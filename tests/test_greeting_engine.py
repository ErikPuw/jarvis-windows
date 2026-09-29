import asyncio
import random
from datetime import datetime
from types import SimpleNamespace

from engine.main import greeting_engine as ge


def test_slots_cover_every_hour_without_overlap():
    for h in range(24):
        assert sum(s["start"] <= h < s["end"] for s in ge._SLOTS) == 1, h


def test_only_followup_asks_a_question():
    for s in ge._SLOTS:
        assert not any("?" in t for t in s["greet"] + s["care"] + s["remind"])
        assert all(t.count("?") == 1 for t in s["followup"])
        assert s["emoji"], s["start"]


def test_spoken_time():
    assert ge._spoken_time(SimpleNamespace(hour=8, minute=30)) == "8 giờ 30 phút"
    assert ge._spoken_time(SimpleNamespace(hour=9, minute=0)) == "9 giờ"


RAIN = {"desc": "mưa nhẹ", "temp": 27, "kind": "rain", "is_day": True}
CLOUDY = {"desc": "trời nhiều mây", "temp": 29, "kind": "cloudy", "is_day": True}


def test_weather_sentence():
    assert ge._weather_sentence(None, datetime(2026, 9, 28, 8)) == ("", False)
    text, tip = ge._weather_sentence(RAIN, datetime(2026, 9, 28, 8))
    assert text.startswith("🌧️") and "mưa nhẹ" in text and "27" in text and tip
    text, tip = ge._weather_sentence(CLOUDY, datetime(2026, 9, 28, 8))
    assert "nhiều mây" in text and not tip
    for _ in range(20):
        assert "trời hiện trời" not in ge._weather_sentence(CLOUDY, datetime(2026, 9, 28, 8))[0]
    hot = dict(CLOUDY, temp=36)
    assert ge._weather_sentence(hot, datetime(2026, 9, 28, 13))[1]  # nóng -> có nhắc


def test_compose_weather_tip_replaces_generic_reminder():
    random.seed(1)
    with_tip = ge._compose(datetime(2026, 9, 28, 8, 15), RAIN)  # thứ Hai
    assert len(with_tip) == 4  # chào, thời tiết+nhắc, chăm sóc, mời việc
    no_tip = ge._compose(datetime(2026, 9, 28, 8, 15), CLOUDY)
    assert len(no_tip) == 5  # thêm một câu nhắc chung
    no_weather = ge._compose(datetime(2026, 9, 28, 23, 5), None)
    assert len(no_weather) == 4
    for sentences in (with_tip, no_tip, no_weather):
        assert sum(s.count("?") for s in sentences) == 1 and sentences[-1].endswith("?")


def test_compose_varies():
    seen = {tuple(ge._compose(datetime(2026, 9, 28, 8, 15), CLOUDY)) for _ in range(30)}
    assert len(seen) > 20


def test_send_greeting_streams_sentence_by_sentence(monkeypatch):
    ge._greeted_since_boot = False
    put, sent = [], []

    class FakeStreamer:
        def __init__(self, ws):
            self.prefetch_task = self.worker_task = None

        def start(self):
            pass

        async def put(self, sentence):
            put.append(sentence)

        async def stop(self):
            pass

    async def fake_snapshot():
        return RAIN

    async def send(ws, payload):
        sent.append(payload["type"])

    monkeypatch.setattr("engine.server.voice_streamer.VoiceStreamer", FakeStreamer)
    monkeypatch.setattr(ge, "fetch_weather_snapshot", fake_snapshot)

    async def run():
        ws, history = SimpleNamespace(), []
        await ge.send_greeting(ws, history, send)
        await asyncio.sleep(0)
        return history

    history = asyncio.run(run())
    assert len(put) >= 4 and "mưa nhẹ" in put[1]
    assert history[0]["content"] == " ".join(put)
    assert sent[0] == "stream_start" and sent[-1] == "stream_end"
