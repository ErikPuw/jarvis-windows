"""Tests for engine.orchestrator.run_orchestrator. Run: python tests/test_orchestrator_init.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.orchestrator as orchestrator


class FakeWs:
    pass


def _patch(monkeys: dict):
    """monkeys: {module_object: {attr_name: fake_value}}. Returns a restore fn."""
    originals = []
    for module, attrs in monkeys.items():
        for name, value in attrs.items():
            originals.append((module, name, getattr(module, name)))
            setattr(module, name, value)

    def restore():
        for module, name, value in originals:
            setattr(module, name, value)
    return restore


def test_single_task_fast_path_skips_classifier_and_combine():
    """predetermined_tasks with exactly 1 entry must bypass classify_tasks and
    combine() entirely, returning the agent's own result directly."""
    async def scenario():
        calls = {"classify": 0, "combine": 0}

        async def fake_classify(*args, **kwargs):
            calls["classify"] += 1
            return []

        async def fake_dispatch(tasks, **kwargs):
            assert kwargs["silent"] is False, "single predetermined task must not run silent"
            return [{"agent": "email", "query": "xem thu", "result": "3 email moi", "outcome_id": 1, "status": "success"}]

        async def fake_combine(*args, **kwargs):
            calls["combine"] += 1
            return "should not be used", False

        restore = _patch({
            orchestrator: {
                "classify_tasks": fake_classify,
                "dispatch_tasks": fake_dispatch,
                "combine": fake_combine,
            }
        })
        try:
            result = await orchestrator.run_orchestrator(
                user_text="xem thu",
                conversation_history=[],
                ws=FakeWs(),
                predetermined_tasks=[{"agent": "email", "query": "xem thu"}],
            )
        finally:
            restore()
        return result, calls

    result, calls = asyncio.run(scenario())
    assert result == "3 email moi", result
    assert calls == {"classify": 0, "combine": 0}, calls


def test_no_agent_needed_returns_empty_so_caller_falls_back_to_chat():
    async def scenario():
        async def fake_classify(*args, **kwargs):
            return []

        restore = _patch({orchestrator: {"classify_tasks": fake_classify}})
        try:
            return await orchestrator.run_orchestrator(
                user_text="???", conversation_history=[], ws=FakeWs(),
            )
        finally:
            restore()

    result = asyncio.run(scenario())
    assert result == "", result


def test_multi_task_round_delivers_once_when_satisfied():
    async def scenario():
        calls = {"dispatch": 0, "combine": 0, "deliver": 0}

        async def fake_classify(*args, **kwargs):
            return [{"agent": "email", "query": "a"}, {"agent": "notes", "query": "b"}]

        async def fake_dispatch(tasks, **kwargs):
            calls["dispatch"] += 1
            assert kwargs["silent"] is True
            return [
                {"agent": "email", "query": "a", "result": "ra", "outcome_id": 1, "status": "success"},
                {"agent": "notes", "query": "b", "result": "rb", "outcome_id": 2, "status": "success"},
            ]

        async def fake_combine(user_text, results):
            calls["combine"] += 1
            return "cau tra loi gop", False

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
                user_text="a va b", conversation_history=[], ws=FakeWs(),
            )
        finally:
            restore()
        return result, calls

    result, calls = asyncio.run(scenario())
    assert result == "cau tra loi gop", result
    assert calls == {"dispatch": 1, "combine": 1, "deliver": 1}, calls


def test_bounded_loop_stops_at_max_rounds():
    async def scenario():
        calls = {"classify": 0, "combine": 0, "deliver": 0}

        async def fake_classify(*args, **kwargs):
            calls["classify"] += 1
            return [{"agent": "search", "query": f"round {calls['classify']}"}, {"agent": "history", "query": "x"}]

        async def fake_dispatch(tasks, **kwargs):
            return [
                {"agent": t["agent"], "query": t["query"], "result": f"r-{t['agent']}", "outcome_id": 1, "status": "success"}
                for t in tasks
            ]

        async def fake_combine(user_text, results):
            calls["combine"] += 1
            return "van con thieu", True  # always needs more, to force hitting the cap

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
                user_text="nghien cuu sau", conversation_history=[], ws=FakeWs(),
            )
        finally:
            restore()
        return result, calls

    result, calls = asyncio.run(scenario())
    assert result == "van con thieu", result
    assert calls["classify"] == orchestrator.MAX_ORCHESTRATOR_ROUNDS, calls
    assert calls["deliver"] == 1, "must deliver exactly once even when capped"


