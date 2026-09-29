import logging
from typing import Any

log = logging.getLogger("jarvis.agent_desktop")

_OPEN_KW = ["mở", "mở", "open", "chạy", "start", "khởi động", "launch", "run"]
_CLOSE_KW = ["tắt", "đóng", "đóng", "close", "stop", "dừng"]

def _select_desktop_tools(text: str) -> list[str]:
    tl = text.lower()
    sel = []
    if any(kw in tl for kw in _OPEN_KW):
        sel.append("open_app")
    if any(kw in tl for kw in _CLOSE_KW):
        sel.append("close_app")
    return sel  # no open/close verb -> not a desktop request (used to run BOTH open_app and close_app)

async def run_desktop_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs
) -> str:
    from engine.core.actions import handle_user_intent_with_tools, get_agent_context_and_tools
    if not flow_tracker:
        class NoOpFlowTracker:
            def step(self, label):
                class NoOpStep:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStep()
            async def track(self, *args, **kwargs): pass
        flow_tracker = NoOpFlowTracker()

    if not flow_agents:
        class NoOpFlowAgents:
            def step(self, label, emoji=None, agent_name=None):
                class NoOpStep:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStep()
            async def track(self, *args, **kwargs): pass
        flow_agents = NoOpFlowAgents()

    log.info(f"Agent Desktop activated for query: '{user_text}'")

    tool_names = _select_desktop_tools(user_text)
    log.info(f"Selected desktop tools: {tool_names}")
    # Decline (return "") when the request names no real application: the orchestrator then
    # hands the turn back to normal chat instead of running open_app/close_app on a phrase.
    from engine.tools.desktop_automation import extract_app_name, app_target_exists
    target = extract_app_name(user_text)
    if not tool_names or not target or not await app_target_exists(target):
        log.info("Agent Desktop declined %r: no openable/closable application named (%r)", user_text, target)
        return ""
    desktop_tools = get_agent_context_and_tools(tool_names)
    _TOOL_VI = {
        "open_app": f"Thực thi: {user_text}",
        "close_app": f"Thực thi: {user_text}",
    }
    friendly = " / ".join(_TOOL_VI.get(t, t) for t in tool_names)
    try:
        async with flow_tracker.step("Agent Desktop"):
            async with flow_agents.step(friendly, emoji="💻", agent_name="Agent Desktop"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=desktop_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Desktop",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Desktop execution: {e}", exc_info=True)
        
        fallback_err = f"Lỗi thực thi Agent Desktop: {e}"
        return fallback_err
