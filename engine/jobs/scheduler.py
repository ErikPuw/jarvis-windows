"""Tìm việc tự động mỗi sáng (spec mục 11). Máy tắt buổi sáng → chạy bù khi bật."""
import asyncio
import logging
from datetime import datetime

from engine.jobs import RUN_HOUR, SCHEDULER_TICK_S, store

log = logging.getLogger("jarvis.jobs.scheduler")


def due(now: datetime, log_data: dict, has_profile: bool) -> bool:
    return has_profile and now.hour >= RUN_HOUR and log_data.get("last_run_date") != now.date().isoformat()


async def tick(now: datetime, notify) -> bool:
    log_data = store.load("log.json", {})
    if not due(now, log_data, bool(store.load("profile.json", {}))):
        return False
    log_data["last_run_date"] = now.date().isoformat()
    store.save("log.json", log_data)  # ghi trước: lỗi giữa chừng cũng không chạy lại liên tục trong ngày
    from engine.jobs.runner import run_search
    await notify(await run_search(now.timestamp()))
    return True


def start(notify) -> asyncio.Task:
    async def loop():
        while True:
            try:
                await tick(datetime.now(), notify)
            except Exception as exc:
                log.warning("[JOBS] scheduled run failed: %s", exc)
            await asyncio.sleep(SCHEDULER_TICK_S)
    return asyncio.create_task(loop(), name="jobs-scheduler")
