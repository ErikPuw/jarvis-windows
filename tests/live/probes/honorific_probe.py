"""Live probe: "thưa ngài" chỉ một lần, gắn cuối câu, không thành dòng riêng (log 2026-09-25).

Trước khi sửa: có lịch sử DB → 2 lần 9/10, dòng riêng 10/10; không lịch sử → 1/10, 4/10.
Acceptance: mỗi trường hợp <= 1/RUNS cho cả hai chỉ số.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/honorific_probe.py [runs]
Requires: llama-server 127.0.0.1:8080 (chỉ đọc DB).
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

QUESTIONS = ["hệ thống bạn hôm nay thế nào", "hôm nay tôi hơi mệt"]
LINE_RE = re.compile(r"\n\s*thưa ngài[.!]?\s*$", re.I)


async def main():
    from engine.core.memory import build_unified_routing_history
    from engine.prompts import chat
    from engine.server.llm_server import call_llm
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    fail = False
    for q in QUESTIONS:
        for label, hist in (("không lịch sử", []), ("lịch sử DB", build_unified_routing_history(q, [], 12))):
            dbl = line = 0
            ex = ""
            for _ in range(runs):
                msgs = chat.build_chat_messages(q, conversation_history=hist)
                out = (await call_llm(messages=msgs, stream=False, thinking=False)).choices[0].message.content or ""
                d = len(re.findall(r"thưa ngài", out, re.I)) >= 2
                l = bool(LINE_RE.search(out))
                dbl += d
                line += l
                if (d or l) and not ex:
                    ex = out
            print(f"{q[:24]:24} {label:13} 2 lần {dbl}/{runs} | dòng riêng {line}/{runs} | vd: {' '.join(ex.split())[-110:]!r}")
            fail |= dbl > 1 or line > 1
    print("FAIL" if fail else "PASS")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
