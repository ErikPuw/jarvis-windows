"""Agent wrapper for explicit Windows UI Automation workflows."""

import logging
from typing import Any


log = logging.getLogger("jarvis.agent_control")


async def run_control_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs,
) -> str:
    """Run the explicit win_control tool through the standard agent pipeline."""
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

    log.info("Agent Win Control activated for query: %r", user_text)
    control_tools = get_agent_context_and_tools(["win_control"])
    try:
        async with flow_tracker.step("Agent Win Control"):
            async with flow_agents.step(
                f"Thực thi: {user_text}",
                emoji="🪟",
                agent_name="Agent Win Control",
            ):
                return await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=control_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Win Control",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
    except Exception as exc:
        log.error("Error in Agent Win Control execution: %s", exc, exc_info=True)
        return f"Lỗi thực thi Agent Win Control: {exc}"
