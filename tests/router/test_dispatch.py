import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import dispatch as DP
from engine.router.types import RouteDecision, TurnContext


class _WS:
    pass


def _ctx(att=None):
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    return TurnContext(ws=_WS(), send_json=send, attachment_context=att), sent


def _patch(monkeypatch, orch_result="AGENT", replay_result="REPLAY"):
    calls = {}

    async def fake_orch(**kw):
        calls["orch"] = kw
        return orch_result

    async def fake_chat(kind, text, ctx):
        calls["chat"] = kind
        return f"CHAT:{kind}"

    async def fake_replay(d, ctx):
        return replay_result
    monkeypatch.setattr(DP, "_run_orchestrator", fake_orch)
    monkeypatch.setattr(DP, "_chat", fake_chat)
    monkeypatch.setattr(DP, "run_replay", fake_replay)
    return calls


def test_general_and_knowledge_go_to_chat(monkeypatch):
    calls = _patch(monkeypatch)
    ctx, _ = _ctx()
    assert asyncio.run(DP.dispatch(RouteDecision("general_knowledge", "q", "gate"), "q", ctx)) == "CHAT:general_knowledge"


def test_orchestrator_without_agent_falls_back_to_general_chat(monkeypatch):
    calls = _patch(monkeypatch, orch_result="")
    ctx, sent = _ctx()
    assert asyncio.run(DP.dispatch(RouteDecision("orchestrator", "q", "gate"), "q", ctx)) == "CHAT:general"
    assert calls["orch"]["predetermined_tasks"] is None and {"type": "status", "state": "working"} in sent


def test_agent_runs_predetermined_task(monkeypatch):
    calls = _patch(monkeypatch)
    ctx, _ = _ctx()
    assert asyncio.run(DP.dispatch(RouteDecision("agent", "xem thư", "mention", agent="email"), "@email xem thư", ctx)) == "AGENT"
    assert calls["orch"]["predetermined_tasks"] == [{"agent": "email", "query": "xem thư"}]


def test_rag_without_attachment_is_refused(monkeypatch):
    calls = _patch(monkeypatch)
    ctx, sent = _ctx()
    out = asyncio.run(DP.dispatch(RouteDecision("agent", "x", "mention", agent="rag"), "@rag x", ctx))
    assert "tệp đính kèm" in out and "orch" not in calls and sent[-1] == {"type": "stream_end"}


def test_empty_replay_falls_back_to_chat(monkeypatch):
    _patch(monkeypatch, replay_result="")
    ctx, _ = _ctx()
    d = RouteDecision("replay", "mở steam", "replay", agent="desktop", workflow={"id": 1, "agent": "desktop", "tool_chain": ["open_app"]})
    assert asyncio.run(DP.dispatch(d, "mở steam", ctx)) == "CHAT:general"


def test_handle_turn_survives_decide_crash(monkeypatch):
    import engine.router as R
    _patch(monkeypatch)

    async def boom(text, ctx):
        raise RuntimeError("x")
    monkeypatch.setattr(R, "decide", boom)
    ctx, _ = _ctx()
    assert asyncio.run(R.handle_turn("chào", ctx)) == "CHAT:general"


def test_handle_turn_falls_back_to_chat_when_orchestrator_raises(monkeypatch):
    # I3: old server.generate_response_stream also caught exceptions from executing
    # the route and fell back to normal chat; decide() catching its own crash is not
    # enough if the route itself (orchestrator/agent/replay) then blows up.
    import engine.router as R
    from engine.router.types import RouteDecision
    _patch(monkeypatch)

    async def orch_boom(**kw):
        raise RuntimeError("orchestrator down")
    monkeypatch.setattr(DP, "_run_orchestrator", orch_boom)

    async def fake_decide(text, ctx):
        return RouteDecision("orchestrator", text, "gate")
    monkeypatch.setattr(R, "decide", fake_decide)
    ctx, _ = _ctx()
    assert asyncio.run(R.handle_turn("mở word", ctx)) == "CHAT:general"


