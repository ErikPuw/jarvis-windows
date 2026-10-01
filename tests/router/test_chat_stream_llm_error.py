"""Stream LLM đứt giữa chừng: VoiceStreamer phải dừng, gửi status idle, không để task treo."""
import asyncio, sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import chat_stream
from engine.router.types import TurnContext


class _WS:
    tts_disabled = False
    cancel_requested = False


def test_llm_stream_error_stops_voice_streamer(monkeypatch):
    import engine.server.llm_server as llm_server
    import engine.server.voice_streamer as voice_streamer

    sent, made = [], []

    async def send(ws, data):
        sent.append(data)
        return True

    async def fake_tts(text):
        yield "AAAA"

    async def broken_stream():
        yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Xin chào ngài. "))])
        raise ConnectionError("llama-server mất kết nối")

    async def fake_llm(*a, **k):
        return broken_stream()

    real = voice_streamer.VoiceStreamer

    def make(ws):
        s = real(ws, speech_gen_fn=fake_tts, send_fn=send)
        made.append(s)
        return s

    monkeypatch.setattr(llm_server, "call_llm", fake_llm)
    monkeypatch.setattr(voice_streamer, "VoiceStreamer", make)

    async def run():
        # Assert trong vòng lặp: asyncio.run() tự huỷ task còn treo khi thoát, che mất lỗi.
        ws = _WS()
        out = await asyncio.wait_for(chat_stream.stream_chat([], "hi", TurnContext(ws=ws, send_json=send)), 10)
        await asyncio.sleep(0.05)
        s = made[0]
        assert "lỗi kết nối" in out
        assert s.prefetch_task.done() and s.worker_task.done()
        assert {"type": "status", "state": "idle", "source": "tts"} in sent
        assert ws.tts_active is False

    asyncio.run(run())
