"""Gom câu trả lời phỏng vấn thành hồ sơ bằng code, không LLM, nên không thể bịa thêm (spec mục 6)."""
import re

_COMMA = re.compile(r"[,;\n]")
_LINE = re.compile(r"[;\n]")
_REQUIRED = {
    "full_name": "họ tên (câu 1)",
    "phone": "số điện thoại (câu 2)",
    "email": "email (câu 3)",
    "positions": "vị trí ứng tuyển (câu 5)",
}


def _items(value, sep=_COMMA) -> list[str]:
    return [p.strip() for p in sep.split(str(value or "")) if p.strip()]


def build(answers: dict, gmail: str = "") -> dict:
    a = answers or {}

    def text(key: str) -> str:
        return str(a.get(key) or "").strip()

    return {
        "full_name": text("full_name"),
        "phone": text("phone"),
        "email": text("email") or gmail.strip(),
        "location": text("location"),
        "positions": _items(a.get("positions"))[:3],
        "experience": [str(e).strip() for e in a.get("experience") or [] if str(e).strip()],
        "education": _items(a.get("education"), _LINE),
        "certificates": _items(a.get("certificates")),
        "skills": _items(a.get("skills")),
        "english": text("english") or "không",
        "expectations": text("expectations"),
        "dealbreakers": _items(a.get("dealbreakers")),
    }


def missing(profile: dict) -> list[str]:
    """Trường bắt buộc còn trống: thiếu thì không tìm việc, không gửi thư."""
    return [label for key, label in _REQUIRED.items() if not profile.get(key)]
