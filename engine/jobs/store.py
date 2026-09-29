"""Đọc/ghi JSON trong data/jobs. Ghi file tạm rồi đổi tên để file không bao giờ bị ghi dở (spec mục 4)."""
import json
import os
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "jobs"


def file_path(name: str) -> Path:
    return DATA_DIR / name


def load(name: str, default):
    try:
        return json.loads(file_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save(name: str, data) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, file_path(name))
