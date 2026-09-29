# -*- coding: utf-8 -*-
"""Tests for scripts/cleanup_learning_2026_09.py"""

import os
import shutil
import sqlite3
from pathlib import Path
import pytest

from scripts.cleanup_learning_2026_09 import (
    find_junk_learnings,
    find_duplicate_memories,
    find_translated_app_failed_outcomes,
    find_bak_files,
    clean_style_rules,
    run_cleanup,
)


@pytest.fixture
def temp_env(tmp_path):
    """Setup a sandboxed test environment with mock DB and folders."""
    db_path = tmp_path / "jarvis.db"
    wiki_sys_dir = tmp_path / "wiki" / "System"
    wiki_sys_dir.mkdir(parents=True, exist_ok=True)
    style_dir = tmp_path / "skills" / "self_evolution"
    style_dir.mkdir(parents=True, exist_ok=True)
    style_file = style_dir / "STYLE.md"
    backup_dir = tmp_path / "backups"

    # Setup DB
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            semantic_key TEXT,
            content TEXT,
            context TEXT,
            confidence REAL DEFAULT 1.0,
            evidence TEXT,
            created_at REAL DEFAULT 0,
            updated_at REAL DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT,
            content TEXT,
            source TEXT,
            importance INTEGER DEFAULT 5,
            created_at REAL DEFAULT 0,
            last_accessed REAL DEFAULT 0,
            access_count INTEGER DEFAULT 0
        )"""
    )
    conn.execute(
        """CREATE TABLE agent_outcomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent TEXT,
            query TEXT,
            status TEXT,
            result TEXT,
            traces TEXT,
            created_at REAL DEFAULT 0
        )"""
    )

    # Insert test data
    # Learnings: 2 good, 4 junk
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (1, 'preference', 'morning_coffee', 'Uống cà phê sáng')"
    )
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (2, 'preference', 'fav_food', 'Thích cơm tấm sườn')"
    )
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (3, 'user_fact', 'lazy_notepad', 'lười mở Notepad để ghi chép')"
    )
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (4, 'user_fact', 'history_1945', 'Lịch sử Việt Nam 1945 có nhiều biến cố')"
    )
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (5, 'user_fact', 'proj_done', 'USER đã hoàn thành dự án lớn')"
    )
    conn.execute(
        "INSERT INTO learnings (id, type, semantic_key, content) VALUES (6, 'lesson', 'fatigue', 'Hơi mệt mỏi vì phải kiểm tra hành vi liên tục')"
    )

    # Memories: 1 unique, 2 duplicates of learnings, 1 junk
    conn.execute(
        "INSERT INTO memories (id, type, content) VALUES (10, 'fact', 'Tên người dùng là Erik')"
    )
    conn.execute(
        "INSERT INTO memories (id, type, content) VALUES (11, 'preference', 'Thích uống cà phê sáng')"
    )
    conn.execute(
        "INSERT INTO memories (id, type, content) VALUES (12, 'preference', 'Thích cơm tấm sườn')"
    )
    conn.execute(
        "INSERT INTO memories (id, type, content) VALUES (13, 'fact', 'USER đã hoàn thành dự án lớn')"
    )

    # Agent outcomes: 1 success, 2 failed with translated names
    conn.execute(
        "INSERT INTO agent_outcomes (id, agent, query, status, result) VALUES (101, 'desktop', 'mở notepad', 'success', 'OK')"
    )
    conn.execute(
        "INSERT INTO agent_outcomes (id, agent, query, status, result) VALUES (102, 'desktop', 'mở ứng dụng Ghi chú (Notepad)', 'failed', 'Thất bại')"
    )
    conn.execute(
        "INSERT INTO agent_outcomes (id, agent, query, status, result) VALUES (103, 'desktop', 'mở lại ứng dụng Ghi chú', 'failed', 'Lỗi')"
    )
    conn.commit()
    conn.close()

    # Style file with bad rule
    style_content = (
        "- Luôn thân thiện và vui vẻ.\n"
        "- Có thể hỏi lại người dùng nếu cần làm rõ thêm chi tiết.\n"
        "- Trả lời ngắn gọn."
    )
    style_file.write_text(style_content, encoding="utf-8")

    # Bak files
    (style_dir / "STYLE.md.bak").write_text("old", encoding="utf-8")
    (wiki_sys_dir / "Evolution.md.bak").write_text("old", encoding="utf-8")

    return {
        "db_path": db_path,
        "wiki_sys_dir": wiki_sys_dir,
        "style_dir": style_dir,
        "style_file": style_file,
        "backup_dir": backup_dir,
    }


def test_dry_run_does_not_modify_anything(temp_env):
    """Dry-run mode should identify all junk without deleting or creating backups."""
    report = run_cleanup(
        db_path=temp_env["db_path"],
        wiki_sys_dir=temp_env["wiki_sys_dir"],
        style_dir=temp_env["style_dir"],
        backup_dir=temp_env["backup_dir"],
        apply=False,
    )

    # Verify report identifies items
    assert len(report["junk_learnings"]) == 4  # ids: 3, 4, 5, 6
    assert len(report["duplicate_memories"]) >= 2  # ids: 11, 12, 13
    assert len(report["failed_outcomes"]) == 2  # ids: 102, 103
    assert len(report["bak_files"]) == 2
    assert report["style_rules_removed"] == 1

    # Verify DB unchanged
    conn = sqlite3.connect(temp_env["db_path"])
    assert conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0] == 4
    assert conn.execute("SELECT COUNT(*) FROM agent_outcomes").fetchone()[0] == 3
    conn.close()

    # Verify backup dir not created
    assert not temp_env["backup_dir"].exists()

    # Verify .bak files still exist
    assert (temp_env["style_dir"] / "STYLE.md.bak").exists()
    assert (temp_env["wiki_sys_dir"] / "Evolution.md.bak").exists()


def test_apply_cleanup_creates_backup_and_removes_targets(temp_env):
    """When apply=True, backup must exist and targets must be removed."""
    report = run_cleanup(
        db_path=temp_env["db_path"],
        wiki_sys_dir=temp_env["wiki_sys_dir"],
        style_dir=temp_env["style_dir"],
        backup_dir=temp_env["backup_dir"],
        apply=True,
    )

    # Verify backup exists
    assert temp_env["backup_dir"].exists()
    backups = list(temp_env["backup_dir"].iterdir())
    assert len(backups) == 1
    run_backup = backups[0]
    assert (run_backup / "jarvis.db").exists()

    # Verify DB cleaned
    conn = sqlite3.connect(temp_env["db_path"])
    learnings = conn.execute("SELECT id, content FROM learnings").fetchall()
    assert len(learnings) == 2
    assert all(r[0] in (1, 2) for r in learnings)

    memories = conn.execute("SELECT id FROM memories").fetchall()
    assert len(memories) == 1  # Only id 10 ('Erik') remains
    assert memories[0][0] == 10

    outcomes = conn.execute("SELECT id FROM agent_outcomes").fetchall()
    assert len(outcomes) == 1
    assert outcomes[0][0] == 101
    conn.close()

    # Verify style file updated
    style_content = temp_env["style_file"].read_text(encoding="utf-8")
    assert "hỏi lại người dùng nếu cần" not in style_content
    assert "Luôn thân thiện" in style_content
    assert "Trả lời ngắn gọn" in style_content

    # Verify bak files deleted
    assert not (temp_env["style_dir"] / "STYLE.md.bak").exists()
    assert not (temp_env["wiki_sys_dir"] / "Evolution.md.bak").exists()


TEST_JUNK_EVOLUTION = (
    "# Evolution\n\n# Proposed Routing Notes\n"
    "- [ĐỀ XUẤT] Tài liệu văn bản nên chuyển cho office agent (Bằng chứng: tài liệu này xử lý thế nào)\n"
    "- [ĐỀ XUẤT] Đề xuất thật của Evolution\n"
)


def test_apply_backs_up_style_dir_before_editing(temp_env):
    run_cleanup(
        db_path=temp_env["db_path"], wiki_sys_dir=temp_env["wiki_sys_dir"],
        style_dir=temp_env["style_dir"], backup_dir=temp_env["backup_dir"], apply=True,
    )
    run_backup = next(temp_env["backup_dir"].iterdir())
    backed_style = run_backup / "self_evolution" / "STYLE.md"
    assert "hỏi lại người dùng nếu cần" in backed_style.read_text(encoding="utf-8")  # bản gốc, trước khi sửa
    assert (run_backup / "self_evolution" / "STYLE.md.bak").exists()


def test_test_junk_line_in_evolution_is_listed_then_removed(temp_env):
    evo = temp_env["wiki_sys_dir"] / "Evolution.md"
    evo.write_text(TEST_JUNK_EVOLUTION, encoding="utf-8")
    report = run_cleanup(
        db_path=temp_env["db_path"], wiki_sys_dir=temp_env["wiki_sys_dir"],
        style_dir=temp_env["style_dir"], backup_dir=temp_env["backup_dir"], apply=False,
    )
    assert report["evolution_test_lines"] == 1
    assert evo.read_text(encoding="utf-8") == TEST_JUNK_EVOLUTION  # dry-run không sửa

    run_cleanup(
        db_path=temp_env["db_path"], wiki_sys_dir=temp_env["wiki_sys_dir"],
        style_dir=temp_env["style_dir"], backup_dir=temp_env["backup_dir"], apply=True,
    )
    text = evo.read_text(encoding="utf-8")
    assert "office agent" not in text
    assert "Đề xuất thật của Evolution" in text
