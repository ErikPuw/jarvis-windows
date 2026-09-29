# tests/router/test_gate.py
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import gate
from engine.router.types import TurnContext
from engine.server import llm_server


def _resp(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _classify(text, reply, attachment=None, monkeypatch=None):
    seen = {}

    async def fake_inner(messages, *a, **k):
        seen["system"], seen["user"] = messages[0]["content"], messages[1]["content"]
        return _resp(reply)
    monkeypatch.setattr(llm_server, "_call_llm_inner", fake_inner)
    monkeypatch.setattr(gate, "_routing_history", lambda text, fallback: [])
    monkeypatch.setattr(gate, "_corrections", lambda: [])
    monkeypatch.setattr(gate, "_read_pref_context", lambda: "")
    ctx = TurnContext(ws=object(), send_json=None, attachment_context=attachment)
    return asyncio.run(gate.classify_bucket(text, ctx)), seen


def test_returns_only_known_buckets(monkeypatch):
    assert _classify("mo word", "orchestrator", monkeypatch=monkeypatch)[0] == "orchestrator"
    assert _classify("mo word", "desktop", monkeypatch=monkeypatch)[0] == "general"  # tên agent cũ = nhãn lạ


def test_decorated_or_think_wrapped_bucket_is_understood(monkeypatch):
    assert _classify("x", "<think>hm</think>Bucket: orchestrator.", monkeypatch=monkeypatch)[0] == "orchestrator"
    assert _classify("x", "`general_knowledge`", monkeypatch=monkeypatch)[0] == "general_knowledge"


def test_attachment_bucket_only_with_attachment(monkeypatch):
    assert _classify("x", "attachment_clarify", monkeypatch=monkeypatch)[0] == "general"
    att = SimpleNamespace(router_metadata=lambda: {"filename": "a.docx"})
    got, seen = _classify("x", "attachment_clarify", attachment=att, monkeypatch=monkeypatch)
    assert got == "attachment_clarify" and "attachment_clarify" in seen["system"]


def test_history_shows_the_pending_question_untruncated():
    # Production shape (build_unified_routing_history, spec §6): history always ends
    # with the CURRENT user utterance, not the assistant's question.
    long = "Chrome đang ngốn rất nhiều RAM vì có quá nhiều tab và tiện ích chạy nền cùng lúc. Ngài có muốn tôi đóng Chrome không?"
    ctx = gate._history_context(
        [
            {"role": "user", "content": "máy chậm"},
            {"role": "assistant", "content": long},
            {"role": "user", "content": "ừ"},
        ],
        pending_ask="Ngài có muốn tôi đóng Chrome không?",
    )
    assert "Ngài có muốn tôi đóng Chrome không?" in ctx


def test_llm_error_falls_back_to_general(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("server down")
    monkeypatch.setattr(llm_server, "_call_llm_inner", boom)
    monkeypatch.setattr(gate, "_routing_history", lambda text, fallback: [])
    monkeypatch.setattr(gate, "_corrections", lambda: [])
    monkeypatch.setattr(gate, "_read_pref_context", lambda: "")
    assert asyncio.run(gate.classify_bucket("x", TurnContext(ws=object(), send_json=None))) == "general"
