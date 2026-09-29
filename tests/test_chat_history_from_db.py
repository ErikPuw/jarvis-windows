"""Lịch sử chat đọc từ DB phải giữ ask_user/action_run để dựng lại thẻ (spec 2026-09-25 mục 3)."""
import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.core.mcp_context as mcp_context
import engine.core.memory as memory
from engine.prompts import chat as chat_prompts
from engine.router import chat
from engine.router.types import TurnContext


def _fresh(monkeypatch):
    tmp = Path(tempfile.mkdtemp()) / "jarvis.db"
    monkeypatch.setattr(memory, "DB_PATH", tmp)
    memory.init_db()


def _offer_turns():
    memory.save_message("user", "tôi lười mở notepad quá")
    memory.save_message(
        "assistant", "Ngài có muốn tôi mở Notepad không?",
        ask_user="mở Notepad", action_run="open_app",
    )
    memory.save_message("user", "ừ")


def test_routing_history_keeps_offer_fields(monkeypatch):
    _fresh(monkeypatch)
    _offer_turns()
    hist = memory.build_unified_routing_history("ừ", [], 12)
    assistant = [h for h in hist if h["role"] == "assistant"][0]
    assert assistant["ask_user"] == "mở Notepad"
    assert assistant["action_run"] == "open_app"


def test_repeated_user_reply_is_not_dropped(monkeypatch):
    _fresh(monkeypatch)
    _offer_turns()
    memory.save_message("assistant", "Đã mở Notepad.")
    memory.save_message("user", "ừ")  # "ừ" thứ hai = lượt hiện tại
    hist = memory.build_unified_routing_history("ừ", [], 12)
    assert [h["role"] for h in hist] == ["user", "assistant", "user", "assistant", "user"]
    assert hist[-1]["content"] == "ừ"


def test_chat_messages_do_not_rebuild_tags_from_db(monkeypatch):
    """2026-09-27 (user): lịch sử gửi cho model không dựng lại thẻ đề nghị — thẻ chỉ ở cột DB ask_user/action_run.
    Dựng lại làm 'ví dụ mẫu' khiến model đề nghị ở mọi lượt sau (jarvis.log 20:57–21:00)."""
    _fresh(monkeypatch)
    _offer_turns()

    async def fake_mcp(*a, **k):
        return ""

    monkeypatch.setattr(mcp_context, "build_mcp_context", fake_mcp)
    messages, _ = asyncio.run(chat.build_chat_messages("general", "ừ", TurnContext(ws=object(), send_json=None)))
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert "mở Notepad" in assistant["content"]
    assert "<ask_user>" not in assistant["content"] and "<action_run>" not in assistant["content"]
    # Lượt "ừ" hiện tại chỉ xuất hiện một lần, ở cuối
    assert messages[-1] == {"role": "user", "content": "ừ"}
    assert sum(1 for m in messages if m["role"] == "user" and m["content"] == "ừ") == 1


def test_earlier_identical_user_turn_kept_in_chat_history():
    history = [
        {"role": "user", "content": "ừ"},
        {"role": "assistant", "content": "Đã mở."},
        {"role": "user", "content": "ừ"},
    ]
    msgs = chat_prompts.build_chat_messages("ừ", conversation_history=history)
    users = [m for m in msgs if m["role"] == "user"]
    assert len(users) == 2  # "ừ" cũ giữ lại, "ừ" hiện tại chỉ một lần ở cuối


def test_reference_has_no_agent_outcomes(monkeypatch):
    """2026-09-27: không nạp kết quả agent gần nhất vào chat (mồi model đề nghị lại tool đó)."""
    _fresh(monkeypatch)
    memory.save_message("user", "chào")

    class FakeEngine:
        def recall_learnings(self, text, k):
            return []

        def get_recent_agent_outcomes(self, limit=3):
            return [
                {"agent": "desktop", "query": "mở Notepad", "status": "success"},
                {"agent": "desktop", "query": "mở Ghi chú (Notepad)", "status": "failed"},
            ]

    import engine.core.learning as learning
    monkeypatch.setattr(learning, "get_learning_engine", lambda: FakeEngine())

    async def fake_mcp(*a, **k):
        return ""

    monkeypatch.setattr(mcp_context, "build_mcp_context", fake_mcp)
    messages, _ = asyncio.run(chat.build_chat_messages("general", "chào", TurnContext(ws=object(), send_json=None)))
    all_text = " ".join(m["content"] for m in messages)
    assert "mở Notepad" not in all_text and "<agent_results>" not in all_text
    assert "Ghi chú (Notepad)" not in all_text
    assert "VERIFIED" not in all_text
