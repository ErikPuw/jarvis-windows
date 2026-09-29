"""Regression test: agent_office.py must decline like agent_rag.py does when
run without a real attachment_context, instead of proceeding into
handle_user_intent_with_tools purely on wording ("file Word đính kèm") with no
structural evidence of an attachment. Run: python tests/test_agent_office_guard.py
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.agents import agent_office


def test_office_declines_without_attachment_context():
    async def scenario():
        return await agent_office.run_office_agent(
            user_text="sửa nội dung file Word đính kèm này",
            conversation_history=[],
            ws=SimpleNamespace(),
            attachment_context=None,
        )

    result = asyncio.run(scenario())
    assert "đính kèm" in result.lower(), result
    assert "office" in result.lower(), result


def test_office_proceeds_with_a_real_attachment_context(monkeypatch):
    """Sanity check the guard doesn't block the legitimate case."""
    async def fake_handle_user_intent_with_tools(**kwargs):
        return "OK ran"

    def fake_get_agent_context_and_tools(tool_names):
        return []

    import engine.core.actions as actions_mod
    monkeypatch.setattr(actions_mod, "handle_user_intent_with_tools", fake_handle_user_intent_with_tools)
    monkeypatch.setattr(actions_mod, "get_agent_context_and_tools", fake_get_agent_context_and_tools)

    async def scenario():
        return await agent_office.run_office_agent(
            user_text="sửa nội dung file Word đính kèm này",
            conversation_history=[],
            ws=SimpleNamespace(),
            attachment_context=SimpleNamespace(filename="report.docx"),
        )

    assert asyncio.run(scenario()) == "OK ran"


if __name__ == "__main__":
    test_office_declines_without_attachment_context()
    print("OK: agent_office guard tests passed (real-attachment case needs monkeypatch fixture, run via pytest)")
