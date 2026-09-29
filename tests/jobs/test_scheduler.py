"""Chạy mỗi sáng sau 08:00, một lần/ngày, chạy bù khi bật máy muộn (spec mục 11)."""
import asyncio
from datetime import datetime

from engine.jobs import scheduler, store


def test_due():
    assert scheduler.due(datetime(2026, 9, 28, 8, 0), {}, True)
    assert not scheduler.due(datetime(2026, 9, 28, 7, 59), {}, True)
    assert not scheduler.due(datetime(2026, 9, 28, 9, 0), {"last_run_date": "2026-09-28"}, True)
    assert scheduler.due(datetime(2026, 9, 28, 21, 0), {"last_run_date": "2026-09-27"}, True)
    assert not scheduler.due(datetime(2026, 9, 28, 9, 0), {}, False)


def test_tick_runs_once_per_day(monkeypatch):
    store.save("profile.json", {"full_name": "A"})
    from engine.jobs import runner
    runs, notes = [], []

    async def fake_run(now=None):
        runs.append(now)
        return "danh sách"

    async def notify(text):
        notes.append(text)
    monkeypatch.setattr(runner, "run_search", fake_run)
    now = datetime(2026, 9, 28, 9, 0)
    assert asyncio.run(scheduler.tick(now, notify)) is True
    assert asyncio.run(scheduler.tick(now, notify)) is False
    assert notes == ["danh sách"] and runs == [now.timestamp()]
    assert store.load("log.json", {})["last_run_date"] == "2026-09-28"


def test_telegram_broadcast_sends_to_every_allowed_chat(monkeypatch):
    from engine.server.telegram_bot import TelegramBot
    bot = TelegramBot("t", {2, 1}, None)
    sent = []

    async def fake_send(chat_id, text):
        sent.append((chat_id, text))
    monkeypatch.setattr(bot, "_send_text", fake_send)
    asyncio.run(bot.broadcast("xin chào"))
    assert sent == [(1, "xin chào"), (2, "xin chào")]
