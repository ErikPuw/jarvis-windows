"""After a tool/agent run, Jarvis reports the result and stops — no "ngài có cần thêm gì
không?" (user decision 2026-09-23). Those trailing questions are what the user then
answers with a bare "ừ", which general chat cannot act on.

Offline part checks the two prompts that used to force the question; the live part
(real LLM, skipped if the server is down) checks what the model actually writes.

Run: python tests/test_tool_answer_no_followup.py
"""
import asyncio
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(Path(__file__).parent.parent / ".env")

from engine.core import actions  # noqa: E402
from engine.orchestrator import synthesizer  # noqa: E402
from engine.prompts import results  # noqa: E402

_ASKS = re.compile(r"hỏi (ngài|người dùng)|cần (gì )?thêm", re.I)


def test_synthesis_prompt_does_not_ask_for_more():
    p = results.build_synthesis_prompt()
    assert not _ASKS.search(p), p
    assert "không hỏi" in p.lower()


def test_tool_summary_prompt_does_not_ask_for_more():
    base = results.build_tool_summary_prompt("general")
    assert not _ASKS.search(base), base
    assert "không hỏi" in base.lower()


def _ends_with_question(text: str) -> bool:
    tail = re.sub(r"(thưa ngài[.!]?|[\s\W_])+$", "", text.strip().lower(), flags=re.I)
    last = re.split(r"(?<=[.!?])\s+", text.strip())[-1]
    return "?" in last or tail.endswith("không")


async def _live():
    from engine.server.llm_server import call_llm
    results = [
        {"agent": "search", "query": "thời tiết Hà Nội", "status": "success",
         "result": "Hà Nội hôm nay 31°C, trời nắng, độ ẩm 70%, chiều tối có thể mưa rào."},
        {"agent": "search", "query": "giá vàng hôm nay", "status": "success",
         "result": "| Loại | Mua | Bán |\n|---|---|---|\n| SJC | 118.0 | 120.0 |"},
    ]
    bad = 0
    for i in range(3):
        text, _ = await synthesizer.combine("thời tiết Hà Nội và giá vàng hôm nay", results)
        q = _ends_with_question(text)
        bad += q
        print(f"[synth run{i+1}] ends_with_question={q} …{' '.join(text.split())[-160:]}")
    for i in range(3):
        resp = await call_llm(messages=[
            {"role": "system", "content": results.build_tool_summary_prompt("general")},
            {"role": "user", "content": "Câu hỏi của người dùng: mở notepad\n\nKết quả công cụ:\n"
                                        "Kết quả công cụ open_app:\nĐã mở Notepad thành công."},
        ], temperature=0.3, thinking=False, stream=False)
        text = resp.choices[0].message.content or ""
        q = _ends_with_question(text)
        bad += q
        print(f"[summary run{i+1}] ends_with_question={q} …{' '.join(text.split())[-160:]}")
    return bad


def main():
    for t in (test_synthesis_prompt_does_not_ask_for_more, test_tool_summary_prompt_does_not_ask_for_more):
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            print("FAIL", t.__name__, "->", str(e)[:160])
    try:
        urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2)
    except Exception:
        print("LLM server không chạy -- bỏ qua phần live.")
        return
    bad = asyncio.run(_live())
    print(("PASS" if bad == 0 else "FAIL") + f" live: {bad}/6 câu trả lời còn kết thúc bằng câu hỏi")


if __name__ == "__main__":
    main()
