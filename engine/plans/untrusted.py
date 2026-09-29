"""Chốt chặn prompt injection cho nội dung KHÔNG tin cậy: trang web, báo cáo agent, lịch sử
(spec 2026-09-26 mục 7). Chỉ import stdlib + hằng số ở đầu file: engine/tools/research_engine.py dùng module này."""
import re
import unicodedata

from engine.plans import MAX_QUERY_CHARS, REPORT_CHARS

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200d\u2060\ufeff]")
# Token chat template, thẻ nội bộ của JARVIS và thẻ khung dữ liệu: nội dung ngoài không được mang chúng.
_TAGS = re.compile(
    r"<\|[^<>|]{0,40}\|>"
    r"|</?\s*(?:think|tool_call|tool_response|start_of_turn|end_of_turn|ask_user|action_run|du_lieu)\b[^>]*>",
    re.I,
)
# Mẫu riêng cho nội dung ngoài, bổ sung guardrails.looks_like_injection.
_EXTRA_INJECTION = [
    re.compile(r"^\s*(?:system|assistant|developer)\s*:\s*(?:you\b|bạn\b|hãy\b|ignore\b|bỏ\s+qua)", re.I | re.M),
    re.compile(r"\bnew\s+instructions?\s*:", re.I),
    re.compile(r"(?:chỉ\s+thị|yêu\s+cầu|lệnh)\s+mới\s+(?:cho|dành\s+cho)\s+(?:ai|trợ\s+lý|jarvis|bạn|mô\s+hình)\b", re.I),
]
_BAD_QUERY = re.compile(r"https?://|www\.|[\w.+-]+@[\w-]+\.\w|(?:\d[\s.\-]?){9,}|[<>{}]", re.I)
_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_HTML = re.compile(r"</?[A-Za-z][^>\n]{0,200}>")
_MD_LINK = re.compile(r"\[([^\]\n]+)\]\((\S+?)\)")
_URL = re.compile(r"https?://[^\s)\]>\"'<]+")
_URL_TAIL = ".,;:"
_MULTI_SPACE = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCT = re.compile(r"[ \t]+([,.;:!?])")


def clean(text) -> str:
    """NFKC, bỏ ký tự điều khiển/zero-width, bỏ token template và thẻ nội bộ (lặp tới khi ổn định)."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = _CONTROL.sub("", text)
    prev = None
    while prev != text:
        prev, text = text, _TAGS.sub("", text)
    return text


def looks_injected(text) -> bool:
    """Văn bản ra lệnh cho trợ lý. Regex: chỉ giảm nhiễu — an toàn thật nằm ở chỗ model đọc nó không có tool."""
    from engine.core.guardrails import looks_like_injection
    text = clean(text)
    return looks_like_injection(text) or any(p.search(text) for p in _EXTRA_INJECTION)


def status_label(status) -> str:
    return {"success": "THÀNH CÔNG", "failed": "THẤT BẠI"}.get(status, "KHÔNG CÓ KẾT QUẢ")


def frame(index: int, result: dict) -> str:
    """Một báo cáo bước, đóng khung là DỮ LIỆU cho planner/solver."""
    source = clean(result.get("target") or result.get("agent") or "")
    body = clean(result.get("result", ""))[:REPORT_CHARS]
    return (f'<du_lieu buoc="{index}" nguon="{source}" trang_thai="{status_label(result.get("status"))}">\n'
            f"Tra cứu: {clean(result.get('query', ''))}\n{body}\n</du_lieu>")


def query_ok(query) -> bool:
    """Câu tra cứu do planner viết: ngắn, không URL/email/số dài/ngoặc nhọn (chặn rò dữ liệu qua câu tìm kiếm)."""
    if not isinstance(query, str):
        return False
    q = query.strip()
    return 0 < len(q) <= MAX_QUERY_CHARS and not _BAD_QUERY.search(q)


def sources_of(done) -> set[str]:
    """Các URL xuất hiện trong báo cáo: chỉ những URL này được phép còn trong câu trả lời."""
    return {u.rstrip(_URL_TAIL) for r in (done or []) for u in _URL.findall(str(r.get("result", "")))}


def sanitize_answer(text, sources) -> str:
    """Câu trả lời cuối: bỏ thẻ ask_user/action_run, ảnh, HTML; liên kết/URL lạ bị bỏ (chặn rò qua ảnh/link)."""
    from engine.router.ask_user import extract
    text, _ = extract(str(text or ""))
    text = _IMG.sub("", text)
    text = _HTML.sub("", text)
    allowed = set(sources or ())
    text = _MD_LINK.sub(lambda m: m.group(0) if m.group(2).rstrip(_URL_TAIL) in allowed else m.group(1), text)
    text = _URL.sub(_keep_allowed_url(allowed), text)
    # chỗ vừa xoá để lại dấu cách thừa / dấu cách trước dấu câu; giữ nguyên xuống dòng (bảng Markdown)
    text = _SPACE_BEFORE_PUNCT.sub(r"\1", _MULTI_SPACE.sub(" ", text))
    return text.strip()


def _keep_allowed_url(allowed):
    def repl(m):
        url = m.group(0)
        core = url.rstrip(_URL_TAIL)
        return url if core in allowed else url[len(core):]  # URL lạ bị xoá, dấu câu dính sau nó thì giữ
    return repl