class TestOfferContext:
    """Task 17: orchestrator receives offer_context when pending offer exists."""

    def test_dispatch_gate_orchestrator_with_valid_offer_passes_offer_context(self, monkeypatch):
        """Test (a): dispatch(orchestrator, gate) + valid offer → _run_orchestrator gets offer_context with question + tool."""
        calls = _patch(monkeypatch)
        import engine.core.memory as memory
        monkeypatch.setattr(memory, "get_pending_offer", lambda: ("Ngài có muốn tôi mở Notepad không?", "open_app"))

        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("orchestrator", "ừ nhưng mở word", "gate"), "ừ nhưng mở word", ctx))

        assert "offer_context" in calls["orch"], "offer_context not passed to _run_orchestrator"
        offer_ctx = calls["orch"]["offer_context"]
        assert "Ngài có muốn tôi mở Notepad không?" in offer_ctx, f"Question not in offer_context: {offer_ctx}"
        assert "[công cụ: open_app]" in offer_ctx, f"Tool hint not in offer_context: {offer_ctx}"

    def test_dispatch_gate_orchestrator_with_empty_offer_passes_empty_offer_context(self, monkeypatch):
        """Test (b): dispatch(orchestrator, gate) + empty offer → offer_context == ""."""
        calls = _patch(monkeypatch)
        import engine.core.memory as memory
        monkeypatch.setattr(memory, "get_pending_offer", lambda: ("", ""))

        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("orchestrator", "mở word", "gate"), "mở word", ctx))

        assert calls["orch"]["offer_context"] == "", f"Expected empty offer_context, got: {calls['orch']['offer_context']}"

    def test_dispatch_ask_reply_orchestrator_no_offer_context(self, monkeypatch):
        """Test (c): dispatch(orchestrator, ask_reply) does NOT call get_pending_offer; offer_context == ""."""
        calls = _patch(monkeypatch)
        get_offer_calls = []

        import engine.core.memory as memory
        def track_get_offer():
            get_offer_calls.append(True)
            return ("x", "y")
        monkeypatch.setattr(memory, "get_pending_offer", track_get_offer)

        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("orchestrator", "mở notepad", "ask_reply"), "mở notepad", ctx))

        assert len(get_offer_calls) == 0, f"get_pending_offer should not be called for ask_reply source, but was called {len(get_offer_calls)} times"
        assert calls["orch"]["offer_context"] == "", f"Expected empty offer_context for ask_reply, got: {calls['orch']['offer_context']}"

    def test_dispatch_gate_orchestrator_with_db_error_passes_empty_offer_context(self, monkeypatch):
        """Test (d): dispatch(orchestrator, gate) with get_pending_offer raising → offers empty offer_context."""
        calls = _patch(monkeypatch)
        import engine.core.memory as memory
        import sqlite3

        def boom():
            raise sqlite3.OperationalError("database is locked")
        monkeypatch.setattr(memory, "get_pending_offer", boom)

        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("orchestrator", "mở word", "gate"), "mở word", ctx))

        assert calls["orch"]["offer_context"] == "", f"Expected empty offer_context on DB error, got: {calls['orch']['offer_context']}"

    def test_run_orchestrator_receives_offer_context_in_extra_context(self, monkeypatch):
        """Task 19: run_orchestrator(offer_context="X") → classify_tasks gets offer_context=="X"."""
        import engine.orchestrator as ORCH
        calls = {}

        async def fake_classify(user_text, **kw):
            calls["classify"] = kw
            return []

        monkeypatch.setattr(ORCH, "classify_tasks", fake_classify)

        ctx, _ = _ctx()
        asyncio.run(ORCH.run_orchestrator(
            user_text="test",
            conversation_history=[],
            ws=_WS(),
            offer_context="OFFER_CONTEXT_TEXT"
        ))

        assert "classify" in calls, "classify_tasks not called"
        assert calls["classify"].get("offer_context") == "OFFER_CONTEXT_TEXT", \
            f"classify_tasks did not get expected offer_context, got: {calls['classify']}"
        assert calls["classify"].get("extra_context", "") == "", \
            f"classify_tasks should get empty extra_context in round 1, got: {calls['classify']}"


