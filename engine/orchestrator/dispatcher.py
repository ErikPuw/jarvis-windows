"""Executes the task list produced by classifier.py against real, registered
agents — replaces the old approach of merging tool names into a single LLM
call. record_agent_outcome bookkeeping is centralized here."""

import asyncio
import logging
import time

from engine.orchestrator import registry

log = logging.getLogger("jarvis.orchestrator.dispatcher")

_PRIOR_CHARS = 3000
# note_engine.execute_note_action saves the last assistant message of the history when the
# text carries a save-intent phrase; this phrase is what makes `notes` store the previous
# step's report instead of the literal sub-query.
_NOTES_SAVE_PREFIX = "lưu lại kết quả: "


def _prior_report(done: list[dict]) -> str:
    """Reports of the earlier *successful* steps: the input of a step that needs them."""
    text = "\n\n".join(str(r["result"]) for r in done if r.get("status") == "success")
    # note_engine skips assistant messages that contain '### Kết quả'
    return text.replace("### Kết quả", "## Kết quả")[:_PRIOR_CHARS].strip()


_MIN_REPORT_CHARS = 120  # longer than any one-line status ("Đã mở Notepad thành công")


def _note_should_save_prior(prior: str) -> bool:
    """`notes` called after another agent. The small model tends to write the note from its own
    knowledge instead of copying the agent's report (measured: 1 of 5 chained requests), so when the
    earlier report is substantial the report itself is saved; the model's text is kept only after a
    one-line status ("Đã mở Notepad"), where the note text can only be the user's own content.
    # ponytail: length rule; a substantial report followed by an unrelated own-content note
    # ("tìm giá xăng rồi ghi note mua sữa") saves the report instead. Upgrade: let the model choose between two tools."""
    return len(prior) >= _MIN_REPORT_CHARS


