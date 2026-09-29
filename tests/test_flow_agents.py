"""Regression tests for engine.main.flow_agents card identity. Run: python tests/test_flow_agents.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.main.flow_agents import FlowAgents


class Recorder:
    """Collects the interactive cards a FlowAgents instance emits."""
    def __init__(self):
        self.cards = []

    async def send(self, _ws, payload):
        self.cards.append(payload["card"])

    def ids(self, status=None):
        return [c["id"] for c in self.cards if status is None or c["status"] == status]


def _flow():
    rec = Recorder()
    return FlowAgents(ws=object(), safe_send=rec.send), rec


def test_turn_id_changes_across_resets_in_the_same_second():
    """Two turns inside one wall-clock second must not share a turn id."""
    flow, _ = _flow()
    first = flow._turn_id
    flow.reset()
    second = flow._turn_id
    flow.reset()
    third = flow._turn_id
    assert first != second, f"turn id repeated across reset: {first}"
    assert second != third, f"turn id repeated across reset: {second}"


def test_card_ids_differ_across_turns_in_the_same_second():
    """The real symptom: turn 2's card overwrote turn 1's card in the UI."""
    async def scenario():
        flow, rec = _flow()
        async with flow.step("tim kiem", "🔍", "Agent Search"):
            pass
        flow.reset()
        async with flow.step("tim kiem", "🔍", "Agent Search"):
            pass
        return rec
    rec = asyncio.run(scenario())
    active = rec.ids("active")
    assert len(active) == 2, active
    assert active[0] != active[1], f"both turns produced the same card id: {active[0]}"


def test_concurrent_same_agent_in_one_turn_gets_distinct_cards():
    """Guards the earlier per-call-id fix: two parallel calls, two cards."""
    async def scenario():
        flow, rec = _flow()
        async def one():
            async with flow.step("tim kiem", "🔍", "Agent Search"):
                await asyncio.sleep(0.01)
        await asyncio.gather(one(), one())
        return rec
    rec = asyncio.run(scenario())
    active = rec.ids("active")
    completed = rec.ids("completed")
    assert len(active) == 2, active
    assert active[0] != active[1], "concurrent calls collided on one card id"
    assert len(completed) == 2, f"a concurrent call's completion was swallowed: {completed}"


def test_terminal_status_without_active_is_ignored():
    """A stray completed for an unknown card must not reach the frontend."""
    async def scenario():
        flow, rec = _flow()
        await flow.track("tim kiem", "completed", "🔍", "Agent Search", call_id=99)
        return rec
    rec = asyncio.run(scenario())
    assert rec.cards == [], rec.cards


def test_failure_inside_step_emits_failed():
    async def scenario():
        flow, rec = _flow()
        try:
            async with flow.step("tim kiem", "🔍", "Agent Search"):
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        return rec
    rec = asyncio.run(scenario())
    assert rec.ids("failed"), rec.cards
    assert len(rec.ids("failed")) == 1


def test_fail_all_active_closes_every_open_card():
    async def scenario():
        flow, rec = _flow()
        await flow.track("a", "active", "🔍", "Agent Search", call_id=1)
        await flow.track("b", "active", "📷", "Agent Webcam", call_id=2)
        await flow.fail_all_active()
        return rec, flow
    rec, flow = asyncio.run(scenario())
    assert len(rec.ids("failed")) == 2, rec.ids("failed")
    assert flow._active_cards == {}, flow._active_cards


if __name__ == "__main__":
    test_turn_id_changes_across_resets_in_the_same_second()
    test_card_ids_differ_across_turns_in_the_same_second()
    test_concurrent_same_agent_in_one_turn_gets_distinct_cards()
    test_terminal_status_without_active_is_ignored()
    test_failure_inside_step_emits_failed()
    test_fail_all_active_closes_every_open_card()
    print("OK: all flow_agents regression tests passed")