class TestActionDeclined:
    """Task 18: when an action path falls back to chat, set ctx.action_declined=True."""

    def test_orchestrator_empty_sets_action_declined(self, monkeypatch):
        """Orchestrator returns "" → ctx.action_declined=True when _chat is called."""
        _patch(monkeypatch, orch_result="")
        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("orchestrator", "mở word", "gate"), "mở word", ctx))
        assert ctx.action_declined is True, "action_declined should be True after orchestrator fallback"

    def test_replay_empty_sets_action_declined(self, monkeypatch):
        """Replay returns "" → ctx.action_declined=True when _chat is called."""
        _patch(monkeypatch, replay_result="")
        ctx, _ = _ctx()
        d = RouteDecision("replay", "mở steam", "replay", agent="desktop", workflow={"id": 1, "agent": "desktop", "tool_chain": ["open_app"]})
        asyncio.run(DP.dispatch(d, "mở steam", ctx))
        assert ctx.action_declined is True, "action_declined should be True after replay fallback"

    def test_general_kind_does_not_set_action_declined(self, monkeypatch):
        """General/general_knowledge calls _chat directly → action_declined stays False."""
        _patch(monkeypatch)
        ctx, _ = _ctx()
        asyncio.run(DP.dispatch(RouteDecision("general", "hello", "gate"), "hello", ctx))
        assert ctx.action_declined is False, "action_declined should stay False for general kind"

    def test_handle_turn_non_chat_exception_sets_action_declined(self, monkeypatch):
        """handle_turn: dispatch(orchestrator) raises → fallback _chat with action_declined=True."""
        import engine.router as R
        _patch(monkeypatch)

        async def orch_boom(**kw):
            raise RuntimeError("orch down")
        monkeypatch.setattr(DP, "_run_orchestrator", orch_boom)

        async def fake_decide(text, ctx):
            return RouteDecision("orchestrator", text, "gate")
        monkeypatch.setattr(R, "decide", fake_decide)

        ctx, _ = _ctx()
        asyncio.run(R.handle_turn("mở word", ctx))
        assert ctx.action_declined is True, "action_declined should be True on non-chat exception fallback"


class TestAttachmentIgnored:
    """Log 2026-09-28 07:34: PDF + "lưu trữ dữ liệu" → classifier chọn notes, tệp bị bỏ qua."""

    def _setup(self, monkeypatch, selected):
        from engine.orchestrator import AttachmentIgnored
        calls = []

        async def fake_orch(**kw):
            calls.append(kw)
            if kw.get("predetermined_tasks") is None:
                raise AttachmentIgnored()
            return "RAG OK"

        async def fake_clarify(ctx):
            return selected
        monkeypatch.setattr(DP, "_run_orchestrator", fake_orch)
        monkeypatch.setattr(DP, "_clarify_attachment", fake_clarify)
        return calls

    def test_ignored_attachment_asks_then_runs_chosen_agent(self, monkeypatch):
        calls = self._setup(monkeypatch, "rag")
        ctx, _ = _ctx(att=object())
        res = asyncio.run(DP.dispatch(RouteDecision("orchestrator", "lưu trữ dữ liệu", "gate"), "lưu trữ dữ liệu", ctx))
        assert res == "RAG OK"
        assert calls[-1]["predetermined_tasks"] == [{"agent": "rag", "query": "lưu trữ dữ liệu"}]

    def test_ignored_attachment_cancel_does_not_run_anything(self, monkeypatch):
        calls = self._setup(monkeypatch, None)
        ctx, _ = _ctx(att=object())
        res = asyncio.run(DP.dispatch(RouteDecision("orchestrator", "lưu trữ dữ liệu", "gate"), "lưu trữ dữ liệu", ctx))
        assert res == "Đã hủy xử lý tệp vì chưa có lựa chọn phù hợp." and len(calls) == 1


class _Att:
    def __init__(self, ext):
        self.extension, self.filename = ext, "tep" + ext


class TestAttachmentOptions:
    """Bảng chọn tệp chỉ đưa agent thật sự đọc được định dạng đó (2026-09-28)."""

    def _options(self, monkeypatch, ext):
        import engine.main.ask_verifi as AV
        seen = {}

        async def fake_select(ws, send, action, message, options, **k):
            seen["options"] = [o["id"] for o in options]
            return None
        monkeypatch.setattr(AV, "ask_user_selection", fake_select)
        ctx, sent = _ctx(att=_Att(ext))
        res = asyncio.run(DP.dispatch(RouteDecision("attachment_clarify", "xử lý tệp", "gate"), "xử lý tệp", ctx))
        return seen.get("options"), res, sent

    def test_supported_formats_keep_their_choices(self, monkeypatch):
        assert self._options(monkeypatch, ".pdf")[0] == ["rag", "cancel"]
        assert self._options(monkeypatch, ".docx")[0] == ["rag", "office"]
        assert self._options(monkeypatch, ".png")[0] == ["image", "cancel"]

    def test_tif_is_not_offered_to_upscayl(self, monkeypatch):
        options, res, _ = self._options(monkeypatch, ".tif")
        assert options is None and ".tif" in res  # image_engine không nhận tif

    def test_unsupported_format_says_so_without_useless_card(self, monkeypatch):
        options, res, sent = self._options(monkeypatch, ".zip")
        assert options is None and ".zip" in res
        assert any(".zip" in (m.get("text") or "") for m in sent)
