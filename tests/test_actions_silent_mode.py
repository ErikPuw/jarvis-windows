"""Tests for the `silent` mode of handle_user_intent_with_tools. Run:
python tests/test_actions_silent_mode.py"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import actions


class FakeWs:
    def __init__(self):
        self.sent = []


async def _fake_execute_tool_direct(tool_name, args, ws, **kwargs):
    return {"text": f"ket qua {tool_name}"}


async def _fake_execute_tool_internal(tool_name, args, ws, **kwargs):
    return "noi dung man hinh"


def _fake_llm_response(content: str):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


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


def test_silent_direct_tool_skips_ws_and_returns_text():
    """direct_tools branch: silent=True must still run the Vòng 2 LLM synthesis
    (tools still get summarized) but must not touch ws or send stream_end."""
    async def scenario():
        ws = FakeWs()
        original_execute_tool = actions.execute_tool
        original_call_llm = actions.call_llm
        actions.execute_tool = _fake_execute_tool_direct

        async def fake_call_llm(**kwargs):
            assert kwargs.get("stream") is False, "silent mode must not stream"
            return _fake_llm_response("Đã kiểm tra an ninh xong.")
        actions.call_llm = fake_call_llm
        try:
            result = await actions.handle_user_intent_with_tools(
                user_text="kiem tra an ninh",
                add_tools=["check_security"],
                conversation_history=[],
                ws=ws,
                agent_name="Agent Security",
                silent=True,
            )
        finally:
            actions.execute_tool = original_execute_tool
            actions.call_llm = original_call_llm
        return result, ws

    result, ws = asyncio.run(scenario())
    assert result == "Đã kiểm tra an ninh xong.", result
    assert ws.sent == [], f"silent mode must not send anything to ws: {ws.sent}"


def test_non_silent_direct_tool_still_streams():
    """Regression guard: default (silent=False) behavior must be unchanged —
    this test only checks that ws.send_json-driven helpers are still invoked
    somewhere, by monkeypatching safe_ws_send_json to record calls."""
    async def scenario():
        ws = FakeWs()
        recorded = []

        async def fake_safe_ws_send_json(_ws, payload):
            recorded.append(payload)
            return True

        import server as server_module
        original_safe_send = server_module.safe_ws_send_json
        server_module.safe_ws_send_json = fake_safe_ws_send_json

        import engine.server.voice_streamer as voice_streamer_module
        original_voice_streamer = voice_streamer_module.VoiceStreamer
        voice_streamer_module.VoiceStreamer = _FakeVoiceStreamer

        original_execute_tool = actions.execute_tool
        original_call_llm = actions.call_llm
        actions.execute_tool = _fake_execute_tool_direct

        async def fake_stream():
            async def gen():
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="Xong."))]
                )
                yield chunk
            return gen()

        async def fake_call_llm(**kwargs):
            assert kwargs.get("stream") is True, "non-silent mode must stream"
            return await fake_stream()
        actions.call_llm = fake_call_llm
        try:
            await actions.handle_user_intent_with_tools(
                user_text="kiem tra an ninh",
                add_tools=["check_security"],
                conversation_history=[],
                ws=ws,
                agent_name="Agent Security",
                silent=False,
            )
        finally:
            actions.execute_tool = original_execute_tool
            actions.call_llm = original_call_llm
            server_module.safe_ws_send_json = original_safe_send
            voice_streamer_module.VoiceStreamer = original_voice_streamer
        return recorded

    recorded = asyncio.run(scenario())
    assert any(p.get("type") == "stream_end" for p in recorded), recorded


def test_silent_internal_llm_tool_skips_streaming():
    """internal_llm_tools branch (e.g. read_screen): silent=True must skip
    Vòng 2 entirely (unchanged — this tool group never used Vòng 2) and just
    return the tool's own text without touching ws."""
    async def scenario():
        ws = FakeWs()
        original_execute_tool = actions.execute_tool
        actions.execute_tool = _fake_execute_tool_internal
        try:
            result = await actions.handle_user_intent_with_tools(
                user_text="xem man hinh",
                add_tools=["read_screen"],
                conversation_history=[],
                ws=ws,
                agent_name="Agent Vision",
                silent=True,
            )
        finally:
            actions.execute_tool = original_execute_tool
        return result, ws

    result, ws = asyncio.run(scenario())
    assert result == "noi dung man hinh", result
    assert ws.sent == [], f"silent mode must not send anything to ws: {ws.sent}"


if __name__ == "__main__":
    test_silent_direct_tool_skips_ws_and_returns_text()
    test_non_silent_direct_tool_still_streams()
    test_silent_internal_llm_tool_skips_streaming()
    print("OK: all actions silent-mode tests passed")
