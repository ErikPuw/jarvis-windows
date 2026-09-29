import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


@pytest.fixture(autouse=True)
def jobs_data_dir(tmp_path, monkeypatch):
    """Mọi test trong tests/jobs ghi vào tmp_path, không bao giờ vào data/jobs thật."""
    from engine.jobs import store
    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "jobs")
    return tmp_path / "jobs"
