"""Learning/Evolution must not persist emoji into md files or the DB — emoji only
shows up in live chat responses, never in what gets written to disk/DB.
Run: python tests/test_no_emoji_in_storage.py"""
import json
import sqlite3
import tempfile
import time
import types
from pathlib import Path

import engine.core.learning as learning_mod
from engine.core.learning import LearningEngine

EMOJI = "🤵✨😊"


def _learnings_db(tmp) -> str:
    db = str(Path(tmp) / "l.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE learnings (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, "
        "semantic_key TEXT DEFAULT '', content TEXT, source TEXT, importance INTEGER, "
        "created_at REAL, embedding TEXT DEFAULT '')"
    )
    conn.execute(
        "CREATE TABLE agent_outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, "
        "query TEXT, status TEXT, result TEXT DEFAULT '', traces TEXT DEFAULT '[]', created_at REAL)"
    )
    conn.execute(
        "CREATE TABLE validated_workflows (id INTEGER PRIMARY KEY AUTOINCREMENT, agent TEXT, "
        "intent TEXT, tool_chain TEXT, argument_keys TEXT, success_evidence TEXT, "
        "validation_count INTEGER DEFAULT 1, status TEXT DEFAULT 'validated', wiki_path TEXT, "
        "sample_queries TEXT DEFAULT '[]', created_at REAL, updated_at REAL, "
        "UNIQUE(agent, tool_chain))"
    )
    conn.commit()
    conn.close()
    return db


def _fresh_engine(db_path: str) -> LearningEngine:
    le = LearningEngine.__new__(LearningEngine)

    def _conn():
        c = sqlite3.connect(db_path)
        c.row_factory = sqlite3.Row
        return c

    le._get_learning_db = _conn
    le._sync_learning_wiki = lambda: None
    le._sync_workflow_hub = lambda: None
    return le


def _fetchone(le, sql):
    conn = le._get_learning_db()
    try:
        return conn.execute(sql).fetchone()
    finally:
        conn.close()


def test_store_learning_strips_emoji():
    with tempfile.TemporaryDirectory() as tmp:
        le = _fresh_engine(_learnings_db(tmp))
        assert le._store_learning(f"Thích cà phê buổi sáng {EMOJI}", "preference", "coffee")
        row = _fetchone(le, "SELECT content FROM learnings")
        assert EMOJI not in row["content"] and "Thích cà phê" in row["content"], row["content"]


def test_store_outcome_lesson_strips_emoji():
    with tempfile.TemporaryDirectory() as tmp:
        db = _learnings_db(tmp)
        le = _fresh_engine(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO agent_outcomes (agent, query, status, result, traces, created_at) "
            "VALUES ('search', 'q', 'success', 'r', '[{\"outcome\": \"success\"}]', 0)"
        )
        conn.commit()
        conn.close()
        assert le.store_outcome_lesson(1, f"Dùng agent_search khi hỏi giá {EMOJI}", "search")
        row = _fetchone(le, "SELECT content FROM learnings")
        assert EMOJI not in row["content"], row["content"]


def test_store_routing_correction_strips_emoji_from_payload():
    with tempfile.TemporaryDirectory() as tmp:
        db = _learnings_db(tmp)
        le = _fresh_engine(db)
        conn = sqlite3.connect(db)
        conn.execute(
            "INSERT INTO agent_outcomes (agent, query, status, result, traces, created_at) "
            "VALUES ('search', ?, 'success', '', '[]', ?)",
            (f"tìm giá {EMOJI}", time.time()),
        )
        conn.commit()
        conn.close()
        assert le.store_routing_correction(f"phải dùng general {EMOJI}", f"evidence {EMOJI}", "general")
        row = _fetchone(le, "SELECT content FROM learnings WHERE type='routing_correction'")
        assert EMOJI not in row["content"], row["content"]


def test_store_validated_workflow_strips_emoji_from_intent_and_samples():
    import asyncio

    with tempfile.TemporaryDirectory() as tmp:
        db = _learnings_db(tmp)
        le = _fresh_engine(db)
        conn = sqlite3.connect(db)
        traces = json.dumps([{"action_name": "check_project", "outcome": "success", "args": {}}])
        conn.execute(
            "INSERT INTO agent_outcomes (agent, query, status, result, traces, created_at) "
            "VALUES ('project', ?, 'success', 'ok', ?, ?)",
            (f"kiểm tra dự án {EMOJI}", traces, time.time()),
        )
        conn.commit()
        conn.close()

        async def fake_llm(**kwargs):
            content = '{"intent": "kiểm tra dự án ' + EMOJI + '", "agent": "project", "tools": ["check_project"]}'
            msg = types.SimpleNamespace(content=content)
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)])

        import engine.server.llm_server as llm_server

        saved_llm = llm_server.call_llm
        saved_dir = learning_mod.WORKFLOWS_WIKI_DIR
        llm_server.call_llm = fake_llm
        learning_mod.WORKFLOWS_WIKI_DIR = Path(tmp) / "Workflows"
        try:
            result = asyncio.run(le.store_validated_workflow(1))
        finally:
            llm_server.call_llm = saved_llm
            learning_mod.WORKFLOWS_WIKI_DIR = saved_dir

        assert result is not None
        row = _fetchone(le, "SELECT intent, sample_queries FROM validated_workflows")
        assert EMOJI not in row["intent"], row["intent"]
        assert EMOJI not in row["sample_queries"], row["sample_queries"]
        wiki_text = (Path(tmp) / "Workflows" / "project.md").read_text(encoding="utf-8")
        assert EMOJI not in wiki_text, wiki_text


if __name__ == "__main__":
    test_store_learning_strips_emoji()
    test_store_outcome_lesson_strips_emoji()
    test_store_routing_correction_strips_emoji_from_payload()
    test_store_validated_workflow_strips_emoji_from_intent_and_samples()
    print("ok")
