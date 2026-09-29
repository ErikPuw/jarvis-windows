"""Tests for engine.orchestrator.dispatcher. Run: python tests/test_orchestrator_dispatcher.py"""
import asyncio
import functools
import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import dispatcher, registry


def _no_real_db(fn):
    """Dispatch ghi agent_outcomes qua get_learning_engine(); không có cái này test
    ghi các dòng fake vào data/jarvis.db thật và lọt vào prompt của JARVIS."""
    @functools.wraps(fn)
    def wrapper():
        from engine.core import learning

        class _Sink:
            def record_agent_outcome(self, *a, **k):
                return "test-outcome"

        original = learning.get_learning_engine
        learning.get_learning_engine = lambda: _Sink()
        try:
            return fn()
        finally:
            learning.get_learning_engine = original
    return wrapper


class FakeWs:
    pass


def _install_fake_agent_module(module_name: str, runner_name: str, seen: list):
    """Registers a throwaway module in sys.modules so registry.resolve_runner
    can 'import' it without touching the real engine.agents package."""
    module = types.ModuleType(module_name)

    async def fake_runner(**kwargs):
        seen.append(kwargs)
        return f"ket qua tu {module_name}"

    setattr(module, runner_name, fake_runner)
    sys.modules[module_name] = module
    return module


@_no_real_db
def test_dispatch_skips_unregistered_agent_without_raising():
    async def scenario():
        ws = FakeWs()
        tasks = [{"agent": "khong_ton_tai", "query": "x"}]
        return await dispatcher.dispatch_tasks(
            tasks, user_text="x", conversation_history=[], ws=ws,
        )
    resolved = asyncio.run(scenario())
    assert resolved == [], resolved


@_no_real_db
def test_dispatch_calls_real_runner_and_forwards_silent():
    seen = []
    _install_fake_agent_module("tests._fake_agent_dispatch_1", "run_fake_agent", seen)
    original_registry = dict(dispatcher.registry.AGENT_REGISTRY)
    dispatcher.registry.AGENT_REGISTRY["fake"] = {
        "module": "tests._fake_agent_dispatch_1",
        "runner": "run_fake_agent",
    }
    try:
        async def scenario():
            ws = FakeWs()
            tasks = [{"agent": "fake", "query": "lam gi do"}]
            return await dispatcher.dispatch_tasks(
                tasks, user_text="lam gi do", conversation_history=[], ws=ws, silent=True,
            )
        resolved = asyncio.run(scenario())
    finally:
        dispatcher.registry.AGENT_REGISTRY.clear()
        dispatcher.registry.AGENT_REGISTRY.update(original_registry)
        del sys.modules["tests._fake_agent_dispatch_1"]

    assert len(resolved) == 1, resolved
    assert resolved[0]["agent"] == "fake"
    assert resolved[0]["result"] == "ket qua tu tests._fake_agent_dispatch_1"
    assert seen[0]["silent"] is True, seen[0]
    assert seen[0]["user_text"] == "lam gi do"


@_no_real_db
def test_dispatch_runs_multiple_tasks_in_parallel():
    seen_a, seen_b = [], []
    _install_fake_agent_module("tests._fake_agent_dispatch_a", "run_fake_agent", seen_a)
    _install_fake_agent_module("tests._fake_agent_dispatch_b", "run_fake_agent", seen_b)
    original_registry = dict(dispatcher.registry.AGENT_REGISTRY)
    dispatcher.registry.AGENT_REGISTRY["fake_a"] = {"module": "tests._fake_agent_dispatch_a", "runner": "run_fake_agent"}
    dispatcher.registry.AGENT_REGISTRY["fake_b"] = {"module": "tests._fake_agent_dispatch_b", "runner": "run_fake_agent"}
    try:
        async def scenario():
            ws = FakeWs()
            tasks = [{"agent": "fake_a", "query": "a"}, {"agent": "fake_b", "query": "b"}]
            return await dispatcher.dispatch_tasks(
                tasks, user_text="a va b", conversation_history=[], ws=ws, silent=True,
            )
        resolved = asyncio.run(scenario())
    finally:
        dispatcher.registry.AGENT_REGISTRY.clear()
        dispatcher.registry.AGENT_REGISTRY.update(original_registry)
        del sys.modules["tests._fake_agent_dispatch_a"]
        del sys.modules["tests._fake_agent_dispatch_b"]

    assert len(resolved) == 2, resolved
    assert {r["agent"] for r in resolved} == {"fake_a", "fake_b"}


