"""Test Task 17: "ừ" chạy thẳng tool đề nghị; orchestrator thấy lời đề nghị."""
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router.types import TurnContext

D = sys.modules.get("engine.router.decide")
if not D:
    import engine.router.decide
    D = sys.modules["engine.router.decide"]


def _run(text, monkeypatch, bucket="orchestrator", replay=None, attachment=None, offer=None):
    """Helper: run decide() with patched gate, find_replay, get_pending_offer."""
    calls = {"gate": 0}

    async def fake_gate(clean, ctx):
        calls["gate"] += 1
        return bucket

    async def fake_find(clean, att):
        return replay

    monkeypatch.setattr(D, "classify_bucket", fake_gate)
    monkeypatch.setattr(D, "find_replay", fake_find)
    monkeypatch.setattr(D, "_unlearn_last_route", lambda text: True)

    # Patch get_pending_offer nếu có offer
    if offer is not None:
        import engine.core.memory as memory
        monkeypatch.setattr(memory, "get_pending_offer", lambda: offer)

    ctx = TurnContext(ws=object(), send_json=None, attachment_context=attachment)
    return asyncio.run(D.decide(text, ctx)), calls["gate"]


class TestOfferReplay:
    """Test khi user đồng ý với lời đề nghị có tool hợp lệ."""

    def test_affirm_with_valid_tool_runs_replay(self, monkeypatch):
        """offer (ask, "open_app") + "ừ mở đi" → replay decision, no gate call."""
        offer = ("Ngài có muốn tôi mở Notepad không?", "open_app")
        d, gate_calls = _run("ừ mở đi", monkeypatch, offer=offer)

        assert d.kind == "replay", f"Expected replay, got {d.kind}"
        assert d.source == "ask_reply", f"Expected source ask_reply, got {d.source}"
        assert d.query == "mở Notepad", f"Expected query 'mở Notepad', got {d.query}"
        assert d.agent == "desktop", f"Expected agent desktop, got {d.agent}"
        assert d.workflow == {"id": "offer", "agent": "desktop", "tool_chain": ["open_app"]}, \
            f"Unexpected workflow: {d.workflow}"
        assert gate_calls == 0, f"Gate should not be called, but was called {gate_calls} times"

    def test_translated_app_name_uses_original_name_in_parentheses(self, monkeypatch):
        """Log 2026-09-25: 'Ghi chú (Notepad)' → app_name 'ghi chú (notepad)' bị Windows từ chối."""
        for ask, tool, want in [
            ("Ngài có muốn tôi mở ứng dụng Ghi chú (Notepad) không ạ?", "open_app", "mở Notepad"),
            ("Ngài có muốn tôi đóng Máy tính (Calculator) không?", "close_app", "đóng Calculator"),
            ("Ngài có muốn tôi mở Visual Studio Code không?", "open_app", "mở Visual Studio Code"),
            ("Ngài có muốn tôi tra thời tiết (Hà Nội) không?", "weather_search", "tra thời tiết (Hà Nội)"),
        ]:
            d, _ = _run("ừ mở đi", monkeypatch, offer=(ask, tool))
            assert (d.kind, d.query) == ("replay", want), (ask, d.query)

    def test_affirm_with_empty_tool_goes_to_orchestrator(self, monkeypatch):
        """offer (ask, "") + "ừ" → orchestrator, no gate call."""
        offer = ("Ngài có muốn tôi giúp gì không?", "")
        d, gate_calls = _run("ừ", monkeypatch, offer=offer)

        assert d.kind == "orchestrator", f"Expected orchestrator, got {d.kind}"
        assert d.source == "ask_reply", f"Expected source ask_reply, got {d.source}"
        assert gate_calls == 0, f"Gate should not be called, but was called {gate_calls} times"

    def test_deny_with_offer_stays_general(self, monkeypatch):
        """offer + "thôi khỏi" → general, no gate call (existing behavior)."""
        offer = ("Ngài có muốn tôi mở Notepad không?", "open_app")
        d, gate_calls = _run("thôi khỏi", monkeypatch, offer=offer)

        assert d.kind == "general", f"Expected general, got {d.kind}"
        assert d.source == "ask_reply", f"Expected source ask_reply, got {d.source}"
        assert gate_calls == 0, f"Gate should not be called, but was called {gate_calls} times"

    def test_complex_reply_with_offer_goes_to_gate(self, monkeypatch):
        """offer + "ừ nhưng mở word" → gate, because reply modifies the offer."""
        offer = ("Ngài có muốn tôi mở Notepad không?", "open_app")
        d, gate_calls = _run("ừ nhưng mở word", monkeypatch, offer=offer)

        assert d.source == "gate", f"Expected source gate, got {d.source}"
        assert gate_calls == 1, f"Gate should be called once, but was called {gate_calls} times"

    def test_affirm_with_unknown_tool_goes_to_orchestrator(self, monkeypatch):
        """offer with unknown tool + "ừ" → orchestrator, because tool not in OFFERABLE_TOOLS."""
        offer = ("Ngài có muốn tôi làm gì không?", "unknown_tool")
        d, gate_calls = _run("ừ", monkeypatch, offer=offer)

        assert d.kind == "orchestrator", f"Expected orchestrator, got {d.kind}"
        assert d.source == "ask_reply", f"Expected source ask_reply, got {d.source}"
        assert gate_calls == 0, f"Gate should not be called, but was called {gate_calls} times"

    def test_no_offer_behaves_normally(self, monkeypatch):
        """Without offer, "ừ" → gate (normal behavior)."""
        offer = ("", "")  # No pending offer
        d, gate_calls = _run("ừ", monkeypatch, bucket="general", offer=offer)

        # When no actionable offer, should go to gate
        assert gate_calls == 1 or d.source == "gate", f"Expected gate path"
