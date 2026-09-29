import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def isolate_jobs_data(tmp_path, monkeypatch):
    """Router đọc data/jobs để biết đang phỏng vấn/chờ duyệt: test router không được thấy file thật."""
    from engine.jobs import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "jobs")
    return tmp_path / "jobs"
