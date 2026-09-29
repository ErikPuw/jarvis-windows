import logging
from typing import Any

log = logging.getLogger("jarvis.agent_webcam")

async def run_webcam_agent(
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

    log.info(f"Agent Webcam activated for query: '{user_text}'")

    webcam_tools = get_agent_context_and_tools(["read_webcam"])
    try:
        async with flow_tracker.step("Agent Webcam"):
            async with flow_agents.step(f"Thực thi: {user_text}", emoji="📷", agent_name="Agent Webcam"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=webcam_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Webcam",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Webcam execution: {e}", exc_info=True)
        
        fallback_err = f"Lỗi thực thi Agent Webcam: {e}"
        return fallback_err
