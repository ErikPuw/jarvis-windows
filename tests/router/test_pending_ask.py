import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import engine.core.memory as memory


def _fresh(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "jarvis.db"
    monkeypatch.setattr(memory, "DB_PATH", tmp)
    memory.init_db()
    memory.init_db()  # migration idempotent
    return tmp


def test_pending_ask_only_for_the_turn_right_after_the_question(monkeypatch):
    _fresh(monkeypatch)
    memory.save_message("user", "tôi lười mở notepad quá")
    memory.save_message("assistant", "Ngài có muốn tôi mở Notepad không?", ask_user="Ngài có muốn tôi mở Notepad không?")
    memory.save_message("user", "ừ")
    assert memory.get_pending_ask() == "Ngài có muốn tôi mở Notepad không?"
    memory.save_message("assistant", "Đã mở.")
    memory.save_message("user", "ok")
    assert memory.get_pending_ask() == ""  # đã có lượt khác chen vào


def test_content_stays_clean_and_old_rows_default_empty(monkeypatch):
    tmp = _fresh(monkeypatch)
    memory.save_message("assistant", "Chào ngài.")
    memory.save_message("user", "ừ")
    assert memory.get_pending_ask() == ""
    import sqlite3
    row = sqlite3.connect(tmp).execute("SELECT content, ask_user FROM messages WHERE role='assistant'").fetchone()
    assert row == ("Chào ngài.", "")


def test_second_consecutive_ask_reply_is_not_skipped_as_duplicate(monkeypatch):
    # I2: save_message used to skip a message equal to the last row OF THE SAME
    # ROLE, so a second "ừ" (with an assistant turn in between) never got stored
    # and get_pending_ask() then saw [assistant, ...] instead of [user, assistant].
    _fresh(monkeypatch)
    memory.save_message("assistant", "Ngài muốn làm gì?")
    memory.save_message("user", "ừ")
    memory.save_message(
        "assistant", "Ngài có muốn tôi mở Notepad không?",
        ask_user="Ngài có muốn tôi mở Notepad không?",
    )
    memory.save_message("user", "ừ")
    assert memory.get_pending_ask() == "Ngài có muốn tôi mở Notepad không?"


def test_exact_immediate_duplicate_is_still_skipped(monkeypatch):
    _fresh(monkeypatch)
    first_id = memory.save_message("user", "ừ")
    second_id = memory.save_message("user", "ừ")
    assert first_id == second_id


def test_pending_ask_expires_after_max_age(monkeypatch):
    tmp = _fresh(monkeypatch)
    memory.save_message(
        "assistant", "Ngài có muốn tôi mở Notepad không?",
        ask_user="Ngài có muốn tôi mở Notepad không?",
    )
    memory.save_message("user", "ừ")
    import sqlite3, time
    conn = sqlite3.connect(tmp)
    conn.execute(
        "UPDATE messages SET created_at=? WHERE role='assistant'",
        (time.time() - 11 * 60,),
    )
    conn.commit()
    conn.close()
    assert memory.get_pending_ask() == ""


def test_action_run_persisted_with_ask_user(monkeypatch):
    """save_message accepts action_run param; get_pending_offer() returns (ask, action_run) tuple."""
    _fresh(monkeypatch)
    memory.save_message("user", "tôi lười mở notepad quá")
    memory.save_message(
        "assistant", "Ngài có muốn tôi mở Notepad không?",
        ask_user="Ngài có muốn tôi mở Notepad không?",
        action_run="open_app"
    )
    memory.save_message("user", "ừ")
    ask, action = memory.get_pending_offer()
    assert ask == "Ngài có muốn tôi mở Notepad không?"
    assert action == "open_app"
    # get_pending_ask() returns just the ask part
    assert memory.get_pending_ask() == "Ngài có muốn tôi mở Notepad không?"


def test_action_run_only_when_ask_present(monkeypatch):
    """action_run returned only if ask_user is also present."""
    _fresh(monkeypatch)
    memory.save_message("assistant", "Chào ngài.", action_run="some_tool")
    memory.save_message("user", "ừ")
    ask, action = memory.get_pending_offer()
    assert ask == ""
    assert action == ""


def test_action_run_cleared_on_extra_turn(monkeypatch):
    """action_run cleared when another turn intervenes."""
    _fresh(monkeypatch)
    memory.save_message(
        "assistant", "Ngài có muốn tôi mở Notepad không?",
        ask_user="Ngài có muốn tôi mở Notepad không?",
        action_run="open_app"
    )
    memory.save_message("user", "ừ")
    memory.save_message("assistant", "Đã mở.")
    memory.save_message("user", "ok")
    ask, action = memory.get_pending_offer()
    assert ask == ""
    assert action == ""


def test_init_db_idempotent_with_action_run(monkeypatch):
    """init_db twice should not error and should create action_run column."""
    tmp = _fresh(monkeypatch)
    import sqlite3
    conn = sqlite3.connect(tmp)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)").fetchall()}
    assert "action_run" in cols, f"action_run column missing; found: {cols}"
    conn.close()
