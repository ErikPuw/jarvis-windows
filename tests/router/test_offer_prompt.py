"""Prompt chat: quy tắc đề nghị nằm trong khối <offer_protocol> riêng (spec §11, user 2026-09-25)."""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from engine.prompts.chat import build_chat_system_prompt
from engine.prompts.catalog import tool_list_text


def _block(name):
    m = re.search(rf"<{name}>\n(.*?)\n</{name}>", build_chat_system_prompt(), re.S)
    assert m, f"thiếu khối <{name}>"
    return m.group(1)


def test_capabilities_only_lists_what_the_system_can_do():
    caps = _block("capabilities")
    assert "<ask_user>" not in caps and "<action_run>" not in caps


def test_offer_protocol_has_format_and_tool_whitelist():
    p = _block("offer_protocol")
    assert tool_list_text() in p
    # User 2026-09-25: thẻ chỉ bọc phần việc bên trong câu hỏi, không bọc cả câu
    assert "Ngài có muốn tôi <ask_user>[việc + đối tượng]</ask_user> không?<action_run>[tên công cụ]</action_run>" in p
    assert "MỘT lần" in p  # câu hỏi xin phép không lặp


def test_offer_protocol_keeps_original_app_names():
    p = _block("offer_protocol")
    assert "tên gốc" in p and "Không dịch" in p and "ngoặc" in p


def test_offer_protocol_offers_the_same_task_when_user_is_lazy():
    assert "đề nghị làm chính việc đó thay ngài" in _block("offer_protocol")


def test_soul_rules_do_not_push_offers_and_name_only_real_blocks():
    """2026-09-27 (user: chat thường gợi ý ầm đùng): luật cứng nhắc 'đề nghị theo <offer_protocol>' 2 lần làm
    model coi đề nghị là việc nên làm; <offer_protocol> tự đủ. Luật chỉ được nhắc khối có thật trong prompt."""
    soul = _block("soul_rules")
    assert "<offer_protocol>" not in soul and "đề nghị" not in soul
    for ghost in ("<memory_context>", "<learned_experiences>", "<user_preferences>", "<mcp_data>", "<hook_context>"):
        assert ghost not in soul, ghost
    assert "<style_rules>" not in _block("identity")


def test_classifier_keeps_original_app_names():
    from engine.orchestrator.classifier import _SYSTEM
    assert "tên gốc" in _SYSTEM and "ngoặc" in _SYSTEM
