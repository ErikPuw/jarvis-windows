"""Tìm tin có email nhận CV, lọc bằng code, chấm điểm bằng LLM (spec mục 8).
Email người nhận CHỈ lấy bằng regex từ trang gốc, không bao giờ từ đầu ra của LLM."""
import logging
import re
from urllib.parse import urlparse

from engine import prompts
from engine.core.json_parser import safe_json_loads
from engine.jobs import EMAIL_WINDOW, LOW_ENGLISH, MAX_PENDING, MIN_SCORE, POST_CHARS, RESULTS_PER_QUERY
from engine.plans.untrusted import clean, looks_injected
from engine.server import llm_server

log = logging.getLogger("jarvis.jobs.search")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
KEYWORD_RE = re.compile(r"cv|ứng tuyển|hồ sơ|gửi về|gửi qua", re.I)
_BLOCKED_LOCAL = {"noreply", "no-reply", "support"}
_SITE_LOCAL = {"info", "contact"}
_VI_CHARS = set("àáảãạăằắẳẵặâầấẩẫậđèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵ")

SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "score": {"type": "integer", "minimum": 0, "maximum": 10},
            "reason": {"type": "string", "maxLength": 200},
            "title": {"type": "string", "maxLength": 100},
            "company": {"type": "string", "maxLength": 100},
            "english": {"type": "string", "enum": ["none", "preferred", "required"]},
            "dealbreaker": {"type": "boolean"},
        },
        "required": ["score", "reason", "title", "company", "english", "dealbreaker"],
    },
}


def queries(profile: dict) -> list[str]:
    location = profile.get("location", "")
    return [" ".join(f"tuyển {p} {location} gửi CV email".split()) for p in profile.get("positions") or []]


def _host(url) -> str:
    host = (urlparse(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _same_site(domain: str, host: str) -> bool:
    return bool(host) and (domain == host or host.endswith("." + domain) or domain.endswith("." + host))


def _acceptable(email: str, host: str) -> bool:
    local, _, domain = email.lower().partition("@")
    if local in _BLOCKED_LOCAL:
        return False
    return not (local in _SITE_LOCAL and _same_site(domain, host))


def find_apply_email(text, page_url: str = "") -> str:
    """Email đầu tiên sau từ khoá (trong EMAIL_WINDOW ký tự), rồi mới xét phía trước. "" nếu không có."""
    text, host = str(text or ""), _host(page_url)
    for kw in KEYWORD_RE.finditer(text):
        after = text[kw.end(): kw.end() + EMAIL_WINDOW]
        before = text[max(0, kw.start() - EMAIL_WINDOW): kw.start()]
        for chunk in (after, before):
            for m in EMAIL_RE.finditer(chunk):
                email = m.group(0).rstrip(".")
                if _acceptable(email, host):
                    return email
    return ""


def is_vietnamese(text) -> bool:
    letters = [c for c in str(text or "").lower() if c.isalpha()]
    return bool(letters) and sum(c in _VI_CHARS for c in letters) / len(letters) >= 0.01


def _norm(s) -> str:
    return " ".join(str(s or "").lower().split())


def already_sent(email: str, title: str, log_data: dict) -> bool:
    return any(_norm(s.get("email")) == _norm(email) and _norm(s.get("title")) == _norm(title)
               for s in log_data.get("sent", []))


def profile_text(profile: dict) -> str:
    return "\n".join([
        f"Vị trí mong muốn: {', '.join(profile.get('positions') or [])}",
        f"Nơi sống: {profile.get('location', '')}",
        f"Kinh nghiệm: {'; '.join(profile.get('experience') or [])}",
        f"Học vấn: {'; '.join(profile.get('education') or [])}",
        f"Chứng chỉ: {', '.join(profile.get('certificates') or [])}",
        f"Kỹ năng: {', '.join(profile.get('skills') or [])}",
        f"Tiếng Anh: {profile.get('english', '')}",
        f"Mong muốn: {profile.get('expectations', '')}",
        f"Không chấp nhận: {', '.join(profile.get('dealbreakers') or [])}",
    ])


def frame_post(text) -> str:
    return f'<du_lieu nguon="tin_tuyen_dung">\n{clean(text)[:POST_CHARS]}\n</du_lieu>'


async def score(profile: dict, post_text: str) -> dict | None:
    messages = [
        {"role": "system", "content": prompts.load("jobs_score")},
        {"role": "user", "content": f"Hồ sơ ứng viên:\n{profile_text(profile)}\n\nTin tuyển dụng:\n{frame_post(post_text)}"},
    ]
    try:
        response = await llm_server.call_llm(
            messages=messages, stream=False, thinking=False,
            temperature=0.0, max_tokens=300, response_format=SCHEMA,
        )
        data = safe_json_loads(response.choices[0].message.content or "")
    except Exception as exc:
        log.warning("[JOBS] score failed: %s", exc)
        return None
    if not isinstance(data, dict) or not isinstance(data.get("score"), int):
        return None
    return data


def keep(result: dict, profile: dict) -> tuple[bool, str]:
    if result.get("dealbreaker"):
        return False, ""
    english = result.get("english")
    if english == "required" and profile.get("english", "không") in LOW_ENGLISH:
        return False, ""
    if int(result.get("score", 0)) < MIN_SCORE:
        return False, ""
    return True, ("⚠️ ưu tiên tiếng Anh" if english == "preferred" else "")


def _one_line(s, limit: int = 100) -> str:
    return " ".join(clean(s).split())[:limit]


async def evaluate(profile: dict, log_data: dict, text: str, url: str = "") -> dict | None:
    """Một tin → mục chờ duyệt, hoặc None nếu bị loại. Ghi url vào log_data["seen"] (caller lưu file)."""
    text = clean(text)
    if url:
        log_data.setdefault("seen", []).append(url)
    email = find_apply_email(text, url)
    if not email or not is_vietnamese(text) or looks_injected(text):
        return None
    result = await score(profile, text)
    if not result:
        return None
    ok, flag = keep(result, profile)
    title = _one_line(result.get("title")) or "vị trí đang tuyển"
    if not ok or already_sent(email, title, log_data):
        return None
    return {"title": title, "company": _one_line(result.get("company")), "email": email, "url": url,
            "score": int(result["score"]), "flag": flag, "reason": _one_line(result.get("reason"), 200),
            "post": text[:POST_CHARS]}


async def find_jobs(profile: dict, log_data: dict) -> list[dict]:
    from engine.tools.browser import browser
    seen = set(log_data.get("seen", []))
    items = []
    for query in queries(profile):
        try:
            results = await browser.search(query, max_results=RESULTS_PER_QUERY)
        except Exception as exc:
            log.warning("[JOBS] search failed for %r: %s", query, exc)
            continue
        for r in results:
            if r.url in seen:
                continue
            seen.add(r.url)
            page = await browser.visit(r.url)
            if page is None:
                log_data.setdefault("seen", []).append(r.url)
                continue
            item = await evaluate(profile, log_data, page.text_content, r.url)
            if item:
                items.append(item)
    items.sort(key=lambda i: i["score"], reverse=True)
    unique, keys = [], set()
    for item in items:
        key = (_norm(item["email"]), _norm(item["title"]))
        if key not in keys:
            keys.add(key)
            unique.append(item)
    return unique[:MAX_PENDING]
