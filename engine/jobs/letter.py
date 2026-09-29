"""Soạn thư xin việc tiếng Việt cho một tin; code kiểm tra thư trước khi dùng (spec mục 9)."""
import logging
import re

from engine import prompts
from engine.jobs import LETTER_MAX_WORDS
from engine.jobs.search import EMAIL_RE, frame_post, profile_text
from engine.plans.untrusted import clean
from engine.server import llm_server

log = logging.getLogger("jarvis.jobs.letter")

_URL = re.compile(r"https?://|www\.", re.I)
_PHONE = re.compile(r"(?:\d[\s.\-]?){9,}")


def _digits(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def letter_ok(body: str, profile: dict) -> bool:
    if not body.strip() or len(body.split()) > LETTER_MAX_WORDS or _URL.search(body):
        return False
    own_email = str(profile.get("email") or "").lower()
    if any(m.group(0).rstrip(".").lower() != own_email for m in EMAIL_RE.finditer(body)):
        return False
    own_phone = _digits(profile.get("phone"))
    return not any(_digits(m.group(0)) != own_phone for m in _PHONE.finditer(body))


def subject(item: dict, profile: dict) -> str:
    return f"Ứng tuyển {item['title']} – {profile.get('full_name', '')}"


async def write(profile: dict, item: dict, wish: str = "") -> str | None:
    user = (f"Hồ sơ ứng viên:\nHọ tên: {profile.get('full_name', '')}\nSĐT: {profile.get('phone', '')}\n"
            f"Email: {profile.get('email', '')}\n{profile_text(profile)}\n\n"
            f"Vị trí: {item['title']} – {item.get('company', '')}\n\n"
            f"Tin tuyển dụng:\n{frame_post(item.get('post', ''))}")
    if wish:
        user += f"\n\nYêu cầu chỉnh sửa của ứng viên: {clean(wish)[:300]}"
    messages = [{"role": "system", "content": prompts.load("jobs_letter")}, {"role": "user", "content": user}]
    for _ in range(2):
        try:
            response = await llm_server.call_llm(messages=messages, stream=False, thinking=False,
                                                 temperature=0.3, max_tokens=800)
            body = clean(response.choices[0].message.content or "").strip()
        except Exception as exc:
            log.warning("[JOBS] letter failed: %s", exc)
            return None
        if letter_ok(body, profile):
            return body
        log.info("[JOBS] letter rejected by checks")
    return None
