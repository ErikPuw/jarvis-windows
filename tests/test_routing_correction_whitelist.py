"""Tests for routing_correction expected_route whitelist.
Run: python tests/test_routing_correction_whitelist.py"""
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.learning import LearningEngine


def _engine_with_memory_db():
    """LearningEngine whose DB is a fresh temp-file sqlite with the two
    tables store_routing_correction touches. Temp file (not :memory:) vì hàm
    thật close() connection sau mỗi lần gọi. Never touches data/jarvis.db."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE agent_outcomes ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, query TEXT, "
        "status TEXT, created_at REAL)"
    )
    conn.execute(
        "CREATE TABLE learnings ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, content TEXT, "
        "source TEXT, importance INTEGER, created_at REAL)"
    )
    conn.execute(
        "INSERT INTO agent_outcomes (agent, query, status, created_at) "
        "VALUES ('search', 'dang coi van de o dau', 'success', ?)",
        (time.time(),),
    )
    conn.commit()
    engine = LearningEngine.__new__(LearningEngine)
    engine._get_learning_db = lambda: sqlite3.connect(tmp.name)
    return engine, tmp.name


def _stored_correction(dbpath):
    conn = sqlite3.connect(dbpath)
    try:
        row = conn.execute(
            "SELECT content FROM learnings WHERE type='routing_correction' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, "correction was not stored"
    return json.loads(row[0])


def test_garbage_expected_route_coerced_to_general():
    """Regression: từng có dòng ghi expected_route là câu tiếng Việt khiến
    gate in nguyên văn vào prompt mà model không map được vào bucket."""
    engine, conn = _engine_with_memory_db()
    assert engine.store_routing_correction("sai roi", "sai roi", "chi tra loi hoi thoai") is True
    assert _stored_correction(conn)["expected_route"] == "general"


def test_valid_expected_route_passes_through():
    engine, conn = _engine_with_memory_db()
    assert engine.store_routing_correction("sai roi", "sai roi", "Orchestrator") is True
    assert _stored_correction(conn)["expected_route"] == "orchestrator"


def test_no_recent_outcome_stores_nothing():
    engine, dbpath = _engine_with_memory_db()
    conn = sqlite3.connect(dbpath)
    conn.execute("UPDATE agent_outcomes SET created_at=?", (time.time() - 3600,))
    conn.commit()
    conn.close()
    assert engine.store_routing_correction("sai roi", "sai roi", "general") is False
    conn = sqlite3.connect(dbpath)
    try:
        assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 0
    finally:
        conn.close()


if __name__ == "__main__":
    test_garbage_expected_route_coerced_to_general()
    test_valid_expected_route_passes_through()
    test_no_recent_outcome_stores_nothing()
    print("OK: all routing correction whitelist tests passed")
