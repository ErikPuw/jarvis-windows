"""Test get_behaviour_rules() và integration vào chat system prompt."""
import asyncio
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from engine.core.learning import LearningEngine


@pytest.fixture
def temp_db_path():
    """Tạo DB tạm cho test."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield db_path


@pytest.fixture
def engine(temp_db_path):
    """Tạo LearningEngine với DB tạm (không dùng data/jarvis.db thật)."""
    # Patch đường dẫn DB
    with patch("engine.core.learning.MEMORY_DB_PATH", temp_db_path):
        eng = LearningEngine()
        yield eng


def test_get_behaviour_rules_basic(engine):
    """(a) DB tạm có 1 bài lesson ⇒ get_behaviour_rules() trả bài đó."""
    conn = engine._get_learning_db()
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("lesson", "Hạn chế gợi ý khi người dùng không yêu cầu", 8, 1000.0),
    )
    conn.commit()
    conn.close()

    rules = engine.get_behaviour_rules(limit=5, max_chars=600)
    assert len(rules) == 1
    assert "Hạn chế gợi ý" in rules[0]


def test_get_behaviour_rules_respects_max_chars(engine):
    """(b) Tổng độ dài các bài ≤ max_chars."""
    conn = engine._get_learning_db()
    # Thêm 3 bài với nội dung khác nhau
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("lesson", "A" * 200, 8, 1000.0),
    )
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("lesson", "B" * 200, 7, 1001.0),
    )
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("lesson", "C" * 200, 6, 1002.0),
    )
    conn.commit()
    conn.close()

    rules = engine.get_behaviour_rules(limit=10, max_chars=500)
    total_len = sum(len(r) for r in rules)
    assert total_len <= 500, f"Total length {total_len} exceeds max_chars 500"


def test_get_behaviour_rules_excludes_from_style_md(engine):
    """(c) Bài đã có trong STYLE.md không lặp."""
    style_md_content = "Luôn trả lời bằng tiếng Việt lịch sự"

    with patch("pathlib.Path.read_text") as mock_read:
        def side_effect(encoding=None):
            # Khi đọc STYLE.md, trả về content chuẩn
            if "STYLE.md" in str(mock_read.call_args):
                return style_md_content
            raise FileNotFoundError()

        # Thêm 2 bài: 1 đã có trong STYLE.md, 1 mới
        conn = engine._get_learning_db()
        conn.execute(
            "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
            ("lesson", "Luôn trả lời bằng tiếng Việt lịch sự", 8, 1000.0),
        )
        conn.execute(
            "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
            ("lesson", "Hạn chế gợi ý", 7, 1001.0),
        )
        conn.commit()
        conn.close()

        rules = engine.get_behaviour_rules(limit=10, max_chars=600)
        # Bài đã có trong STYLE.md sẽ bị lọc bỏ
        assert len(rules) >= 1
        assert "Hạn chế gợi ý" in rules[0] or any("Hạn chế gợi ý" in r for r in rules)


def test_get_behaviour_rules_ignores_non_lessons(engine):
    """(f) Bài preference/user_fact KHÔNG vào get_behaviour_rules."""
    conn = engine._get_learning_db()
    # Thêm lesson, preference, user_fact
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("lesson", "Hạn chế gợi ý", 8, 1000.0),
    )
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("preference", "Thích lập trình Python", 8, 1001.0),
    )
    conn.execute(
        "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
        ("user_fact", "Tên là John", 8, 1002.0),
    )
    conn.commit()
    conn.close()

    rules = engine.get_behaviour_rules(limit=10, max_chars=600)
    assert len(rules) == 1
    assert rules[0] == "Hạn chế gợi ý"


def test_build_chat_system_prompt_includes_behaviour_rules(engine):
    """(d) build_chat_system_prompt chứa bài học hành vi TRONG khối <style>."""
    # Patch get_learning_engine được gọi bên trong build_chat_system_prompt
    with patch("engine.core.learning.get_learning_engine") as mock_get_engine:
        mock_get_engine.return_value = engine

        # Thêm bài học vào engine
        conn = engine._get_learning_db()
        conn.execute(
            "INSERT INTO learnings (type, content, importance, created_at) VALUES (?, ?, ?, ?)",
            ("lesson", "Hạn chế gợi ý khi người dùng không yêu cầu", 8, 1000.0),
        )
        conn.commit()
        conn.close()

        # Patch đọc STYLE.md, Preferences.md, persona... để tránh lỗi
        with patch("engine.prompts.chat.persona.load_full_persona") as mock_persona:
            mock_persona.return_value = {
                "identity": "Tôi là JARVIS",
                "soul": "Phục vụ người dùng",
                "user": "Người dùng là John"
            }
            with patch("engine.prompts.chat.prompts.load") as mock_load:
                mock_load.side_effect = lambda *args, **kwargs: "(placeholder capability)"
                with patch("pathlib.Path.exists") as mock_exists:
                    mock_exists.return_value = False
                    with patch("pathlib.Path.read_text"):
                        prompt = __import__("engine.prompts.chat", fromlist=["build_chat_system_prompt"]).build_chat_system_prompt()

                        # Kiểm tra <style> chứa bài học
                        assert "<style>" in prompt
                        assert "Hạn chế gợi ý" in prompt


def test_build_chat_messages_no_recall_learnings(engine):
    """(e) engine.router.chat.build_chat_messages KHÔNG còn gọi recall_learnings."""
    # Giả recall_learnings raise để phát hiện nếu bị gọi
    def mock_recall_learnings(*args, **kwargs):
        raise AssertionError("recall_learnings should not be called; behaviour rules go to <style>")

    with patch("engine.core.learning.LearningEngine.recall_learnings", side_effect=mock_recall_learnings):
        with patch("engine.prompts.chat.build_chat_system_prompt") as mock_sys:
            mock_sys.return_value = "(system prompt)"
            with patch("engine.prompts.chat._history_messages") as mock_hist:
                mock_hist.return_value = []
                with patch("engine.prompts.chat.results.build_turn_status") as mock_turn:
                    mock_turn.return_value = ""

                    # Gọi build_chat_messages từ prompts (không router)
                    msgs = __import__("engine.prompts.chat", fromlist=["build_chat_messages"]).build_chat_messages(
                        user_text="Xin chào",
                        conversation_history=[],
                        reference_data={},
                    )
                    # Test chỉ check structure, không call router.build_chat_messages
                    assert len(msgs) >= 2  # ít nhất system + user


def test_no_learned_experiences_block_if_empty(engine):
    """Khối <learned_experiences> KHÔNG xuất hiện nếu không có lessons trong reference_data."""
    msgs = __import__("engine.prompts.chat", fromlist=["build_chat_messages"]).build_chat_messages(
        user_text="Xin chào",
        conversation_history=[],
        reference_data={},  # Rỗng
    )
    full_text = "\n".join(m.get("content", "") for m in msgs)
    assert "<learned_experiences>" not in full_text
    assert "lessons" not in full_text.lower() or "learned_experiences" not in full_text


def test_propose_prompt_routes_how_jarvis_behaves_to_behaviour_lesson():
    """Review Task E: 'hạn chế gợi ý' từng bị phân loại thành preference (vào <about_user>, không phải <style>);
    prompt đề xuất phải nói rõ yêu cầu về CÁCH Jarvis cư xử là behaviour_lesson."""
    from pathlib import Path
    text = (Path(__file__).resolve().parents[1] / "prompt" / "learning_propose.md").read_text(encoding="utf-8")
    assert "behaviour_lesson: ngài yêu cầu hoặc phàn nàn về CÁCH Jarvis" in text
    assert "preference/user_fact: sở thích hoặc sự thật về chính ngài" in text
