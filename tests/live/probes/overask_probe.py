"""Live (read-only): chat thường (không cần công cụ) có bị gắn lời đề nghị lạc chủ đề không.
Câu lấy từ jarvis.log 2026-09-27 20:42–21:00: 4 lượt liên tiếp đề nghị tin tức/chụp màn hình/lịch/ghi chú không liên quan.
Mục tiêu: TALK gần 0 lời đề nghị. Kiểm hồi quy bằng offer_protocol_probe.py và plan_offer_probe.py.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/overask_probe.py [runs]
"""
import asyncio
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

TALK = [
    "xin chào jarvis",
    "bạn đang làm gì đó",
    "Jarvis có bạn mới rồi",
    "jarvis có bạn fox nhỏ đồng hành mascot đang ở trên thanh command",
    "tôi add cho bạn mà trên giao diện webui làm sao bạn thấy được",
    "không cần đâu bạn học là có bạn fox nhỏ trên thanh command là được rồi",
    "không cần ghi chú đâu bạn nhớ là được",
    "tôi đang xem hệ thống của bạn hoạt động như thế nào",
]


async def main(runs: int):
    from engine.prompts.chat import build_chat_system_prompt
    from engine.router.ask_user import extract, extract_action
    from engine.server.llm_server import call_llm
    system = build_chat_system_prompt()
    t0, c = time.time(), Counter()
    for text in TALK:
        for _ in range(runs):
            r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                               stream=False, thinking=False)
            body = r.choices[0].message.content or ""
            _, ask = extract(body)
            if ask:
                tool = extract_action(body) or "?"
                c[tool] += 1
                print(f"  OVERASK {tool:14} {text[:45]!r:50} -> {ask[:50]!r}")
    total = sum(c.values())
    print(f"TALK overask={total}/{len(TALK) * runs} {dict(c)}  ({time.time() - t0:.0f}s)")
    return total


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 3))
