"""Điểm vào của router cho kind "jobs" (spec mục 5). Mọi câu trả lời đi qua _say: giao diện và Telegram như nhau."""
import logging
import os
import time

from engine.jobs import MAX_SENT_PER_DAY, interview, profile as profile_mod, review, store

log = logging.getLogger("jarvis.jobs.runner")

HELP = ("Lệnh tìm việc:\n"
        "@jobs phỏng vấn — tạo hồ sơ\n"
        "@jobs tiếp tục — hỏi tiếp phần còn dở\n"
        "@jobs sửa hồ sơ — xem và sửa hồ sơ\n"
        "@jobs tìm — tìm việc ngay\n"
        "@jobs tin <nội dung hoặc link> — đánh giá một tin ngài gửi\n"
        "@jobs trạng thái — xem tình trạng")
NO_PROFILE = 'Chưa có hồ sơ. Nói "@jobs phỏng vấn" để bắt đầu.'


async def _say(ctx, text: str) -> str:
    await ctx.send_json(ctx.ws, {"type": "text_chunk", "text": text})
    await ctx.send_json(ctx.ws, {"type": "stream_end"})
    return text


async def handle(d, ctx) -> str:
    try:
        text = await _route(d.source, d.query, time.time())
    except Exception as exc:
        log.exception("[JOBS] failed")
        text = f"Tìm việc gặp lỗi: {exc}"
    return await _say(ctx, text)


async def _route(source: str, query: str, now: float) -> str:
    if source == "session":
        return await _interview_answer(query, now)
    if source == "review":
        cmd = review.parse(query)
        return await review.apply(cmd, now) if cmd else HELP
    return await _command(query, now)


async def _command(query: str, now: float) -> str:
    q = " ".join(str(query or "").split())
    low = q.lower()
    if low in ("phỏng vấn", "tiếp tục", "sửa hồ sơ"):
        fn = interview.reopen if low == "sửa hồ sơ" else interview.resume
        state, reply = fn(store.load("interview.json", {}), now)
        store.save("interview.json", state)
        return reply
    if low == "tìm":
        return await run_search(now)
    if low == "tin" or low.startswith("tin "):
        return await _one_post(q[3:].strip(), now)
    if low == "trạng thái":
        return _status(now)
    return HELP


async def _interview_answer(text: str, now: float) -> str:
    state, reply, finished = interview.answer(store.load("interview.json", {}), text, now)
    store.save("interview.json", state)
    if not finished:
        return reply
    prof = profile_mod.build(state["answers"], os.getenv("GMAIL_ADDRESS", ""))
    store.save("profile.json", prof)
    from engine.jobs import cv
    _, pdf, err = await cv.build_cv(prof)
    lines = ["Đã lưu hồ sơ."]
    missing = profile_mod.missing(prof)
    if missing:
        lines.append("Còn thiếu: " + ", ".join(missing) + '. Nói "@jobs sửa hồ sơ" để bổ sung.')
    lines.append(f"Đã tạo CV: {pdf}" if pdf else f"Chưa tạo được CV PDF: {err}")
    if not missing and pdf:
        lines.append('Nói "@jobs tìm" để tìm việc ngay, hoặc chờ JARVIS tự tìm vào mỗi sáng.')
    return "\n".join(lines)


def _ready_profile() -> tuple[dict | None, str]:
    prof = store.load("profile.json", {})
    if not prof:
        return None, NO_PROFILE
    missing = profile_mod.missing(prof)
    if missing:
        return None, "Hồ sơ còn thiếu: " + ", ".join(missing) + '. Nói "@jobs sửa hồ sơ".'
    return prof, ""


async def _make_pending(prof: dict, found: list[dict], now: float) -> str:
    """Soạn thư cho các tin mới, nối vào danh sách chờ còn hạn (số thứ tự tiếp nối), trả tin nhắn duyệt."""
    from engine.jobs import letter
    pending = store.load("pending.json", {})
    items = list(pending.get("items", [])) if review.pending_open(pending, now) else []
    new = []
    for it in found:
        body = await letter.write(prof, it)
        if not body:
            continue
        entry = dict(it, body=body, n=max((i["n"] for i in items), default=0) + 1)
        items.append(entry)
        new.append(entry)
    store.save("pending.json", {"created_at": now, "items": items})
    return review.render(new)


async def run_search(now: float | None = None) -> str:
    """Dùng chung cho "@jobs tìm" và scheduler."""
    from engine.jobs import search
    now = time.time() if now is None else now
    prof, error = _ready_profile()
    if prof is None:
        return error
    log_data = store.load("log.json", {})
    found = await search.find_jobs(prof, log_data)
    store.save("log.json", log_data)
    return await _make_pending(prof, found, now)


async def _one_post(content: str, now: float) -> str:
    from engine.jobs import search
    if not content:
        return 'Gửi kèm nội dung tin hoặc link, ví dụ: "@jobs tin <nội dung>".'
    prof, error = _ready_profile()
    if prof is None:
        return error
    url = ""
    if content.lower().startswith(("http://", "https://")):
        from engine.tools.browser import browser
        url = content.split()[0]
        page = await browser.visit(url)
        if page is None:
            return "Không mở được link này. Ngài dán nội dung tin vào nhé."
        content = page.text_content
    log_data = store.load("log.json", {})
    item = await search.evaluate(prof, log_data, content, url)
    store.save("log.json", log_data)
    if not item:
        return "Tin này bị loại: không có email nhận CV, không phải tiếng Việt, không hợp hồ sơ, hoặc đã nộp rồi."
    return await _make_pending(prof, [item], now)


def _status(now: float) -> str:
    state = store.load("interview.json", {})
    pending = store.load("pending.json", {})
    log_data = store.load("log.json", {})
    waiting = len(pending.get("items", [])) if review.pending_open(pending, now) else 0
    return "\n".join([
        f"Phỏng vấn: {state.get('status', 'chưa bắt đầu')}",
        f"Hồ sơ: {'đã có' if store.load('profile.json', {}) else 'chưa có'}",
        f"CV PDF: {'có' if store.file_path('CV.pdf').exists() else 'chưa có'}",
        f"Chờ duyệt: {waiting} thư",
        f"Đã gửi hôm nay: {review.sent_today(log_data, now)}/{MAX_SENT_PER_DAY}",
        f"Lần tìm tự động gần nhất: {log_data.get('last_run_date', 'chưa có')}",
    ])
