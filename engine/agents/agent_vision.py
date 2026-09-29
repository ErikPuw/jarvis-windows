import logging
import json
import asyncio
import base64
from typing import Any

log = logging.getLogger("jarvis.agent_vision")

_ALL_TOOLS = ["read_screen", "cap_screen"]

_CAP_SRC = ["chụp màn hình","chụp"," chụp hình"]
_READ_SRC = ["xem màn hình","đọc màn hình","nhìn màn hình","nhìn"] 

def _select_tools(text: str) -> list[str]:
    tl = text.lower()
    selected = []
    if any(kw in tl for kw in _CAP_SRC):
        selected.append("cap_screen")
    if any(kw in tl for kw in _READ_SRC):
        selected.append("read_screen")
    return selected if selected else _ALL_TOOLS

async def run_vision_agent(
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

    log.info(f"Agent Vision activated for query: '{user_text}'")
    
    tool_names = _select_tools(user_text)
    vision_tools = get_agent_context_and_tools(tool_names)
    _TOOL_VI = {
        "read_screen": f"Thực thi: {user_text}",
        "cap_screen": f"Thực thi: {user_text}",
    }
    friendly = " / ".join(_TOOL_VI.get(t, t) for t in tool_names)
    try:
        async with flow_tracker.step("Agent Vision"):
            async with flow_agents.step(friendly, emoji="👁️", agent_name="Agent Vision"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=vision_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Vision",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Vision execution: {e}", exc_info=True)
        
        fallback_err = f"Lỗi thực thi Agent Vision: {e}"
        return fallback_err
