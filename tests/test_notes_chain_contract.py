"""dispatcher relies on note_engine saving the last assistant message for a
"lưu lại kết quả: ..." request. Lock that contract (fake engine, nothing written).
Run: python tests/test_notes_chain_contract.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.orchestrator import dispatcher
from engine.tools import note_engine


class _FakeNotes:
    def __init__(self):
        self.saved = []

    def save_note(self, content, title="", tags=""):
        self.saved.append(content)
        return "slug"


def _save(query, history):
    fake = _FakeNotes()
    orig = note_engine.get_note_engine
    note_engine.get_note_engine = lambda: fake
    try:
        asyncio.run(note_engine.execute_note_action(arguments={}, conversation_history=history, user_text=query))
    finally:
        note_engine.get_note_engine = orig
    return fake.saved


def test_previous_report_is_what_gets_saved_not_the_subquery():
    prior = dispatcher._prior_report([{"status": "success", "result": "Có 3 thư mới\n### Kết quả: Google, Nebius"}])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": prior}]
    saved = _save(dispatcher._NOTES_SAVE_PREFIX + "ghi note nội dung email", history)
    assert saved == [prior], saved
    assert "Nebius" in saved[0] and "nội dung email" not in saved[0]


def test_without_the_prefix_the_literal_subquery_would_be_saved():
    """documents why the prefix exists"""
    saved = _save("ghi note nội dung email", [{"role": "assistant", "content": "Có 3 thư mới"}])
    assert saved and "Có 3 thư mới" not in saved[0], saved


if __name__ == "__main__":
    test_previous_report_is_what_gets_saved_not_the_subquery()
    test_without_the_prefix_the_literal_subquery_would_be_saved()
    print("OK: notes chain contract tests passed")
