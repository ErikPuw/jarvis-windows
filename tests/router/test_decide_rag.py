"""Router: @rag là lệnh tường minh, bắt bằng regex trước resolve_mention (không LLM)."""
import asyncio
import sys
from types import SimpleNamespace

import engine.router.decide  # noqa: F401
from engine.router.fast_paths import rag_mention
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


def test_rag_mention_parses_command():
    assert rag_mention("@rag hợp đồng thuê nhà hết hạn khi nào") == "hợp đồng thuê nhà hết hạn khi nào"
    assert rag_mention("@RAG: danh sách") == "danh sách"
    assert rag_mention("@rag") == ""
    assert rag_mention("@ragged x") is None
    assert rag_mention("tìm trong @rag x") is None
    assert rag_mention("@search thời tiết") is None


def test_rag_mention_routes_to_rag_kind_not_attachment_agent(monkeypatch):
    d = _decide("@rag điều khoản phạt", monkeypatch)
    assert (d.kind, d.query, d.source) == ("rag", "điều khoản phạt", "mention")
    assert _decide("@rag", monkeypatch).kind == "rag"


def test_plain_chat_and_other_mentions_unaffected(monkeypatch):
    assert _decide("rag là gì", monkeypatch).kind == "general"
    assert _decide("@jobs tìm", monkeypatch).kind == "jobs"


def test_dispatch_sends_rag_to_runner(monkeypatch):
    import engine.rag.runner as runner
    from engine.router import dispatch as DP
    seen = {}

    async def fake_handle(d, ctx):
        seen["d"] = d
        return "ok"
    monkeypatch.setattr(runner, "handle", fake_handle)

    async def send(ws, data):
        return True
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send)
    d = RouteDecision("rag", "danh sách", "mention")
    assert asyncio.run(DP.dispatch(d, "@rag danh sách", ctx)) == "ok" and seen["d"] is d
