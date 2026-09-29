"""Agent entry point for read-only New Outlook checks."""

from __future__ import annotations

import logging
from typing import Any


log = logging.getLogger("jarvis.agent_email")


def _select_tools(user_text: str) -> list[str]:
    intent_text = user_text.casefold().replace("lịch sử", "")
    wants_calendar = any(
        keyword in intent_text
        for keyword in (
            "calendar",
            "lịch",
            "cuộc hẹn",
            "sinh nhật",
            "ngày lễ",
        )
    )
    wants_mail = any(
        keyword in intent_text
        for keyword in ("email", "e-mail", "mail", "thư", "hộp thư")
    )
    if wants_mail and wants_calendar:
        return ["check_mail", "check_calendar"]
    if wants_calendar:
        return ["check_calendar"]
    return ["check_mail"]


async def run_email_agent(
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
            def step(self, _label):
                return NoOpStep()

        class NoOpStep:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        flow_tracker = NoOpFlowTracker()

    if not flow_agents:
        class NoOpFlowAgents:
            def step(self, _label, **_kwargs):
                return NoOpAgentStep()

        class NoOpAgentStep:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        flow_agents = NoOpFlowAgents()

    log.info("Agent Email activated for query: %r", user_text)
    email_tools = get_agent_context_and_tools(
        _select_tools(user_text)
    )
    try:
        async with flow_tracker.step("Agent Email"):
            async with flow_agents.step(
                f"Thực thi: {user_text}",
                emoji="📧",
                agent_name="Agent Email",
            ):
                return await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=email_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Email",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    **kwargs,
                )
    except Exception as exc:
        log.error("Error in Agent Email execution: %s", exc, exc_info=True)
        return f"Lỗi thực thi Agent Email: {exc}"
