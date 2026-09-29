"""Router hỏi: câu này thuộc phiên phỏng vấn hay là lệnh duyệt? Chỉ đọc file, không LLM (spec mục 5)."""
import logging
import time

from engine.jobs import interview, review, store

log = logging.getLogger("jarvis.jobs.gate")


def route_source(text, now: float | None = None) -> str | None:
    t = str(text or "").strip()
    if not t or t.startswith("@"):
        return None
    now = time.time() if now is None else now
    try:
        if interview.is_open(store.load("interview.json", {}), now):
            return "session"
        if review.parse(t) and review.pending_open(store.load("pending.json", {}), now):
            return "review"
    except Exception as exc:
        log.warning("[JOBS] gate failed: %s", exc)
    return None
