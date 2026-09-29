"""
JARVIS History Engine - Truy vấn lịch sử hội thoại từ DB + Obsidian Wiki.
"""

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

log = logging.getLogger("jarvis.history_engine")

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "query_history": (
        "QUY TẮC ĐỊNH DẠNG LỊCH SỬ HỘI THOẠI BẮT BUỘC:\n"
        "- Tóm tắt các yêu cầu của người dùng hoặc phản hồi của AI theo thứ tự thời gian dưới dạng danh sách đầu dòng súc tích.\n"
        "- Giữ phản hồi ngắn gọn, dễ đọc, chỉ tập trung vào các ý chính đã trao đổi."
    ),
}

# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_time_range(text: str) -> tuple[Optional[float], Optional[float]]:
    """Phân tích câu hỏi → (since, until). Trả về (None, None) nếu không xác định."""
    now = datetime.now()
    today_start = datetime(now.year, now.month, now.day).timestamp()
    tl = text.lower()

    # "hôm qua"
    if "hôm qua" in tl:
        yesterday = now - timedelta(days=1)
        since = datetime(yesterday.year, yesterday.month, yesterday.day).timestamp()
        until = today_start
        return (since, until)

    # "hôm nay"
    if "hôm nay" in tl:
        since = today_start
        until = now.timestamp()
        return (since, until)

    # "sáng nay"
    if "sáng nay" in tl or "trưa nay" in tl:
        since = today_start
        until = today_start + 43200
        return (since, until)

    # "chiều qua"
    if "chiều qua" in tl:
        yesterday = now - timedelta(days=1)
        since = datetime(yesterday.year, yesterday.month, yesterday.day).timestamp() + 43200
        until = today_start
        return (since, until)

    # "tuần trước"
    if "tuần trước" in tl:
        since = (now - timedelta(days=7)).timestamp()
        until = now.timestamp()
        return (since, until)

    # "tháng 3", "tháng 12"
    month_match = re.search(r"tháng\s*(\d+)", tl)
    if month_match:
        month = int(month_match.group(1))
        year = now.year
        since = datetime(year, month, 1).timestamp()
        if month == 12:
            until = datetime(year + 1, 1, 1).timestamp()
        else:
            until = datetime(year, month + 1, 1).timestamp()
        return (since, until)

    # "hôm kia"
    if "hôm kia" in tl or "ngày kia" in tl:
        day = now - timedelta(days=2)
        since = datetime(day.year, day.month, day.day).timestamp()
        until = since + 86400
        return (since, until)

    # "3 hôm trước", "5 ngày trước"
    day_match = re.search(r"(\d+)\s*(hôm|ngày)\s*trước", tl)
    if day_match:
        n = int(day_match.group(1))
        day = now - timedelta(days=n)
        since = datetime(day.year, day.month, day.day).timestamp()
        until = since + 86400
        return (since, until)

    # "ngày 14/7/2026" hoặc "14/07/2026" hoặc "14/7"
    date_match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{4}))?", tl)
    if date_match:
        day = int(date_match.group(1))
        month = int(date_match.group(2))
        year = int(date_match.group(3)) if date_match.group(3) else now.year
        try:
            dt = datetime(year, month, day)
            since = datetime(dt.year, dt.month, dt.day).timestamp()
            until = since + 86400
            return (since, until)
        except ValueError:
            pass

    return (None, None)


def _format_conversations(rows: list[dict]) -> str:
    """Format dữ liệu conversation_log thành text cho LLM."""
    lines = []
    for r in rows:
        ts = datetime.fromtimestamp(r["created_at"]).strftime("%H:%M:%S")
        date_ts = datetime.fromtimestamp(r["created_at"]).strftime("%Y-%m-%d")
        lines.append(f"[{date_ts} {ts}] User: {r['user_input']}")
        if r["assistant_response"]:
            lines.append(f"[{date_ts} {ts}] AI: {r['assistant_response']}")
        lines.append("---")
    return "\n".join(lines)


