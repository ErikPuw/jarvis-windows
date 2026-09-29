# -*- coding: utf-8 -*-
"""
JARVIS Dream Agent Wrapper — Tích hợp Dream Cycle vào hệ thống định tuyến để gửi lệnh 'dream'
(kích hoạt thủ công 1 chu kỳ dọn dẹp/tóm tắt hội thoại + Wiki cũ, ngoài lịch tự động ban đêm).
"""

import logging
from typing import Any

log = logging.getLogger("jarvis.agent_dream")

async def run_dream_agent(
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

    log.info(f"Agent Dream activated for query: '{user_text}'")

    tool_names = ["dream"]
    dream_tools = get_agent_context_and_tools(tool_names)
    try:
        async with flow_tracker.step("Agent Dream"):
            async with flow_agents.step(f"Thực thi: {user_text}", emoji="💤", agent_name="Agent Dream"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=dream_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Dream",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Dream execution: {e}", exc_info=True)

        return f"Lỗi thực thi Agent Dream: {e}"
