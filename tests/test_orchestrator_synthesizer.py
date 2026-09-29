"""Tests for engine.orchestrator.synthesizer. Run: python tests/test_orchestrator_synthesizer.py"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import synthesizer


def _fake_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def test_combine_returns_single_result_without_llm_call():
    async def scenario():
        results = [{"agent": "search", "query": "gia vang", "result": "Vang dang 80 trieu"}]
        return await synthesizer.combine("gia vang bao nhieu", results)
    text, needs_more = asyncio.run(scenario())
    assert text == "Vang dang 80 trieu", text
    assert needs_more is False


def test_combine_merges_multiple_results_via_llm():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            assert stream is False, "combine() must never stream"
            return _fake_response("### Email\nCo 3 email moi.\n\n### Notes\nDa ghi chu xong.")

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            results = [
                {"agent": "email", "query": "xem thu", "result": "3 email moi"},
                {"agent": "notes", "query": "ghi lai", "result": "da luu note"},
            ]
            return await synthesizer.combine("kiem tra mail roi ghi note", results)
        finally:
            llm_server._call_llm_inner = original

    text, needs_more = asyncio.run(scenario())
    assert "Email" in text and "Notes" in text, text
    assert needs_more is False


def test_combine_detects_needs_more_marker():
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response("Da tim thay 1 phan thong tin.\n[NEEDS_MORE]")

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            results = [
                {"agent": "search", "query": "x", "result": "a"},
                {"agent": "history", "query": "y", "result": "b"},
            ]
            return await synthesizer.combine("nghien cuu sau ve x", results)
        finally:
            llm_server._call_llm_inner = original

    text, needs_more = asyncio.run(scenario())
    assert needs_more is True
    assert "[NEEDS_MORE]" not in text, text


class _FakeVoiceStreamer:
    """Stand-in for engine.server.voice_streamer.VoiceStreamer that never
    touches the network (no real Edge-TTS call)."""

    def __init__(self, ws, disable_tts=False, **kwargs):
        self.ws = ws

    def start(self):
        return None

    async def put(self, sentence):
        pass

    async def stop(self, clear_queue=False):
        pass


def test_deliver_streams_and_sends_stream_end():
    async def scenario():
        recorded = []

        class FakeWs:
            pass

        async def fake_safe_send(_ws, payload):
            recorded.append(payload)
            return True

        import server as server_module
        original = server_module.safe_ws_send_json
        server_module.safe_ws_send_json = fake_safe_send

        import engine.server.voice_streamer as voice_streamer_module
        original_voice_streamer = voice_streamer_module.VoiceStreamer
        voice_streamer_module.VoiceStreamer = _FakeVoiceStreamer
        try:
            result = await synthesizer.deliver(FakeWs(), "Xin chao thua ngai.")
        finally:
            server_module.safe_ws_send_json = original
            voice_streamer_module.VoiceStreamer = original_voice_streamer
        return result, recorded

    result, recorded = asyncio.run(scenario())
    assert result == "Xin chao thua ngai."
    assert any(p.get("type") == "stream_end" for p in recorded), recorded


def test_combine_strips_stray_needs_more_marker_not_trailing():
    """Regression: if the LLM emits [NEEDS_MORE] mid-text or followed by
    other content (not the exact trailing token), the raw marker must never
    leak into the returned text, regardless of what needs_more ends up being."""
    async def scenario():
        from engine.server import llm_server

        async def fake_inner(messages, model=None, thinking=False, stream=False,
                              tools=None, tool_choice=None, temperature=None,
                              max_tokens=None, response_format=None):
            return _fake_response(
                "Da tim thay mot phan. [NEEDS_MORE] Con thieu du lieu ve gia."
            )

        original = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            results = [
                {"agent": "search", "query": "x", "result": "a"},
                {"agent": "history", "query": "y", "result": "b"},
            ]
            return await synthesizer.combine("nghien cuu sau ve x", results)
        finally:
            llm_server._call_llm_inner = original

    text, needs_more = asyncio.run(scenario())
    assert "[NEEDS_MORE]" not in text, text


def test_agent_table_missing_from_answer_is_restored_verbatim():
    table = "| Loại | Mua | Bán |\n|---|---|---|\n| Vàng SJC | 144 | 147 |"
    results = [{"agent": "search", "query": "giá", "result": "Bảng giá:\n" + table},
               {"agent": "notes", "query": "ghi", "result": "Đã lưu note."}]
    out = synthesizer._restore_tables("Vàng SJC khoảng 144-147 triệu.", results)
    assert table in out, out
    already = synthesizer._restore_tables("Đây:\n" + table + "\nXong.", results)
    assert already.count("| Vàng SJC | 144 | 147 |") == 1, already
    assert synthesizer._restore_tables("ok", [{"result": "không có bảng | ở giữa"}]) == "ok"


def test_digest_dedupes_caps_keeps_tables_and_flags_failures():
    table = "| A | B |\n|---|---|\n| 1 | 2 |"
    long_prose = "\n".join(f"dòng {i}" for i in range(2000))
    results = [
        {"agent": "search", "query": "giá", "status": "success", "result": "Xin chào ngài\n" + long_prose + "\n" + table},
        {"agent": "email", "query": "thư", "status": "failed", "result": "Xin chào ngài\nKhông mở được Outlook"},
    ]
    d = synthesizer._digest(results)
    assert table in d, "table must survive verbatim"
    assert d.count("Xin chào ngài") == 1, "same line from two agents is reported once"
    assert "…(đã rút gọn)" in d and len(d) < synthesizer._REPORT_CHARS + 600, len(d)
    assert "agent email (yêu cầu con: thư) — THẤT BẠI" in d and "agent search (yêu cầu con: giá):" in d


def test_combine_sends_the_digest_to_the_llm():
    async def scenario():
        from engine.server import llm_server
        seen = {}

        async def fake_inner(messages, *a, **k):
            seen["user"] = messages[1]["content"]
            return _fake_response("ok")

        orig = llm_server._call_llm_inner
        llm_server._call_llm_inner = fake_inner
        try:
            await synthesizer.combine("q", [
                {"agent": "a", "query": "x", "status": "failed", "result": "Lỗi thực thi agent a"},
                {"agent": "b", "query": "y", "status": "success", "result": "xong"},
            ])
        finally:
            llm_server._call_llm_inner = orig
        return seen["user"]

    assert "agent a (yêu cầu con: x) — THẤT BẠI" in asyncio.run(scenario())


if __name__ == "__main__":
    test_combine_returns_single_result_without_llm_call()
    test_combine_merges_multiple_results_via_llm()
    test_combine_detects_needs_more_marker()
    test_deliver_streams_and_sends_stream_end()
    test_combine_strips_stray_needs_more_marker_not_trailing()
    test_agent_table_missing_from_answer_is_restored_verbatim()
    test_digest_dedupes_caps_keeps_tables_and_flags_failures()
    test_combine_sends_the_digest_to_the_llm()
    print("OK: all orchestrator synthesizer tests passed")
