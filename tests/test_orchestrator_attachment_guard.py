"""Có tệp đính kèm mà classifier chọn agent không dùng tệp → AttachmentIgnored (log 2026-09-28 07:34:
PDF + "lưu trữ dữ liệu" → notes lưu câu nói thành ghi chú, bỏ qua tệp). Run: python -m pytest tests/test_orchestrator_attachment_guard.py"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.orchestrator as orchestrator


def _run(monkeypatch, tasks, att, predetermined=None):
    ran = []

    async def fake_classify(*a, **k):
        return tasks

    async def fake_dispatch(t, **k):
        ran.append(t)
        return [{"agent": t[0]["agent"], "query": "q", "result": "OK", "outcome_id": 1, "status": "failed"}]
    monkeypatch.setattr(orchestrator, "classify_tasks", fake_classify)
    monkeypatch.setattr(orchestrator, "dispatch_tasks", fake_dispatch)
    res = asyncio.run(orchestrator.run_orchestrator("lưu trữ dữ liệu", [], ws=object(),
                                                    attachment_context=att, predetermined_tasks=predetermined))
    return res, ran


def test_attachment_with_non_file_agent_raises_before_running(monkeypatch):
    with pytest.raises(orchestrator.AttachmentIgnored):
        _run(monkeypatch, [{"agent": "notes", "query": "lưu trữ dữ liệu"}], att=object())


def test_attachment_with_file_agent_runs(monkeypatch):
    for agent in ("rag", "office", "image"):
        res, ran = _run(monkeypatch, [{"agent": agent, "query": "q"}], att=object())
        assert res == "OK" and ran, agent


def test_no_attachment_or_predetermined_is_untouched(monkeypatch):
    res, ran = _run(monkeypatch, [{"agent": "notes", "query": "q"}], att=None)
    assert res == "OK" and ran
    res, ran = _run(monkeypatch, [], att=object(), predetermined=[{"agent": "notes", "query": "q"}])
    assert res == "OK" and ran  # @notes do ngài gọi thẳng: không chặn


class _Att:
    def __init__(self, ext):
        self.extension = ext


def test_unsupported_attachment_does_not_block_the_request(monkeypatch):
    """.zip không agent nào đọc được: làm tiếp việc trong câu, bỏ qua tệp."""
    res, ran = _run(monkeypatch, [{"agent": "search", "query": "thời tiết"}], att=_Att(".zip"))
    assert res == "OK" and ran


def test_supported_attachment_ignored_still_raises(monkeypatch):
    with pytest.raises(orchestrator.AttachmentIgnored):
        _run(monkeypatch, [{"agent": "notes", "query": "q"}], att=_Att(".pdf"))
