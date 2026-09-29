"""Context cho nhánh chat general / general_knowledge (spec 2026-09-25 mục 3)."""
import asyncio
import logging
import re

from engine.prompts import chat as chat_prompts

log = logging.getLogger("jarvis.router.chat")

_ASKS_ABOUT_AGENTS = re.compile(r"(?<!\w)agents?(?!\w)", re.IGNORECASE)


async def build_chat_messages(kind: str, text: str, ctx) -> tuple[list[dict], str]:
    """Trả về (messages, text) — text là bản sau hook ON_MESSAGE_RECEIVE."""
    route = kind
    flow_tracker = ctx.flow_tracker
    conversation_history = ctx.conversation_history

    try:
        async with flow_tracker.step("Hook ON_MESSAGE_RECEIVE"):
            from engine.tools.load_hook import HookRegistry, HOOKS
            history_list = list(conversation_history) if conversation_history else []
            hook_res = await HookRegistry.get_instance().fire_async(
                HOOKS.ON_MESSAGE_RECEIVE,
                text=text,
                conversation_history=history_list
            )
            text = hook_res.get("text", text)
            if "conversation_history" in hook_res:
                conversation_history = hook_res["conversation_history"]
            _injected = hook_res.get("__injected_context", "")
    except Exception as e:
        log.warning(f"Hook fire ON_MESSAGE_RECEIVE failed: {e}")
        _injected = ""

    # Góp nhặt reference data
    reference_data = {}
    if _injected:
        reference_data["hook_context"] = _injected[:2000]

    # MCP Task
    if route not in ("general",):
        try:
            async with flow_tracker.step("MCP context"):
                from engine.core import mcp_context
                mcp_ctx = await mcp_context.build_mcp_context(text, route=route, flow_tracker=flow_tracker)
                if mcp_ctx:
                    reference_data["mcp_data"] = mcp_ctx
        except Exception as e:
            log.warning(f"MCP context task failed: {e}")

    # Tên agent chỉ nạp khi ngài hỏi về agent: để cố định trong <capabilities> làm mất lời đề nghị
    # (đo 2026-09-26: đề nghị kiểm tra bảo mật 10/10 → 0/10).
    if route == "general" and _ASKS_ABOUT_AGENTS.search(text or ""):
        from engine.prompts import catalog
        reference_data["agent_names"] = catalog.agent_names_text()

    # Learned experiences (lessons only, không nạp key facts vì đã có trong <about_user>)
    if route == "general":  # bài học giao tiếp chỉ cho chat; tra cứu (general_knowledge) không cần
        try:
            from engine.core.learning import get_learning_engine
            db_engine = get_learning_engine()
            # Chỉ bài học (type lesson): sở thích/sự thật đã ở <about_user> — mỗi dữ liệu một kênh
            learnings = [l for l in await asyncio.to_thread(db_engine.recall_learnings, text, 10)
                         if l.get("type") == "lesson"][:3]
            if learnings:
                reference_data["lessons"] = [f"{l['content']} (Nguồn: {l.get('source', '')})" for l in learnings]
            # Không nạp kết quả agent gần nhất (2026-09-27): "[email] xem email → thành công" ở mọi lượt chat làm
            # model đề nghị lại chính tool đó. Câu trả lời của agent đã nằm trong lịch sử.
        except Exception as le:
            log.warning(f"Failed to load learned experiences: {le}")

    # Lịch sử hội thoại từ DB (cùng nguồn với gate)
    try:
        from engine.core.memory import build_unified_routing_history
        db_history = await asyncio.to_thread(build_unified_routing_history, text, conversation_history, 12)
    except Exception as he:
        log.warning(f"Failed to load unified history from DB: {he}")
        db_history = conversation_history

    action_declined = getattr(ctx, "action_declined", False)

    messages = chat_prompts.build_chat_messages(
        user_text=text,
        conversation_history=db_history,
        route=route,
        action_declined=action_declined,
        reference_data=reference_data,
    )

    return messages, text
