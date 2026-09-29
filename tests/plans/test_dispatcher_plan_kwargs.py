"""dispatch_tasks: runner_kwargs theo từng task + step_timeout (spec 2026-09-26 mục 6)."""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.orchestrator import dispatcher, registry

_OLD_KWARGS = {"user_text", "conversation_history", "ws", "flow_tracker", "flow_agents", "attachment_context", "silent"}


def _run(tasks, **kw):
    return asyncio.run(dispatcher.dispatch_tasks(tasks, user_text="g", conversation_history=[], ws=SimpleNamespace(), **kw))


def test_runner_kwargs_reach_the_runner(monkeypatch):
    seen = []

    async def runner(**kw):
        seen.append(kw)
        return "R"
    monkeypatch.setattr(registry, "resolve_runner", lambda name: runner)
    monkeypatch.setattr(dispatcher, "record_outcome", lambda *a, **k: (7, "success"))
    out = _run([{"agent": "search", "query": "q", "runner_kwargs": {"tools": ["web_research"]}}])
    assert seen[0]["tools"] == ["web_research"]
    assert out == [{"agent": "search", "query": "q", "result": "R", "outcome_id": 7, "status": "success"}]


def test_without_runner_kwargs_the_runner_gets_exactly_the_old_kwargs(monkeypatch):
    seen = []

    async def runner(**kw):
        seen.append(kw)
        return "R"
    monkeypatch.setattr(registry, "resolve_runner", lambda name: runner)
    monkeypatch.setattr(dispatcher, "record_outcome", lambda *a, **k: (7, "success"))
    _run([{"agent": "search", "query": "q"}])
    assert set(seen[0]) == _OLD_KWARGS


def test_step_timeout_marks_the_step_failed_without_recording(monkeypatch):
    recorded = []

    async def slow(**kw):
        await asyncio.sleep(1)
        return "late"
    monkeypatch.setattr(registry, "resolve_runner", lambda name: slow)
    monkeypatch.setattr(dispatcher, "record_outcome", lambda *a, **k: recorded.append(a) or (1, "success"))
    out = _run([{"agent": "search", "query": "q"}], step_timeout=0.05)
    assert out == [{"agent": "search", "query": "q", "result": "Quá thời gian thực hiện bước này.",
                    "outcome_id": None, "status": "failed"}]
    assert recorded == []
