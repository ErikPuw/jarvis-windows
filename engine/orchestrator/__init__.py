"""Centralized agent orchestrator — single entry point that engine.router
calls for anything beyond general chat / general_knowledge."""

import logging

from engine.orchestrator.classifier import classify_tasks, next_tasks
from engine.orchestrator.dispatcher import dispatch_tasks
from engine.orchestrator.synthesizer import combine, deliver

log = logging.getLogger("jarvis.orchestrator")

MAX_ORCHESTRATOR_ROUNDS = 3

_NO_AGENT_MESSAGE = "Xin lỗi, tôi chưa xác định được công cụ phù hợp cho yêu cầu này, thưa ngài."

# Agent dùng được tệp đính kèm; định dạng lấy từ chính tool của chúng để bảng chọn không lệch.
ATTACHMENT_AGENTS = {"rag", "office", "image"}
_OFFICE_EXT = (".docx", ".xlsx", ".pptx")


def attachment_agents_for(extension) -> list[str]:
    """Agent đọc được định dạng này, theo thứ tự hiện trên bảng chọn. Không rõ đuôi → coi như mọi agent."""
    if not extension:
        return sorted(ATTACHMENT_AGENTS)
    from engine.tools.image_engine import SUPPORTED_INPUT
    from engine.tools.rag_tool import SUPPORTED_DOCUMENTS
    return ([a for a, ok in (("rag", extension in SUPPORTED_DOCUMENTS), ("office", extension in _OFFICE_EXT),
                             ("image", extension in SUPPORTED_INPUT)) if ok])


class AttachmentIgnored(Exception):
    """Có tệp đính kèm nhưng classifier chọn toàn agent không dùng tệp (log 2026-09-28: PDF +
    "lưu trữ dữ liệu" → notes). Router hỏi ngài chọn cách xử lý tệp thay vì chạy nhầm."""


async def _continue(user_text, conversation_history, ws, flow_tracker, flow_agents, attachment_context, done):
    """Native tool-call loop after a single agent already streamed its answer (spec 2026-09-21,
    hướng A): show the model that agent's report and let it call the next one if the request has
    another step ("…rồi ghi lại vào note"). Follow-up steps run silent and their result is delivered
    once, after the first answer. Returns the text of everything the user was shown."""
    first = done[0]["result"]
    accumulated, texts = list(done), []
    for _ in range(MAX_ORCHESTRATOR_ROUNDS - 1):
        more = await next_tasks(user_text, conversation_history, accumulated)
        if not more:
            break
        step = await dispatch_tasks(
            more, user_text=user_text, conversation_history=conversation_history, ws=ws,
            flow_tracker=flow_tracker, flow_agents=flow_agents,
            attachment_context=attachment_context, silent=True, prior=accumulated,
        )
        if not step:
            break
        accumulated.extend(step)
        texts.append(step[0]["result"] if len(step) == 1 else (await combine(user_text, step))[0])
    if not texts:
        return first
    delivered = await deliver(ws, "\n\n".join(texts))
    return f"{first}\n\n{delivered}"


async def run_orchestrator(
    user_text: str,
    conversation_history: list,
    ws,
    flow_tracker=None,
    flow_agents=None,
    attachment_context=None,
    predetermined_tasks: list | None = None,
    offer_context: str = "",
    **kwargs,
) -> str:
    """Resolve which registered agent(s) handle user_text, run them for
    real, and return the final answer already delivered to ws.

    predetermined_tasks lets a caller that already knows the agent (an
    explicit @mention, or an attachment_clarify selection) skip
    classification entirely.

    IMPORTANT for maintainers: the single-agent path below (len(tasks)==1)
    does NOT go through combine()/deliver() for its own answer — that agent's own
    handle_user_intent_with_tools call already streamed its answer directly
    to ws (silent=False). Calling deliver() there would double-stream and
    send a second stream_end. Only the >=2-task path (which dispatches with
    silent=True, so nothing has been streamed yet) reaches combine()+deliver().
    """
    tasks = predetermined_tasks if predetermined_tasks is not None else await classify_tasks(
        user_text, conversation_history=conversation_history, attachment_context=attachment_context,
        offer_context=offer_context,
    )
    if not tasks:
        # The gate said "tool" but the classifier found none: the request is
        # really chat. An empty result makes the caller fall through to the
        # normal chat flow instead of answering with a canned apology.
        log.info("[ORCHESTRATOR] No agent needed, handing back to chat: %r", user_text[:200])
        return ""
    # Tệp không agent nào đọc được (.zip…): làm tiếp việc trong câu, bỏ qua tệp.
    if (attachment_context is not None and predetermined_tasks is None
            and attachment_agents_for(getattr(attachment_context, "extension", None))
            and not any(t.get("agent") in ATTACHMENT_AGENTS for t in tasks)):
        log.warning("[ORCHESTRATOR] Attachment ignored by classifier %s — asking the user", [t.get("agent") for t in tasks])
        raise AttachmentIgnored()

    if len(tasks) == 1:
        # Single agent: let it own the stream directly, exactly like the
        # pre-redesign single-route dispatch did — no synthesis LLM call.
        # Learning ghi câu lệnh agent nhận, không ghi cả câu ngài nói: classifier chỉ được
        # bớt từ (quy tắc F), nên câu lệnh vẫn là lời của ngài, gọn và đúng ý định (2026-09-25).
        resolved = await dispatch_tasks(
            tasks, user_text=user_text, conversation_history=conversation_history, ws=ws,
            flow_tracker=flow_tracker, flow_agents=flow_agents,
            attachment_context=attachment_context, silent=False,
        )
        if not resolved:
            return ""  # the agent declined (or is unregistered): fall back to normal chat
        if predetermined_tasks is not None or resolved[0].get("status") != "success":
            return resolved[0]["result"]  # explicit @mention / learned workflow, or a failed step: no continuation
        return await _continue(
            user_text, conversation_history, ws, flow_tracker, flow_agents, attachment_context, resolved,
        )

    accumulated: list[dict] = []
    extra_context = ""
    for round_no in range(1, MAX_ORCHESTRATOR_ROUNDS + 1):
        if round_no > 1:
            tasks = await classify_tasks(
                user_text, conversation_history=conversation_history,
                attachment_context=attachment_context, extra_context=extra_context,
            )
            if not tasks:
                break

        resolved = await dispatch_tasks(
            tasks, user_text=user_text, conversation_history=conversation_history, ws=ws,
            flow_tracker=flow_tracker, flow_agents=flow_agents,
            attachment_context=attachment_context, silent=True, prior=accumulated,
        )
        if not resolved:
            break
        accumulated.extend(resolved)

        text, needs_more = await combine(user_text, accumulated)
        is_last_round = round_no == MAX_ORCHESTRATOR_ROUNDS
        if not needs_more or is_last_round:
            if needs_more and is_last_round:
                log.warning(
                    "[ORCHESTRATOR] Reached max rounds (%d) still needing more info: %r",
                    MAX_ORCHESTRATOR_ROUNDS, user_text[:200],
                )
            return await deliver(ws, text)

        extra_context = (
            f"Đã có kết quả các vòng trước:\n{text}\n\n"
            "Hãy chọn thêm agent để bổ sung thông tin còn thiếu."
        )

    if not accumulated:
        log.warning("[ORCHESTRATOR] No registered agent matched: %r", user_text[:200])
        return await deliver(ws, _NO_AGENT_MESSAGE)

    return await deliver(ws, text)
