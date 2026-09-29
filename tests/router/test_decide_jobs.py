"""Router: @jobs, phiên phỏng vấn, lệnh duyệt (spec 2026-09-27 mục 5)."""
import asyncio
import sys
import time

import engine.router.decide  # noqa: F401
from engine.jobs import store
from engine.router.types import RouteDecision, TurnContext

D = sys.modules["engine.router.decide"]


def _decide(text, monkeypatch, attachment=None):
    async def fake_gate(clean, ctx):
        return "general"

    async def fake_find(clean, att):
        return None
    monkeypatch.setattr(D, "classify_bucket", fake_gate)
    monkeypatch.setattr(D, "find_replay", fake_find)
    monkeypatch.setattr(D, "_unlearn_last_route", lambda text: False)
    ctx = TurnContext(ws=object(), send_json=None, attachment_context=attachment)
    return asyncio.run(D.decide(text, ctx))


def test_jobs_mention(monkeypatch):
    d = _decide("@jobs tìm", monkeypatch)
    assert (d.kind, d.query, d.source) == ("jobs", "tìm", "mention")
    assert _decide("@jobs", monkeypatch).query == ""


def test_active_interview_takes_plain_text_but_not_mentions(monkeypatch):
    store.save("interview.json", {"status": "active", "index": 3, "answers": {}, "updated_at": time.time()})
    d = _decide("3 năm bán hàng", monkeypatch)
    assert (d.kind, d.query, d.source) == ("jobs", "3 năm bán hàng", "session")
    assert _decide("@email xem thư", monkeypatch).kind != "jobs"


def test_idle_or_paused_interview_does_not_capture(monkeypatch):
    store.save("interview.json", {"status": "active", "index": 3, "answers": {}, "updated_at": time.time() - 3600})
    assert _decide("mở nhạc", monkeypatch).kind == "general"
    store.save("interview.json", {"status": "paused", "index": 3, "answers": {}, "updated_at": time.time()})
    assert _decide("mở nhạc", monkeypatch).kind == "general"


def test_review_command_only_with_open_pending(monkeypatch):
    assert _decide("gửi 1, 3", monkeypatch).kind == "general"
    store.save("pending.json", {"created_at": time.time(), "items": [{"n": 1}]})
    d = _decide("gửi 1, 3", monkeypatch)
    assert (d.kind, d.source) == ("jobs", "review")
    assert _decide("gửi mail cho sếp", monkeypatch).kind == "general"


def test_attachment_skips_session(monkeypatch):
    store.save("interview.json", {"status": "active", "index": 3, "answers": {}, "updated_at": time.time()})
    assert _decide("đây là file", monkeypatch, attachment=object()).kind != "jobs"


def test_dispatch_sends_jobs_to_runner(monkeypatch):
    import engine.jobs.runner as runner
    from engine.router import dispatch as DP
    seen = {}

    async def fake_handle(d, ctx):
        seen["d"] = d
        return "ok"
    monkeypatch.setattr(runner, "handle", fake_handle)

    async def send(ws, data):
        return True
    from types import SimpleNamespace
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send)  # dispatch() setattr lên ws
    d = RouteDecision("jobs", "tìm", "mention")
    assert asyncio.run(DP.dispatch(d, "@jobs tìm", ctx)) == "ok" and seen["d"] is d
