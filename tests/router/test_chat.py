"""build_chat_messages phải giữ Wikipedia + <answer_policy> cho general_knowledge, không cho general.
Chuyển từ tests/test_general_knowledge_route.py (xoá ở Task 8) sang engine/router/chat.py.
Cập nhật spec 2026-09-25: 5 khối message chuẩn, kiểm tra trực tiếp messages trả về.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import engine.core.mcp_context as mcp_context
import engine.core.memory as memory
import engine.tools.load_hook as load_hook
from engine.router import chat
from engine.router.types import TurnContext


def _patch_common(monkeypatch):
    seen = {"mcp": []}

    async def fake_mcp(query, route=None, flow_tracker=None):
        seen["mcp"].append(route)
        return "WIKI-DATA"

    monkeypatch.setattr(mcp_context, "build_mcp_context", fake_mcp)
    monkeypatch.setattr(memory, "build_unified_routing_history", lambda text, fallback, limit: [])
    return seen


def _build(kind, monkeypatch, ctx=None):
    seen = _patch_common(monkeypatch)
    if ctx is None:
        ctx = TurnContext(ws=object(), send_json=None)
    messages, text = asyncio.run(chat.build_chat_messages(kind, "Napoleon là ai", ctx))
    seen["messages"] = messages
    seen["text"] = text
    seen["all_text"] = " ".join(m.get("content", "") for m in messages)
    return seen


def test_general_knowledge_keeps_wikipedia_and_answer_policy(monkeypatch):
    seen = _build("general_knowledge", monkeypatch)
    assert seen["mcp"] == ["general_knowledge"]
    assert "WIKI-DATA" in seen["all_text"]
    assert "<answer_policy>" in seen["all_text"]


def test_general_gets_no_mcp_and_no_answer_policy(monkeypatch):
    seen = _build("general", monkeypatch)
    assert seen["mcp"] == []
    assert "<answer_policy>" not in seen["all_text"]
    assert "WIKI-DATA" not in seen["all_text"]


def test_general_does_not_inject_recent_agent_results(monkeypatch):
    """2026-09-27: <agent_results> '[email] xem email → thành công' ở MỌI lượt chat làm model đề nghị lại chính
    tool đó ('chat thường cũng check mail'). Lịch sử đã có câu trả lời của agent; không nạp thêm."""
    import engine.core.learning as learning

    class _Engine:
        def recall_learnings(self, text, k):
            return []

        def get_recent_agent_outcomes(self, n):
            return [{"agent": "email", "query": "xem email mã ZX-4471", "status": "success"}]
    monkeypatch.setattr(learning, "get_learning_engine", lambda: _Engine())
    seen = _build("general", monkeypatch)
    assert "<agent_results>" not in seen["all_text"] and "ZX-4471" not in seen["all_text"]


def test_returns_hook_rewritten_text_for_on_response_generate(monkeypatch):
    """server.py cũ dùng CÙNG biến text (sau hook ON_MESSAGE_RECEIVE) cho ON_RESPONSE_GENERATE
    ở bước stream sau đó; build_chat_messages phải trả lại text đó, không phải text gốc."""
    _patch_common(monkeypatch)

    async def fake_fire_async(self, hook_name, **ctx):
        if hook_name == load_hook.HOOKS.ON_MESSAGE_RECEIVE:
            return {"text": "REWRITTEN BY HOOK"}
        return {}
    monkeypatch.setattr(load_hook.HookRegistry, "fire_async", fake_fire_async)

    _, text = asyncio.run(chat.build_chat_messages("general", "Napoleon là ai", TurnContext(ws=object(), send_json=None)))
    assert text == "REWRITTEN BY HOOK"


def test_returns_original_text_when_hook_does_not_rewrite(monkeypatch):
    seen = _build("general", monkeypatch)
    assert seen["text"] == "Napoleon là ai"
    assert seen["messages"][-1] == {"role": "user", "content": "Napoleon là ai"}


def test_tool_status_block_added_when_action_declined(monkeypatch):
    """When ctx.action_declined=True, messages must contain <tool_status> block."""
    ctx = TurnContext(ws=object(), send_json=None)
    ctx.action_declined = True
    seen = _build("general", monkeypatch, ctx=ctx)
    assert "<tool_status>" in seen["all_text"], f"<tool_status> not found in messages: {seen['all_text']}"
    assert "CHƯA được thực hiện" in seen["all_text"], "Expected message about action not done"


def test_plain_chat_turn_says_no_tool_ran(monkeypatch):
    """Lượt chat thường cũng không có công cụ nào chạy: chat từng bịa "đã kiểm tra… hệ thống ổn định"
    (log 2026-09-25 15:16). <tool_status> luôn có, bản "không có công cụ nào chạy", không phải bản từ chối."""
    ctx = TurnContext(ws=object(), send_json=None)
    ctx.action_declined = False
    seen = _build("general", monkeypatch, ctx=ctx)
    assert "<tool_status>" in seen["all_text"]
    assert "không có công cụ nào chạy" in seen["all_text"]
    assert "CHƯA được thực hiện" not in seen["all_text"]


def test_declined_status_forbids_leaning_on_history(monkeypatch):
    """Lịch sử có lần mở thành công không được biến thành "đã mở rồi" ở lượt bị từ chối (probe after-success 10/10)."""
    ctx = TurnContext(ws=object(), send_json=None)
    ctx.action_declined = True
    seen = _build("general", monkeypatch, ctx=ctx)
    assert "lượt trước" in seen["all_text"] and "lịch sử" in seen["all_text"]


def test_tool_status_text_lives_in_prompt_md():
    src = (Path(__file__).resolve().parents[2] / "engine/prompts/results.py").read_text(encoding="utf-8")
    assert "CHƯA được thực hiện" not in src and "không có công cụ nào chạy" not in src
