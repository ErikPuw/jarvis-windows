"""Quản lý persona: identity, soul, user profile và persona_short (spec 2026-09-25 mục 2)."""
from pathlib import Path
from engine.prompts import load

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompt"


def get_identity() -> str:
    """Nạp nội dung identity từ prompt/identity.md."""
    return load("identity")


def get_soul() -> str:
    """Nạp nội dung soul từ prompt/soul.md."""
    return load("soul")


def get_user_profile() -> str:
    """Nạp nội dung user profile từ prompt/user.md."""
    return load("user")


def short() -> str:
    """Nạp đoạn persona ngắn dùng chung cho tóm tắt tool và synthesizer."""
    return load("persona_short")


def load_full_persona() -> dict[str, str]:
    """Trả về dict chứa cả 3 khối cốt lõi."""
    return {
        "identity": get_identity(),
        "soul": get_soul(),
        "user": get_user_profile(),
    }
