"""A tool that reports "Thất bại" must be traced as failed. Run: python tests/test_tool_failure_marker.py"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core import actions
from engine.core.trace_logger import TraceLogger


def _outcome_for(result):
    seen = []
    orig_inner, orig_log = actions._execute_tool_inner, TraceLogger.log_trace

    async def fake_inner(*a, **k):
        return result

    actions._execute_tool_inner = fake_inner
    TraceLogger.log_trace = staticmethod(lambda **kw: seen.append(kw["outcome"]))
    try:
        asyncio.run(actions.execute_tool("open_app", {"app_name": "x"}))
    finally:
        actions._execute_tool_inner, TraceLogger.log_trace = orig_inner, orig_log
    return seen[0]


def test_failure_text_is_traced_as_failed():
    assert _outcome_for("Mở ứng dụng 'thử lại giọng đọc tts': Thất bại") == "failed"
    assert _outcome_for("Đóng ứng dụng 'x': Thất bại.") == "failed"


def test_success_text_stays_success():
    assert _outcome_for("Mở ứng dụng 'notepad': Thành công") == "success"


if __name__ == "__main__":
    test_failure_text_is_traced_as_failed()
    test_success_text_stays_success()
    print("OK: tool failure marker tests passed")
