"""Regression test for the silent _NO_AGENT_MESSAGE return in run_orchestrator's
multi-task loop (see engine/orchestrator/__init__.py:128-130). When classify_tasks
picks >=2 agents but dispatch_tasks resolves none of them in every round, the
function returns the apology text directly WITHOUT ever calling deliver() -- the
only place that sends text_chunk/stream_end to the websocket. server.py's caller
does `if res: return res` (server.py:330-331), so this non-empty return short-
circuits the chat fallback too: the client gets nothing at all for that turn.
Run: python tests/test_orchestrator_no_agent_resolved_bug.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.orchestrator as orchestrator


class FakeWs:
    pass


def _patch(monkeys: dict):
    originals = []
    for module, attrs in monkeys.items():
        for name, value in attrs.items():
            originals.append((module, name, getattr(module, name)))
            setattr(module, name, value)

    def restore():
        for module, name, value in originals:
            setattr(module, name, value)
    return restore


def test_no_agent_resolved_across_rounds_should_still_reach_the_user_via_deliver():
    """classify_tasks picks 2 agents (so the multi-round loop is entered, not the
    len==1 fast path); dispatch_tasks resolves none of them (registry miss / every
    agent declined) -- exactly the branch that falls through to `if not accumulated:
    return _NO_AGENT_MESSAGE` at __init__.py:128-130, with no deliver() call."""
    async def scenario():
        calls = {"classify": 0, "dispatch": 0, "combine": 0, "deliver": 0}

        async def fake_classify(*args, **kwargs):
            calls["classify"] += 1
            return [{"agent": "search", "query": "a"}, {"agent": "history", "query": "b"}]

        async def fake_dispatch(tasks, **kwargs):
            calls["dispatch"] += 1
            return []  # every agent declined / unregistered

        async def fake_combine(*args, **kwargs):
            calls["combine"] += 1
            return "should not be called", False

        async def fake_deliver(ws, text):
            calls["deliver"] += 1
            return text

        restore = _patch({
            orchestrator: {
                "classify_tasks": fake_classify,
                "dispatch_tasks": fake_dispatch,
                "combine": fake_combine,
                "deliver": fake_deliver,
            }
        })
        try:
            result = await orchestrator.run_orchestrator(
                user_text="lam gi do la", conversation_history=[], ws=FakeWs(),
            )
        finally:
            restore()
        return result, calls

    result, calls = asyncio.run(scenario())
    assert result == orchestrator._NO_AGENT_MESSAGE, result
    assert calls["dispatch"] == 1, "should give up after round 1 once dispatch resolves nothing"
    assert calls["deliver"] == 1, (
        f"BUG: deliver() was called {calls['deliver']} time(s), expected 1. "
        "run_orchestrator returns a non-empty, user-facing apology message without "
        "ever streaming it to the websocket. Since server.py's caller does "
        "`if res: return res`, the truthy return short-circuits the chat fallback "
        "too -- the client receives NOTHING for this turn (no text_chunk, no "
        "stream_end), leaving the UI waiting indefinitely."
    )


if __name__ == "__main__":
    test_no_agent_resolved_across_rounds_should_still_reach_the_user_via_deliver()
    print("OK: no-agent-resolved regression test passed")
