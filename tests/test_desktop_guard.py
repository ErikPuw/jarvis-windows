"""Desktop agent must decline requests that name no real app. Run: python tests/test_desktop_guard.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.agents import agent_desktop
from engine.tools import desktop_automation as da
import engine.core.actions as actions
import engine.orchestrator as orchestrator
from engine.orchestrator import dispatcher, registry


def test_no_open_close_verb_selects_no_tool():
    assert agent_desktop._select_desktop_tools("thử lại giọng đọc TTS") == []
    assert agent_desktop._select_desktop_tools("mở Notepad") == ["open_app"]
    assert agent_desktop._select_desktop_tools("tắt Chrome") == ["close_app"]


def test_sentence_is_not_an_app_and_known_app_needs_no_powershell():
    assert asyncio.run(da.app_target_exists("thử lại để tôi nghe giọng đọc TTS xem ra sao")) is False
    assert asyncio.run(da.app_target_exists("")) is False
    assert asyncio.run(da.app_target_exists("Notepad")) is True  # in _KNOWN_APPS, no subprocess


def test_agent_declines_without_running_any_tool():
    async def scenario(text, exists):
        calls = []

        async def boom(*a, **k):
            calls.append(1)
            return "ran"

        async def fake_exists(name):
            return exists

        orig = (actions.handle_user_intent_with_tools, da.app_target_exists)
        actions.handle_user_intent_with_tools, da.app_target_exists = boom, fake_exists
        try:
            return await agent_desktop.run_desktop_agent(text, [], None), len(calls)
        finally:
            actions.handle_user_intent_with_tools, da.app_target_exists = orig

    assert asyncio.run(scenario("thử lại giọng đọc TTS", False)) == ("", 0)      # no verb
    assert asyncio.run(scenario("mở thử lại giọng đọc TTS", False)) == ("", 0)   # verb but no real app
    assert asyncio.run(scenario("mở Notepad", True)) == ("ran", 1)


def test_dispatcher_drops_declined_result_and_orchestrator_hands_back_to_chat():
    async def declined(**kwargs):
        return ""

    orig = registry.resolve_runner
    registry.resolve_runner = lambda name: declined
    try:
        resolved = asyncio.run(dispatcher.dispatch_tasks(
            [{"agent": "desktop", "query": "x"}], user_text="x", conversation_history=[], ws=object(),
        ))
        result = asyncio.run(orchestrator.run_orchestrator(
            user_text="x", conversation_history=[], ws=object(),
            predetermined_tasks=[{"agent": "desktop", "query": "x"}],
        ))
    finally:
        registry.resolve_runner = orig
    assert resolved == [] and result == "", (resolved, result)


if __name__ == "__main__":
    test_no_open_close_verb_selects_no_tool()
    test_sentence_is_not_an_app_and_known_app_needs_no_powershell()
    test_agent_declines_without_running_any_tool()
    test_dispatcher_drops_declined_result_and_orchestrator_hands_back_to_chat()
    print("OK: desktop guard tests passed")