def _query_wiki_range(since: float, until: float) -> str:
    """Đọc tất cả file Obsidian daily trong khoảng thời gian.

    Với những ngày Dream đã lưu trữ (không còn file gốc ở daily/), fallback đọc
    bản tóm tắt trong file tổng-kết-tháng — nếu không, các ngày đó sẽ bị bỏ sót
    hoàn toàn khỏi kết quả dù nội dung vẫn còn (chỉ là đã đổi chỗ)."""
    from engine.core.memory_tree import WIKI_DIR
    from engine.core.dream import extract_day_summary_from_month
    wiki_dir = WIKI_DIR / "daily"
    if not wiki_dir.exists():
        return ""

    daily_files: dict[str, Path] = {}
    month_files: dict[str, Path] = {}
    for f in sorted(wiki_dir.rglob("*.md")):
        if f.name.startswith("Tháng "):
            month_files[f.parent.name] = f
            continue
        date_str = f.stem
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            continue
        current = daily_files.get(date_str)
        if current is None or len(f.relative_to(wiki_dir).parts) > len(
            current.relative_to(wiki_dir).parts
        ):
            daily_files[date_str] = f

    parts = []
    covered: set[str] = set()
    for date_str, f in sorted(daily_files.items()):
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        if since <= dt.timestamp() < until:
            content = f.read_text(encoding="utf-8").strip()
            parts.append(f"=== Wiki daily: {date_str} ===\n{content}")
            covered.add(date_str)

    day = datetime.fromtimestamp(since).date()
    end_day = datetime.fromtimestamp(until).date()
    while day < end_day:
        date_str = day.isoformat()
        if date_str not in covered:
            month_file = month_files.get(day.strftime("%m-%Y"))
            if month_file is not None:
                summary = extract_day_summary_from_month(
                    month_file.read_text(encoding="utf-8"), date_str
                )
                if summary:
                    parts.append(f"=== Wiki daily (Dream đã lưu trữ): {date_str} ===\n{summary}")
        day += timedelta(days=1)

    return "\n\n".join(parts)


def query_conversation_history(query_text: str, limit: int = 30) -> str:
    """Truy vấn lịch sử hội thoại từ DB + Obsidian Wiki + session tools."""
    from engine.core.learning import get_learning_engine
    engine = get_learning_engine()

    parts: list[str] = []
    tl = query_text.lower()

    # 1. Session tool history (nếu hỏi về phiên hiện tại)
    if any(kw in tl for kw in ["vừa", "nãy", "lúc nãy", "phiên này", "vừa rồi", "tool"]):
        try:
            from engine.router.replay import recent_outcomes_context as get_session_tool_context
            sess = get_session_tool_context(limit=5)
            if sess:
                parts.append(sess)
        except Exception:
            pass

    # 2. Xác định khoảng thời gian
    since, until = _parse_time_range(query_text)

    # 3. DB messages
    if since is not None and until is not None:
        rows = engine.get_interactions_in_range(since, until)
        log.info(f"History Engine: queried range, got {len(rows)} exchanges")
    else:
        rows = engine.get_recent_interactions(limit=limit)
        log.info(f"History Engine: no time range, got last {len(rows)} exchanges")

    if rows:
        conversation_text = _format_conversations(rows)
        est_tokens = len(conversation_text) // 3
        if est_tokens > 3000:
            ratio = 3000 / est_tokens
            keep = max(10, min(15, int(len(rows) * ratio)))
            rows = rows[-keep:]
            conversation_text = _format_conversations(rows)
            log.info(f"History Engine: trimmed to {keep} exchanges due to token budget")
        parts.append(conversation_text)

    # 4. Obsidian Wiki daily (cho date-range queries)
    if since is not None and until is not None:
        wiki_text = _query_wiki_range(since, until)
        if wiki_text:
            parts.append(f"=== Obsidian Wiki Notes ===\n{wiki_text[:2000]}")

    if not parts:
        return "Không tìm thấy lịch sử hội thoại nào trong khoảng thời gian đó."

    return "\n\n".join(parts)
