"""Regression test for cross-round context loss in run_orchestrator's multi-task
loop. dispatch_tasks() is called without prior=accumulated for round >= 2
(engine/orchestrator/__init__.py:104-108), unlike _continue()'s call for the
single-agent path (engine/orchestrator/__init__.py:28-32) which does pass it.
Run: python tests/test_orchestrator_multiround_prior_bug.py"""
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


def test_round_two_dependent_task_should_receive_prior_round_results():
    """Round 1 resolves `search`+`history`; combine() says needs_more; round 2's
    classifier asks for `notes` with use_previous=True to save round 1's report.
    dispatch_tasks must be given prior=accumulated so dispatcher.py can inject
    that report into the dependent task's history -- exactly like _continue()
    does for the single-agent continuation path."""
    async def scenario():
        calls = {"classify": 0}
        dispatch_prior_by_round = []

        async def fake_classify(*args, **kwargs):
            calls["classify"] += 1
            if calls["classify"] == 1:
                return [{"agent": "search", "query": "gia vang"}, {"agent": "history", "query": "x"}]
            return [{"agent": "notes", "query": "luu ket qua", "use_previous": True}]

        async def fake_dispatch(tasks, **kwargs):
            prior = kwargs.get("prior")
            # snapshot: `prior` is the same `accumulated` list object the caller
            # mutates right after this call (accumulated.extend(resolved)) -- append
            # a copy or every stored entry ends up aliased to the final state.
            dispatch_prior_by_round.append(list(prior) if prior is not None else None)
            if calls["classify"] == 1:
                return [
                    {"agent": "search", "query": "gia vang", "result": "vang SJC 82 trieu", "outcome_id": 1, "status": "success"},
                    {"agent": "history", "query": "x", "result": "rh", "outcome_id": 2, "status": "success"},
                ]
            return [{"agent": "notes", "query": "luu ket qua", "result": "Da ghi note", "outcome_id": 3, "status": "success"}]

        state = {"combined_once": False}

        async def fake_combine(user_text, results):
            if not state["combined_once"]:
                state["combined_once"] = True
                return "chua du", True  # round 1: force a round 2
            return "da du", False

        async def fake_deliver(ws, text):
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
            await orchestrator.run_orchestrator(
                user_text="tra gia vang", conversation_history=[], ws=FakeWs(),
            )
        finally:
            restore()
        return dispatch_prior_by_round

    dispatch_prior_by_round = asyncio.run(scenario())
    assert len(dispatch_prior_by_round) == 2, dispatch_prior_by_round
    round1_prior, round2_prior = dispatch_prior_by_round
    assert not round1_prior, "round 1 has no earlier results, prior should be empty (None or [])"
    assert round2_prior, (
        "BUG: round 2's dispatch_tasks call is missing prior=accumulated "
        "(engine/orchestrator/__init__.py:104-108 never threads round 1's results "
        "into round 2's dispatch call, unlike _continue() at __init__.py:28-32) "
        "-- a use_previous task discovered in round 2 silently loses round 1's report."
    )


if __name__ == "__main__":
    test_round_two_dependent_task_should_receive_prior_round_results()
    print("OK: multi-round prior-context regression test passed")
