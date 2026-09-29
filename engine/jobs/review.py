"""Danh sách chờ duyệt và lệnh "gửi 1, 3" / "bỏ 2" / "sửa thư 1: …" (spec mục 10).
Chỉ lệnh của ngài mới dẫn tới mailer.send. Router import parse/pending_open nên module này nhẹ (import lười)."""
import asyncio
import re
import time
from datetime import datetime

from engine.jobs import MAX_SENT_PER_DAY, PENDING_TTL_S, SEND_GAP_S, store

REVIEW_RE = re.compile(
    r"^\s*(?:(gửi|bỏ)\s+(\d+(?:\s*,\s*\d+)*)|sửa thư\s+(\d+)\s*:\s*(\S.*?))\s*[.!]?\s*$", re.I | re.S)
HINT = 'Trả lời "gửi 1, 3", "bỏ 2" hoặc "sửa thư 1: <ý muốn>".'


def parse(text):
    m = REVIEW_RE.match(str(text or ""))
    if not m:
        return None
    if m.group(1):
        nums = sorted({int(n) for n in re.findall(r"\d+", m.group(2))})
        return ("send" if m.group(1).lower() == "gửi" else "drop", nums, "")
    return ("edit", [int(m.group(3))], m.group(4).strip())


def pending_open(pending, now: float) -> bool:
    return (isinstance(pending, dict) and bool(pending.get("items"))
            and now - float(pending.get("created_at", 0)) <= PENDING_TTL_S)


def render(items: list[dict]) -> str:
    if not items:
        return "Chưa có tin phù hợp."
    lines = [f"Tìm được {len(items)} việc phù hợp:"]
    for it in items:
        head = f"{it['n']}. {it['title']}" + (f" – {it['company']}" if it.get("company") else "") + f" ({it['score']}/10)"
        if it.get("flag"):
            head += f" {it['flag']}"
        lines += [head, f"   → {it['email']}" + (f" · {it['url']}" if it.get("url") else ""),
                  f"   Lý do: {it.get('reason', '')}", "", it["body"], ""]
    lines.append(HINT)
    return "\n".join(lines)


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts).date().isoformat()


def sent_today(log_data: dict, now: float) -> int:
    return sum(1 for s in log_data.get("sent", []) if _day(float(s.get("at", 0))) == _day(now))


async def apply(cmd, now: float | None = None, sleep=asyncio.sleep) -> str:
    from engine.jobs import letter, mailer
    now = time.time() if now is None else now
    action, nums, wish = cmd
    pending = store.load("pending.json", {})
    if not pending_open(pending, now):
        return 'Danh sách chờ duyệt đã hết hạn hoặc trống. Nói "@jobs tìm" để tìm lại.'
    items = {it["n"]: it for it in pending["items"]}
    unknown = [n for n in nums if n not in items]
    if unknown:
        return f"Không có số {', '.join(map(str, unknown))} trong danh sách. Không làm gì cả."
    if action == "drop":
        pending["items"] = [it for it in pending["items"] if it["n"] not in nums]
        store.save("pending.json", pending)
        return f"Đã bỏ {', '.join(map(str, nums))}."
    profile = store.load("profile.json", {})
    if action == "edit":
        item = items[nums[0]]
        body = await letter.write(profile, item, wish)
        if not body:
            return "Không soạn lại được thư hợp lệ. Thư cũ vẫn giữ nguyên."
        item["body"] = body
        store.save("pending.json", pending)
        return render([item])
    if mailer.config() is None:
        return "Chưa cấu hình Gmail (GMAIL_ADDRESS, GMAIL_APP_PASSWORD trong .env). Không gửi thư nào."
    pdf = store.file_path("CV.pdf")
    if not pdf.exists():
        return 'Chưa có CV.pdf. Nói "@jobs sửa hồ sơ" rồi "đúng" để tạo lại CV. Không gửi thư nào.'
    log_data = store.load("log.json", {})
    room = MAX_SENT_PER_DAY - sent_today(log_data, now)
    if room <= 0:
        return f"Đã gửi đủ {MAX_SENT_PER_DAY} thư hôm nay. Gửi tiếp vào ngày mai."
    todo = nums[:room]
    sent, lines = 0, []
    filename = f"CV_{profile.get('full_name', '')}.pdf"
    for i, n in enumerate(todo):
        item = items[n]
        if i:
            await sleep(SEND_GAP_S)
        try:
            await asyncio.to_thread(mailer.send, item["email"], letter.subject(item, profile), item["body"],
                                    profile.get("email", ""), pdf, filename)
        except Exception as exc:
            lines.append(f"Thư {n} lỗi: {exc}. Dừng, không gửi các thư còn lại.")
            break
        sent += 1
        log_data.setdefault("sent", []).append(
            {"at": now, "email": item["email"], "title": item["title"], "url": item.get("url", "")})
        pending["items"] = [it for it in pending["items"] if it["n"] != n]
        store.save("log.json", log_data)
        store.save("pending.json", pending)
        lines.append(f"Thư {n} → {item['email']}: đã gửi.")
    if len(todo) < len(nums):
        lines.append(f"Còn {len(nums) - len(todo)} thư chưa gửi vì đã đủ {MAX_SENT_PER_DAY} thư hôm nay.")
    return f"Đã gửi {sent}/{len(nums)}.\n" + "\n".join(lines)
