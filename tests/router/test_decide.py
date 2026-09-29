import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import engine.router.decide  # đảm bảo submodule nằm trong sys.modules trước khi lấy ra
from engine.router.types import TurnContext

# engine/router/__init__.py rebind "decide" = hàm decide() ở package level (cho handle_turn
# monkeypatch được qua engine.router.decide) → lấy submodule thật trực tiếp từ sys.modules,
# vì mọi "import engine.router.decide as X" đều đi qua getattr(engine.router, "decide") đã bị shadow.
D = sys.modules["engine.router.decide"]


def _run(text, monkeypatch, bucket="orchestrator", replay=None, unlearn=True, attachment=None):
    calls = {"gate": 0}

    async def fake_gate(clean, ctx):
        calls["gate"] += 1
        return bucket

    async def fake_find(clean, att):
        return replay
    monkeypatch.setattr(D, "classify_bucket", fake_gate)
    monkeypatch.setattr(D, "find_replay", fake_find)
    monkeypatch.setattr(D, "_unlearn_last_route", lambda text: unlearn)
    ctx = TurnContext(ws=object(), send_json=None, attachment_context=attachment)
    return asyncio.run(D.decide(text, ctx)), calls["gate"]


def _with_pending(monkeypatch, ask, tool=""):
    import engine.core.memory as memory
    monkeypatch.setattr(memory, "get_pending_offer", lambda: (ask, tool))


def test_affirm_runs_the_offered_command(monkeypatch):
    _with_pending(monkeypatch, "Ngài có muốn tôi mở Notepad không?")
    d, n = _run("ừ", monkeypatch)
    assert (d.kind, d.query, d.source, n) == ("orchestrator", "mở Notepad", "ask_reply", 0)


def test_deny_is_general(monkeypatch):
    _with_pending(monkeypatch, "Ngài có muốn tôi mở Notepad không?")
    d, n = _run("thôi khỏi", monkeypatch)
    assert (d.kind, d.source, n) == ("general", "ask_reply", 0)


def test_other_reply_or_vague_ask_goes_to_gate(monkeypatch):
    _with_pending(monkeypatch, "Ngài có muốn tôi mở Notepad không?")
    assert _run("ừ nhưng mở word", monkeypatch)[0].source == "gate"
    _with_pending(monkeypatch, "Ngài muốn nghe bài nào hay album nào?")
    assert _run("ừ", monkeypatch)[0].source == "gate"


def test_bare_ok_without_pending_ask_reaches_gate(monkeypatch):  # thay test short-reply cũ (spec §4: bỏ fast-path)
    _with_pending(monkeypatch, "")
    d, n = _run("ok", monkeypatch, bucket="general")
    assert (d.kind, d.source, n) == ("general", "gate", 1)


def test_affirm_with_too_short_command_falls_through_to_gate(monkeypatch):
    # M1: ask_to_command(ask) may reduce to <2 words ("giúp", or "" for a question
    # with no concrete verb phrase) — that's not an actionable command, so let the
    # gate classify the reply normally instead of dispatching an empty/1-word task.
    _with_pending(monkeypatch, "Ngài có muốn tôi giúp không ạ?")
    d, n = _run("ừ", monkeypatch, bucket="general")
    assert (d.kind, d.source, n) == ("general", "gate", 1)
    _with_pending(monkeypatch, "Được không ạ?")
    d, n = _run("ừ", monkeypatch, bucket="general")
    assert (d.kind, d.source, n) == ("general", "gate", 1)


def test_attachment_disables_ask_reply(monkeypatch):
    _with_pending(monkeypatch, "Ngài có muốn tôi mở Notepad không?")
    assert _run("ừ", monkeypatch, attachment=object())[0].source == "gate"


def test_pending_ask_db_error_falls_through_to_gate(monkeypatch):
    import sqlite3
    import engine.core.memory as memory

    def boom():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memory, "get_pending_offer", boom)
    d, n = _run("ừ", monkeypatch, bucket="general")
    assert (d.kind, d.source, n) == ("general", "gate", 1)


def test_mention_beats_everything(monkeypatch):
    d, n = _run("@email xem thư", monkeypatch, replay={"id": 1, "agent": "desktop", "tool_chain": ["x"]})
    assert (d.kind, d.agent, d.query, d.source, n) == ("agent", "email", "xem thư", "mention", 0)


def test_unknown_mention_goes_on_without_the_mention(monkeypatch):
    d, _ = _run("@xyz mở notepad", monkeypatch)
    assert (d.kind, d.query, d.source) == ("orchestrator", "mở notepad", "gate")


def test_voice_control(monkeypatch):
    d, n = _run("thu nhỏ cửa sổ", monkeypatch)
    assert (d.kind, d.agent, d.source, n) == ("agent", "win_control", "voice", 0)


def test_complaint_unlearns_and_is_general(monkeypatch):
    d, n = _run("sao lại gọi agent vậy", monkeypatch)
    assert (d.kind, d.source, n) == ("general", "complaint", 0)
    d, n = _run("sao lại gọi agent vậy", monkeypatch, unlearn=False)
    assert d.source == "gate" and n == 1  # không có outcome gần → xuống gate như cũ


def test_replay_before_gate(monkeypatch):
    wf = {"id": 7, "agent": "desktop", "tool_chain": ["open_app"]}
    d, n = _run("mở steam", monkeypatch, replay=wf)
    assert (d.kind, d.workflow, d.agent, d.source, n) == ("replay", wf, "desktop", "replay", 0)


def test_gate_bucket_query_is_trimmed_text(monkeypatch):
    d, _ = _run("  Napoleon là ai ", monkeypatch, bucket="general_knowledge")
    assert (d.kind, d.query, d.source) == ("general_knowledge", "Napoleon là ai", "gate")