def test_record_outcome_ignores_traces_outside_window():
    """Regression for cross-agent contamination under parallel dispatch: traces
    before started_at or after ended_at (e.g. produced by a concurrently
    running sibling agent) must not affect this call's status."""
    from engine.core import trace_logger, learning

    started_at, ended_at = 1000, 2000
    fake_traces = [
        {"timestamp": 500, "outcome": "failed"},   # before window (other agent) - ignore
        {"timestamp": 1500, "outcome": "success"},  # inside window - counted
        {"timestamp": 2500, "outcome": "failed"},   # after window (other agent) - ignore
    ]

    class FakeLearningEngine:
        def __init__(self):
            self.calls = []

        def record_agent_outcome(self, agent_name, query, status, result, traces):
            self.calls.append((agent_name, query, status, result, traces))
            return "fake-outcome-id"

    fake_engine = FakeLearningEngine()
    original_get_recent_traces = trace_logger.TraceLogger.get_recent_traces
    original_get_learning_engine = learning.get_learning_engine
    trace_logger.TraceLogger.get_recent_traces = staticmethod(lambda limit=10: fake_traces)
    learning.get_learning_engine = lambda: fake_engine
    try:
        outcome_id, status = dispatcher.record_outcome(
            "fake", "query", "result", started_at, ended_at,
        )
    finally:
        trace_logger.TraceLogger.get_recent_traces = original_get_recent_traces
        learning.get_learning_engine = original_get_learning_engine

    assert outcome_id == "fake-outcome-id", outcome_id
    # Only the in-window success trace should have been considered, despite the
    # out-of-window "failed" traces on both sides — so status must be "success".
    assert status == "success", status
    assert len(fake_engine.calls) == 1
    passed_traces = fake_engine.calls[0][4]
    assert passed_traces == [{"timestamp": 1500, "outcome": "success"}], passed_traces


def test_single_agent_outcome_is_filed_under_the_users_own_words():
    """Learning replays a workflow only on an exact match of what the user said."""
    async def scenario(flag):
        filed = []

        async def runner(**kwargs):
            return "ok"

        orig = (registry.resolve_runner, dispatcher.record_outcome)
        registry.resolve_runner = lambda name: runner
        dispatcher.record_outcome = lambda agent, query, *a, **k: filed.append(query) or (1, "success")
        try:
            await dispatcher.dispatch_tasks(
                [{"agent": "search", "query": "tìm tin tức nvidia"}],
                user_text="bạn tìm tin tức về nvidia có gì nổi bật không?",
                conversation_history=[], ws=type("W", (), {})(), record_user_text=flag,
            )
        finally:
            registry.resolve_runner, dispatcher.record_outcome = orig
        return filed

    assert asyncio.run(scenario(True)) == ["bạn tìm tin tức về nvidia có gì nổi bật không?"]
    assert asyncio.run(scenario(False)) == ["tìm tin tức nvidia"]


def _seq_run(tasks, results_by_agent):
    """Run dispatch_tasks with fake runners; returns (resolved, calls) where calls holds each runner's input."""
    async def scenario():
        calls = []

        def make(agent):
            async def runner(user_text, conversation_history, **kw):
                calls.append({"agent": agent, "query": user_text, "history": conversation_history})
                return results_by_agent[agent]
            return runner

        orig = (registry.resolve_runner, dispatcher.record_outcome)
        registry.resolve_runner = lambda name: make(name)
        dispatcher.record_outcome = lambda agent, q, result, *a, **k: (1, "failed" if str(result).startswith("Lỗi") else "success")
        try:
            resolved = await dispatcher.dispatch_tasks(
                tasks, user_text="x", conversation_history=[{"role": "user", "content": "hi"}], ws=type("W", (), {})(), silent=True,
            )
        finally:
            registry.resolve_runner, dispatcher.record_outcome = orig
        return resolved, calls

    return asyncio.run(scenario())


def test_dependent_task_runs_after_and_receives_the_earlier_report():
    tasks = [{"agent": "email", "query": "kiểm tra email"},
             {"agent": "notes", "query": "ghi note nội dung email", "use_previous": True}]
    resolved, calls = _seq_run(tasks, {"email": "Có 3 thư mới ### Kết quả", "notes": "Đã ghi"})
    assert [c["agent"] for c in calls] == ["email", "notes"], calls
    notes = calls[1]
    assert notes["query"] == "lưu lại kết quả: ghi note nội dung email", notes["query"]
    assert notes["history"][-1] == {"role": "assistant", "content": "Có 3 thư mới ## Kết quả"}, notes["history"]
    assert calls[0]["history"] == [{"role": "user", "content": "hi"}], "first step gets no injected report"
    assert [r["agent"] for r in resolved] == ["email", "notes"]


def test_dependent_task_is_skipped_when_the_earlier_step_failed():
    tasks = [{"agent": "email", "query": "kiểm tra email"},
             {"agent": "notes", "query": "ghi note nội dung email", "use_previous": True}]
    resolved, calls = _seq_run(tasks, {"email": "Lỗi thực thi agent email: x", "notes": "KHÔNG ĐƯỢC CHẠY"})
    assert [c["agent"] for c in calls] == ["email"], "notes must not run on nothing"
    assert resolved[1]["status"] == "failed" and "Bỏ qua" in resolved[1]["result"], resolved


