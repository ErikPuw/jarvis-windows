# -*- coding: utf-8 -*-
import logging
from typing import Any

log = logging.getLogger("jarvis.agent_rag")


async def run_rag_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs,
) -> str:
    from engine.core.actions import (
        get_agent_context_and_tools,
        handle_user_intent_with_tools,
    )

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
        return "Agent RAG chỉ hoạt động khi request hiện tại có tệp đính kèm hợp lệ."

    rag_tools = get_agent_context_and_tools(["rag_tool"])
    log.info(
        "Agent RAG activated: filename=%s",
        attachment_context.filename,
    )

    try:
        async with flow_tracker.step("Agent RAG"):
            async with flow_agents.step(
                f"Thực thi: {user_text}", emoji="📄", agent_name="Agent RAG"
            ):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=rag_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent RAG",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    attachment_context=attachment_context,
                    silent=kwargs.get("silent", False),
                )
            return response_text
    except Exception as e:
        log.error(f"Error in Agent RAG execution: {e}", exc_info=True)
        return f"Lỗi thực thi Agent RAG: {e}"

