"""Learning tự phản tư (spec 2026-09-25 §4). DB/wiki cô lập trong thư mục tạm — không đụng dữ liệu thật."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine.core.memory as memory
from engine.core import learning
from engine.core.evolution import _bad_rule


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(learning, "MEMORY_DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(learning, "LEARNING_HUB_WIKI_PATH", tmp_path / "hub.md")
    for name in ("PREFERENCES_WIKI_PATH", "LESSONS_WIKI_PATH"):
        monkeypatch.setattr(learning, name, tmp_path / f"{name}.md")
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "jarvis.db")
    monkeypatch.setattr(learning.LearningEngine, "_embed_text", staticmethod(lambda content: None))
    memory.init_db()
    le = learning.LearningEngine()
    le._init_db()
    return le


def _fake_llm(monkeypatch, responses: list[dict], seen: list):
    import engine.server.llm_server as ls

    async def fake(messages, **kwargs):
        seen.append(messages[0]["content"])
        payload = responses.pop(0) if responses else {"proposals": []}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))])

    monkeypatch.setattr(ls, "call_llm", fake)


def _ids(le):
    conn = le._get_learning_db()
    rows = conn.execute("SELECT id, content FROM learnings").fetchall()
    conn.close()
    return {r["id"]: r["content"] for r in rows}


def test_forbidden_style_rules_blocked():
    sources = ["người dùng thích emoji", "hướng dẫn phong cách"]
    assert _bad_rule("- Khi người dùng cần, hãy hỏi xem có muốn mở app không", sources, routing=False) is not None
    assert _bad_rule("- Xin phép người dùng trước khi gọi công cụ", sources, routing=False) is not None
    assert _bad_rule("- Dùng agent_desktop để xử lý yêu cầu", sources, routing=False) is not None
    assert _bad_rule("- Bọc lệnh trong thẻ <ask_user>", sources, routing=False) is not None


def test_evidence_verbatim_guard(engine):
    user_msg = "tôi thích giao diện màu tối và đơn giản"
    ok = {"kind": "preference", "key": "dark_mode", "content": "x", "evidence": "thích giao diện màu tối"}
    fake = {"kind": "preference", "key": "dark_mode", "content": "x", "evidence": "tôi luôn luôn dùng màn hình đen"}
    assert engine._validate_proposal_evidence(ok, user_msg) is True
    assert engine._validate_proposal_evidence(fake, user_msg) is False


def test_forbidden_topics_block_behaviour_rules(engine):
    for content in (
        "Luôn hỏi xin phép người dùng trước khi làm",
        "Dùng công cụ open_app để mở phần mềm",
        "Chuyển việc này cho agent desktop",
        "Viết thẻ <ask_user> ở cuối câu",
    ):
        assert engine._is_forbidden_topic(content, "behaviour_lesson") is True
    assert engine._is_forbidden_topic("Trả lời ngắn gọn, lịch sự, có emoji", "behaviour_lesson") is False


def test_forbidden_topics_do_not_block_user_facts(engine):
    # Sự thật về ngài có thể nhắc tới "agent" mà không phải luật hành vi
    assert engine._is_forbidden_topic("Ngài đang làm dự án agent AI tên Jarvis", "user_fact") is False
    # "hỏi" nằm trong "khỏi" không được tính
    assert engine._is_forbidden_topic("Ngài muốn khỏi phải nhắc lại tên mình", "preference") is False


def test_routing_note_goes_to_evolution_only(engine, tmp_path):
    proposal = {"kind": "routing_note", "key": "route_doc", "content": "Tài liệu nên chuyển cho office", "evidence": "tài liệu"}
    assert engine._handle_routing_note_proposal(proposal) is True
    assert "[ĐỀ XUẤT]" in (tmp_path / "data" / "wiki" / "System" / "Evolution.md").read_text(encoding="utf-8")
    assert _ids(engine) == {}


def test_critique_merge_replace_limited_to_context_item(engine):
    res = engine._apply_critique_decision(
        decision="merge",
        target_item={"id": 999999, "content": "nội dung cũ", "type": "lesson"},
        proposal={"kind": "behaviour_lesson", "key": "test_key", "content": "nội dung mới"},
        merged_content="nội dung đã gộp",
    )
    assert res is False


def test_routing_complaint_does_not_delete_learnings():
    import importlib
    D = importlib.import_module("engine.router.decide")
    assert not hasattr(learning.LearningEngine, "unlearn_last_learning")

    class Fake:
        def unlearn_last_route(self, text):
            return False

    orig = learning.get_learning_engine
    learning.get_learning_engine = lambda: Fake()
    try:
        assert D._unlearn_last_route("sai rồi, tôi chỉ hỏi thôi") is False
    finally:
        learning.get_learning_engine = orig


def test_propose_sees_recent_turns_and_successful_outcomes(engine, monkeypatch):
    memory.save_message("user", "tôi tên là Erik")
    memory.save_message("assistant", "Chào ngài Erik.")
    memory.save_message("user", "mở notepad")
    memory.save_message("assistant", "Đã mở Notepad.")
    engine.record_agent_outcome("desktop", "mở notepad", "success", "ok", [])
    engine.record_agent_outcome("desktop", "mở Ghi chú (Notepad)", "failed", "lỗi", [])
    seen: list = []
    _fake_llm(monkeypatch, [{"proposals": []}], seen)
    asyncio.run(engine.process_conversation_learning("mở notepad", "Đã mở Notepad."))
    assert "tôi tên là Erik" in seen[0]
    assert "mở notepad" in seen[0]
    assert "Ghi chú (Notepad)" not in seen[0]


def test_retract_deletes_item_learned_last_run(engine, monkeypatch):
    memory.save_message("user", "tôi thích trả lời thật ngắn")
    seen: list = []
    _fake_llm(monkeypatch, [
        {"proposals": [{"kind": "preference", "key": "short_answers", "content": "Ngài thích câu trả lời thật ngắn",
                        "evidence": "thích trả lời thật ngắn"}]},
        {"decision": "new"},
    ], seen)
    asyncio.run(engine.process_conversation_learning("tôi thích trả lời thật ngắn", "Vâng."))
    learned_id = next(iter(_ids(engine)))

    memory.save_message("user", "không, tôi đâu có thích ngắn")
    _fake_llm(monkeypatch, [
        {"proposals": [{"kind": "retract", "target_id": learned_id, "evidence": "tôi đâu có thích ngắn"}]},
    ], seen)
    asyncio.run(engine.process_conversation_learning("không, tôi đâu có thích ngắn", "Xin lỗi ngài."))
    assert f"#{learned_id}" in seen[-1]  # lượt đề xuất thấy mục vừa học
    assert _ids(engine) == {}


def test_retract_cannot_touch_items_not_learned_last_run(engine, monkeypatch):
    engine._store_learning("Ngài làm việc ở Hà Nội", "user_fact", "work_city")
    old_id = next(iter(_ids(engine)))
    memory.save_message("user", "sai rồi")
    _fake_llm(monkeypatch, [{"proposals": [{"kind": "retract", "target_id": old_id, "evidence": "sai rồi"}]}], [])
    asyncio.run(engine.process_conversation_learning("sai rồi", "Xin lỗi."))
    assert old_id in _ids(engine)


def test_retract_of_merge_restores_previous_content(engine, monkeypatch):
    engine._store_learning("Ngài thích emoji", "preference", "emoji")
    old_id = next(iter(_ids(engine)))
    memory.save_message("user", "tôi thích emoji và hài hước")
    _fake_llm(monkeypatch, [
        {"proposals": [{"kind": "preference", "key": "emoji", "content": "Ngài thích emoji và hài hước",
                        "evidence": "thích emoji và hài hước"}]},
        {"decision": "merge", "merged_content": "Ngài thích emoji và sự hài hước"},
    ], [])
    asyncio.run(engine.process_conversation_learning("tôi thích emoji và hài hước", "Vâng."))
    assert _ids(engine)[old_id] == "Ngài thích emoji và sự hài hước"

    memory.save_message("user", "không đúng, bỏ cái hài hước đi")
    _fake_llm(monkeypatch, [{"proposals": [{"kind": "retract", "target_id": old_id, "evidence": "bỏ cái hài hước đi"}]}], [])
    asyncio.run(engine.process_conversation_learning("không đúng, bỏ cái hài hước đi", "Vâng."))
    assert _ids(engine)[old_id] == "Ngài thích emoji"
