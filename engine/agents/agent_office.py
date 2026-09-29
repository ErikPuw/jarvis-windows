import logging
from typing import Any

log = logging.getLogger("jarvis.agent_office")

async def run_office_agent(
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

    attachment_context = kwargs.get("attachment_context")
    if attachment_context is None:
        return "Agent Office chỉ hoạt động khi request hiện tại có tệp đính kèm hợp lệ."

    log.info(f"Agent Office activated for query: '{user_text}'")

    tool_names = ["office_tool"]
    office_tools = get_agent_context_and_tools(tool_names)
    try:
        async with flow_tracker.step("Agent Office"):
            async with flow_agents.step(f"Thực thi: {user_text}", emoji="📂", agent_name="Agent Office"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=office_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Office",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    attachment_context=attachment_context,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Office execution: {e}", exc_info=True)
        fallback_err = f"Lỗi thực thi Agent Office: {e}"
        return fallback_err
