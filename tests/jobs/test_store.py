"""Kho JSON trong data/jobs (spec 2026-09-27 mục 4)."""
from engine.jobs import store


def test_save_then_load_roundtrip(jobs_data_dir):
    store.save("x.json", {"a": "Tiếng Việt"})
    assert store.load("x.json", {}) == {"a": "Tiếng Việt"}
    assert store.file_path("x.json") == jobs_data_dir / "x.json"
    assert not list(jobs_data_dir.glob("*.tmp"))


def test_load_missing_or_broken_returns_default(jobs_data_dir):
    assert store.load("none.json", {"d": 1}) == {"d": 1}
    jobs_data_dir.mkdir(parents=True)
    (jobs_data_dir / "bad.json").write_text("{không phải json", encoding="utf-8")
    assert store.load("bad.json", []) == []
