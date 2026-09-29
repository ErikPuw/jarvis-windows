import logging
import re
from typing import Any

log = logging.getLogger("jarvis.agent_notes")

def _select_tools(text: str) -> list[str]:
    q_lower = text.lower()
    is_read_intent = any(kw in q_lower for kw in [
        "đọc ghi chú", "đọc note", "xem chi tiết", "nội dung ghi chú", "đọc ghi chú số"
    ]) or (any(kw in q_lower for kw in ["đọc", "xem", "chi tiết"]) and any(kw in q_lower for kw in ["ghi chú", "note"]) and re.search(r"\d+", q_lower))
    
    is_save_intent = any(kw in q_lower for kw in [
        "vừa tìm được", "vừa tìm", "bạn vừa nói", "câu vừa rồi", "phản hồi trước", 
        "câu nói vừa rồi", "câu vừa nói", "lưu lại kết quả", "lưu thông tin vừa", "lưu thông tin", "ghi chú thông tin"
    ])

    if is_read_intent and not is_save_intent:
        return ["read_note"]
    return ["take_note"]

async def run_notes_agent(
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

    log.info(f"Agent Notes activated for query: '{user_text}'")

    tool_names = _select_tools(user_text)
    notes_tools = get_agent_context_and_tools(tool_names)
    try:
        async with flow_tracker.step("Agent Notes"):
            async with flow_agents.step(f"Thực thi: {user_text}", emoji="📝", agent_name="Agent Notes"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=notes_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Notes",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    **kwargs
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Notes execution: {e}", exc_info=True)
        
        fallback_err = f"Lỗi thực thi Agent Notes: {e}"
        return fallback_err
