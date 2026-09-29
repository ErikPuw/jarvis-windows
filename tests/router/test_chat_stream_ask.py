import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import chat_stream
from engine.router.types import TurnContext


class _WS:
    tts_disabled = True
    cancel_requested = False


class _Streamer:
    def __init__(self, ws): pass
    def start(self): return asyncio.get_event_loop().create_future()
    async def put(self, s): pass
    async def stop(self, clear_queue=False): pass


def _run_stream(monkeypatch, chunks):
    async def fake_stream():
        for c in chunks:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])

    async def fake_llm(*a, **k):
        return fake_stream()

    import engine.server.llm_server as llm_server
    import engine.server.voice_streamer as voice_streamer
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    monkeypatch.setattr(voice_streamer, "VoiceStreamer", _Streamer)
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    ws = _WS()
    out = asyncio.run(chat_stream.stream_chat([], "máy chậm", TurnContext(ws=ws, send_json=send)))
    shown = "".join(d["text"] for d in sent if d["type"] == "text_chunk")
    return ws, shown, out


def test_stream_hides_markers_and_sets_pending_ask(monkeypatch):
    chunks = ["Chrome ngốn RAM. <ask", "_user>Ngài có muốn tôi đóng Chrome không?</ask_user>"]
    ws, shown, out = _run_stream(monkeypatch, chunks)
    assert "ask_user" not in shown and "Ngài có muốn tôi đóng Chrome không?" in shown
    assert "ask_user" not in out
    assert ws.pending_ask_user == "Ngài có muốn tôi đóng Chrome không?"


def test_stream_truncated_mid_tag_leaks_no_partial_marker(monkeypatch):
    """Generation cắt ngay giữa thẻ ("<ask_us") không được lộ marker dở dang ra text_chunk/return."""
    chunks = ["Chrome ngốn RAM. <ask_us"]
    ws, shown, out = _run_stream(monkeypatch, chunks)
    assert "<ask" not in shown and "<ask" not in out
    assert ws.pending_ask_user == ""


def test_empty_response_sets_pending_ask_user_empty(monkeypatch):
    ws, shown, out = _run_stream(monkeypatch, [""])
    assert ws.pending_ask_user == ""


def test_stream_extracts_action_run_and_shows_intent_on_display(monkeypatch):
    """Thẻ không lộ ra; ý định và công cụ hiện dạng `…` (2026-09-27, user); lưu trữ (out) vẫn sạch."""
    chunks = ["Chrome ngốn RAM. <ask", "_user>Ngài có muốn tôi đóng Chrome không?</ask_user><action_", "run>close_app</action_run>"]
    ws, shown, out = _run_stream(monkeypatch, chunks)
    assert "action_run" not in shown and "ask_user" not in shown
    assert "`Ngài có muốn tôi đóng Chrome không?`" in shown and "(công cụ: `close_app`)" in shown
    assert ws.pending_ask_user == "Ngài có muốn tôi đóng Chrome không?"
    assert ws.pending_action_run == "close_app"
    assert "action_run" not in out and "close_app" not in out


def test_offer_is_logged_with_raw_tool_name(monkeypatch, caplog):
    """jarvis.log 2026-09-27: dòng 'JARVIS:' là bản sạch, không thấy thẻ → phải có dòng [OFFER] riêng (kể cả tool bịa)."""
    import logging
    caplog.set_level(logging.INFO, logger="jarvis.router.chat_stream")
    _run_stream(monkeypatch, ["Ok. Muốn tôi <ask_user>kiểm tra dự án</ask_user> không?<action_run>check_project_code</action_run>"])
    lines = [r.getMessage() for r in caplog.records if "[OFFER]" in r.getMessage()]
    assert lines == ["[OFFER] ask='kiểm tra dự án' action_run='check_project_code' valid=False"]
    caplog.clear()
    _run_stream(monkeypatch, ["Chào ngài."])
    assert not [r for r in caplog.records if "[OFFER]" in r.getMessage()]


def test_stream_action_run_empty_for_unknown_tool(monkeypatch):
    """Unknown tool name in <action_run> → pending_action_run = "" (extract_action filters)."""
    chunks = ["Query. <ask_user>Do query?</ask_user><action_run>get_news</action_run>"]
    ws, shown, out = _run_stream(monkeypatch, chunks)
    assert ws.pending_ask_user == "Do query?"
    assert ws.pending_action_run == ""  # get_news not in OFFERABLE_TOOLS


def test_stream_action_run_cleared_if_no_ask(monkeypatch):
    """No <ask_user> → pending_action_run = "" even if <action_run> present."""
    chunks = ["Just text. <action_run>open_app</action_run>"]
    ws, shown, out = _run_stream(monkeypatch, chunks)
    assert ws.pending_ask_user == ""
    assert ws.pending_action_run == ""