def _run_single_with_loop(next_result, status="success", predetermined=None):
    """Single classified task, then the tool-call loop: returns (result, dispatch calls, next_tasks calls, deliveries)."""
    async def scenario():
        dispatched, asked, delivered = [], [], []

        async def fake_classify(*a, **k):
            return [{"agent": "email", "query": "xem thư"}]

        async def fake_dispatch(tasks, **kwargs):
            dispatched.append((tasks, kwargs.get("silent"), kwargs.get("prior")))
            if len(dispatched) == 1:
                return [{"agent": "email", "query": "xem thư", "result": "3 thư mới", "outcome_id": 1, "status": status}]
            return [{"agent": t["agent"], "query": t["query"], "result": "Đã ghi note", "outcome_id": 2, "status": "success"} for t in tasks]

        async def fake_next(user_text, history, done):
            asked.append(list(done))
            return next_result if len(asked) == 1 else []  # the real next_tasks never re-calls an agent that already ran

        async def fake_deliver(ws, text):
            delivered.append(text)
            return text

        restore = _patch({orchestrator: {
            "classify_tasks": fake_classify, "dispatch_tasks": fake_dispatch, "next_tasks": fake_next, "deliver": fake_deliver,
        }})
        try:
            result = await orchestrator.run_orchestrator(
                user_text="xem thư rồi ghi note", conversation_history=[], ws=FakeWs(), predetermined_tasks=predetermined,
            )
        finally:
            restore()
        return result, dispatched, asked, delivered

    return asyncio.run(scenario())


def test_loop_runs_the_next_step_silently_and_delivers_it_once_after_the_first_answer():
    result, dispatched, asked, delivered = _run_single_with_loop([{"agent": "notes", "query": "ghi lại"}])
    assert dispatched[0][1] is False, "first agent streams itself"
    assert dispatched[1][1] is True and dispatched[1][2] and dispatched[1][2][0]["agent"] == "email", dispatched
    assert delivered == ["Đã ghi note"], delivered
    assert result == "3 thư mới\n\nĐã ghi note", result


def test_loop_does_nothing_more_when_the_model_stops_or_the_step_failed_or_agent_was_pinned():
    result, dispatched, asked, delivered = _run_single_with_loop([])
    assert result == "3 thư mới" and len(dispatched) == 1 and not delivered
    result, dispatched, asked, delivered = _run_single_with_loop([{"agent": "notes", "query": "x"}], status="failed")
    assert result == "3 thư mới" and not asked, "a failed step never continues"
    result, dispatched, asked, delivered = _run_single_with_loop(
        [{"agent": "notes", "query": "x"}], predetermined=[{"agent": "email", "query": "xem thư"}])
    assert result == "3 thư mới" and not asked, "@mention / learned workflow are explicit: no loop"


if __name__ == "__main__":
    test_single_task_fast_path_skips_classifier_and_combine()
    test_no_agent_needed_returns_empty_so_caller_falls_back_to_chat()
    test_multi_task_round_delivers_once_when_satisfied()
    test_bounded_loop_stops_at_max_rounds()
    test_loop_runs_the_next_step_silently_and_delivers_it_once_after_the_first_answer()
    test_loop_does_nothing_more_when_the_model_stops_or_the_step_failed_or_agent_was_pinned()
    print("OK: all orchestrator init tests passed")


def test_single_agent_learning_records_the_command_not_the_whole_sentence():
    """Lượt nhờ trực tiếp: classifier vẫn nhận NGUYÊN câu (hiểu ngữ cảnh), agent nhận câu lệnh rút gọn,
    và learning ghi CÂU LỆNH đó — không ghi cả câu (DB/wiki rối, log 2026-09-25 outcome 533-535)."""
    from engine.orchestrator import dispatcher, registry
    long_text = "hôm nay tôi lười mở notepad quá bạn mở giúp tôi được không?"

    async def scenario():
        seen = {}

        async def fake_classify(text, **kwargs):
            seen["classifier_input"] = text
            return [{"agent": "desktop", "query": "mở Notepad"}]

        async def runner(user_text, **kwargs):
            seen["agent_input"] = user_text
            return "Đã mở Notepad."

        async def no_more(*a, **k):
            return []

        restore = _patch({
            orchestrator: {"classify_tasks": fake_classify, "next_tasks": no_more},
            registry: {"resolve_runner": lambda name: runner},
            dispatcher: {"record_outcome": lambda agent, query, *a, **k: seen.setdefault("recorded", query) and (1, "success")},
        })
        try:
            await orchestrator.run_orchestrator(user_text=long_text, conversation_history=[], ws=FakeWs())
        finally:
            restore()
        return seen

    seen = asyncio.run(scenario())
    assert seen["classifier_input"] == long_text
    assert seen["agent_input"] == "mở Notepad"
    assert seen["recorded"] == "mở Notepad"
