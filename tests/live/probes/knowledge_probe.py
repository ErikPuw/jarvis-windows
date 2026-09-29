"""Live probe: nhánh general_knowledge sau khi thu gọn prompt thành "như tool" (2026-09-26).

Kiểm tra: trả lời đúng từ dữ liệu Wikipedia, hiểu câu nối tiếp ("ông ấy"), vẫn dùng kiến thức sẵn có
khi không có dữ liệu, "thưa ngài" tối đa 1 lần, không gắn thẻ đề nghị.
Acceptance: mỗi kịch bản đúng >= 9/RUNS, lỗi xưng hô/thẻ <= 1/RUNS.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/knowledge_probe.py [runs]
Requires: llama-server 127.0.0.1:8080.
"""
import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

WIKI_NAPOLEON = ("Napoléon Bonaparte (1769–1821) là nhà quân sự và chính trị gia người Pháp, "
                 "Hoàng đế của người Pháp từ 1804 đến 1814 và năm 1815.")
WIKI_DEATH = "Napoléon qua đời ngày 5 tháng 5 năm 1821 trên đảo Saint Helena khi đang bị lưu đày."
CASES = [  # tên, lịch sử, câu hỏi, dữ liệu wiki, regex câu trả lời đúng
    ("hỏi thường", [], "Napoleon là ai", WIKI_NAPOLEON, r"Pháp|hoàng đế"),
    ("nối tiếp", [{"role": "user", "content": "Napoleon là ai"},
                  {"role": "assistant", "content": "Napoléon Bonaparte là Hoàng đế của người Pháp, thưa ngài."}],
     "ông ấy mất ở đâu", WIKI_DEATH, r"Helena|Xanh Hê-lê-na"),
    ("không dữ liệu", [], "thủ đô của Úc là thành phố nào", "", r"Canberra"),
]


async def main():
    from engine.prompts import chat
    from engine.server.llm_server import call_llm
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    fail = False
    for name, hist, q, wiki, ok_re in CASES:
        ok = bad = 0
        ex = ""
        for _ in range(runs):
            ref = {"mcp_data": wiki} if wiki else {}
            msgs = chat.build_chat_messages(q, conversation_history=hist, route="general_knowledge", reference_data=ref)
            out = (await call_llm(messages=msgs, stream=False, thinking=False)).choices[0].message.content or ""
            ok += bool(re.search(ok_re, out, re.I))
            b = len(re.findall(r"thưa ngài", out, re.I)) >= 2 or bool(re.search(r"\n\s*thưa ngài\.?\s*$", out, re.I)) or "<ask_user>" in out
            bad += b
            if (b or not re.search(ok_re, out, re.I)) and not ex:
                ex = out
        print(f"{name:14} đúng {ok}/{runs} | lỗi xưng hô/thẻ {bad}/{runs} | vd: {' '.join((ex or out).split())[:160]!r}")
        fail |= ok < runs - 1 or bad > 1
    print("FAIL" if fail else "PASS")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    asyncio.run(main())