async def dispatch_tasks(
    tasks: list[dict],
    user_text: str,
    conversation_history: list,
    ws,
    flow_tracker=None,
    flow_agents=None,
    attachment_context=None,
    silent: bool = False,
    record_user_text: bool = False,
    prior: list[dict] | None = None,
    step_timeout: float | None = None,
) -> list[dict]:
    """Run every task against its real agent runner and return
    a list of {"agent", "query", "result", "outcome_id", "status"} for each
    task that resolved to a registered agent. Unregistered agents are logged
    and skipped, never raised.

    Tasks run in parallel, except when a task needs the report of an earlier one
    (use_previous=True, or `notes` after another agent, or `prior` reports given by the
    orchestrator's tool-call loop): then they run in list order and it receives the
    earlier successful reports.

    record_user_text: file the outcome under what the USER said instead of the
    classifier's rewritten sub-query. The router replays a learned workflow only
    on an exact match of the user's own words, so a single-agent run must be
    keyed by user_text or it can never be reused.

    runner_kwargs (khoá của task, dict): truyền thêm vào runner — engine/plans dùng để ép tool
    (đích "web" → tools=["web_research"]). step_timeout: giây tối đa cho mỗi runner; quá thì bước
    đó "failed", không ghi learning (spec 2026-09-26)."""

    async def run_one(task: dict, done: list[dict] | None = None):
        agent_name = task.get("agent")
        query = task.get("query") or user_text
        runner = registry.resolve_runner(agent_name)
        if runner is None:
            log.warning(
                "[ORCHESTRATOR] Agent '%s' không có trong AGENT_REGISTRY — bỏ qua task.",
                agent_name,
            )
            return None

        history = list(conversation_history or [])
        prior_text = _prior_report(done) if done else ""
        depends = task.get("use_previous") or (
            # after a failed step `notes` must not save its own sub-query as if it were data either
            agent_name == "notes" and (_note_should_save_prior(prior_text) or any(r.get("status") == "failed" for r in done or []))
        )
        if done and depends:
            if not prior_text:
                # Never run on nothing: `notes` would save the literal sub-query as if it were data.
                log.info("[ORCHESTRATOR] '%s' skipped: no successful earlier step to build on", agent_name)
                return {
                    "agent": agent_name, "query": query, "outcome_id": None, "status": "failed",
                    "result": "Bỏ qua: bước trước chưa thành công nên chưa có kết quả để dùng.",
                }
            history.append({"role": "assistant", "content": prior_text})
            if agent_name == "notes":
                query = _NOTES_SAVE_PREFIX + query

        extra = task.get("runner_kwargs") if isinstance(task.get("runner_kwargs"), dict) else {}
        started_at = int(time.time() * 1000)
        try:
            call = runner(
                user_text=query,
                conversation_history=history,
                ws=ws,
                flow_tracker=flow_tracker,
                flow_agents=flow_agents,
                attachment_context=attachment_context,
                silent=silent,
                **extra,
            )
            result = await (asyncio.wait_for(call, step_timeout) if step_timeout else call)
        except TimeoutError:
            log.warning("[ORCHESTRATOR] Agent '%s' timed out after %ss: %r", agent_name, step_timeout, query[:120])
            return {"agent": agent_name, "query": query, "result": "Quá thời gian thực hiện bước này.",
                    "outcome_id": None, "status": "failed"}
        except Exception as exc:
            log.error("[ORCHESTRATOR] Agent '%s' raised: %s", agent_name, exc, exc_info=True)
            result = f"Lỗi thực thi agent {agent_name}: {exc}"
        ended_at = int(time.time() * 1000)

        if isinstance(result, str):
            from engine.core.guardrails import scrub_untrusted
            result = scrub_untrusted(result)

        if not result:
            # Empty result = the agent declined (request was not really for it).
            log.info("[ORCHESTRATOR] Agent '%s' declined: %r", agent_name, query[:120])
            return None

        outcome_id, status = record_outcome(
            agent_name, user_text if record_user_text else query, result, started_at, ended_at,
        )
        return {
            "agent": agent_name,
            "query": query,
            "result": result,
            "outcome_id": outcome_id,
            "status": status,
        }

    if prior or any(t.get("use_previous") for t in tasks) or any(t.get("agent") == "notes" for t in tasks[1:]):
        resolved, done = [], list(prior or [])
        for t in tasks:
            r = await run_one(t, done)
            if r is not None:
                resolved.append(r)
                done.append(r)
    else:
        results = await asyncio.gather(*(run_one(t) for t in tasks))
        resolved = [r for r in results if r is not None]
    if len(resolved) == 1:
        r = resolved[0]
        setattr(ws, "last_agent_outcome_id", r["outcome_id"])
        setattr(ws, "last_agent_outcome_status", r["status"])
        setattr(ws, "last_agent_outcome_at", time.time())
    return resolved


def record_outcome(agent_name: str, query: str, result: str, started_at: int, ended_at: int):
    try:
        from engine.core.learning import get_learning_engine
        from engine.core.trace_logger import TraceLogger
        # ponytail: closed [started_at, ended_at] window shrinks but doesn't eliminate
        # cross-agent trace contamination under parallel dispatch (two agents finishing
        # in the same millisecond can still overlap) — tag traces with a per-call id
        # if this heuristic proves insufficient in practice.
        traces = [
            t for t in TraceLogger.get_recent_traces(limit=20)
            if started_at <= t.get("timestamp", 0) <= ended_at
        ]
        if any(t.get("outcome") == "failed" for t in traces):
            status = "failed"
        elif any(t.get("outcome") == "success" for t in traces):
            status = "success"
        else:
            status = "cancelled"
        outcome_id = get_learning_engine().record_agent_outcome(agent_name, query, status, result, traces)
        return outcome_id, status
    except Exception as outcome_err:
        log.warning("[ORCHESTRATOR] Failed to record agent outcome: %s", outcome_err)
        return None, None