def test_independent_tasks_still_run_in_parallel_without_injection():
    tasks = [{"agent": "desktop", "query": "mở Notepad"}, {"agent": "search", "query": "tin bão"}]
    resolved, calls = _seq_run(tasks, {"desktop": "ok", "search": "tin"})
    assert all(c["history"] == [{"role": "user", "content": "hi"}] for c in calls) and len(resolved) == 2


LONG_REPORT = "Ngài có 3 thư mới: 1) Google cảnh báo bảo mật đăng nhập lạ vào tài khoản của ngài; 2) Nebius cập nhật điều khoản dịch vụ; 3) Epic Games gửi biên lai đơn hàng SPX8891234 cho ngài."


def test_notes_after_a_substantial_report_saves_the_report_not_the_models_own_text():
    """Live Qwen wrote the note from its own knowledge (DDR5) instead of the search result."""
    own_text = "RAM DDR5: công nghệ bộ nhớ thế hệ mới với tốc độ cao hơn DDR4, hỗ trợ dung lượng lớn hơn."
    resolved, calls = _seq_run(
        [{"agent": "search", "query": "thông tin RAM DDR5"}, {"agent": "notes", "query": own_text}],
        {"search": LONG_REPORT, "notes": "Đã ghi"},
    )
    notes = calls[1]
    assert notes["query"] == "lưu lại kết quả: " + own_text, notes
    assert notes["history"][-1]["content"] == LONG_REPORT, notes


def test_notes_keeps_the_users_own_short_content():
    for prior in ("Đã thực hiện: mở Notepad",):  # a one-line status: nothing worth saving, so the note text is the user's own
        resolved, calls = _seq_run(
            [{"agent": "desktop", "query": "mở Notepad"}, {"agent": "notes", "query": "ghi note mua sữa"}],
            {"desktop": prior, "notes": "Đã ghi"},
        )
        assert [c["agent"] for c in calls] == ["desktop", "notes"], calls
        assert calls[1]["query"] == "ghi note mua sữa", calls[1]
        assert calls[1]["history"] == [{"role": "user", "content": "hi"}], "own content: nothing injected"


def test_prior_reports_from_the_tool_call_loop_seed_a_later_step():
    async def scenario():
        seen = []

        async def runner(user_text, conversation_history, **kw):
            seen.append((user_text, conversation_history))
            return "Đã ghi"

        orig = (registry.resolve_runner, dispatcher.record_outcome)
        registry.resolve_runner = lambda name: runner
        dispatcher.record_outcome = lambda *a, **k: (1, "success")
        try:
            await dispatcher.dispatch_tasks(
                [{"agent": "notes", "query": "ghi lại nội dung thư"}], user_text="x", conversation_history=[],
                ws=type("W", (), {})(), silent=True,
                prior=[{"agent": "email", "query": "xem thư", "result": LONG_REPORT, "status": "success"}],
            )
        finally:
            registry.resolve_runner, dispatcher.record_outcome = orig
        return seen

    seen = asyncio.run(scenario())
    assert seen[0][0].startswith("lưu lại kết quả: ") and seen[0][1][-1]["content"] == LONG_REPORT, seen


def test_notes_is_skipped_after_a_failed_step():
    resolved, calls = _seq_run(
        [{"agent": "email", "query": "xem thư"}, {"agent": "notes", "query": "ghi lại nội dung thư"}],
        {"email": "Lỗi thực thi agent email: x", "notes": "KHÔNG ĐƯỢC CHẠY"},
    )
    assert [c["agent"] for c in calls] == ["email"], "notes must not save its own sub-query after a failed step"
    assert resolved[1]["status"] == "failed", resolved


if __name__ == "__main__":
    test_dispatch_skips_unregistered_agent_without_raising()
    test_dispatch_calls_real_runner_and_forwards_silent()
    test_dispatch_runs_multiple_tasks_in_parallel()
    test_record_outcome_ignores_traces_outside_window()
    test_single_agent_outcome_is_filed_under_the_users_own_words()
    test_dependent_task_runs_after_and_receives_the_earlier_report()
    test_dependent_task_is_skipped_when_the_earlier_step_failed()
    test_independent_tasks_still_run_in_parallel_without_injection()
    test_notes_after_a_substantial_report_saves_the_report_not_the_models_own_text()
    test_notes_keeps_the_users_own_short_content()
    test_prior_reports_from_the_tool_call_loop_seed_a_later_step()
    test_notes_is_skipped_after_a_failed_step()
    print("OK: all orchestrator dispatcher tests passed")
