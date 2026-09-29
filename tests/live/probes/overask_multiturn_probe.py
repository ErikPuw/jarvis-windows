"""Live (read-only): đề nghị thừa qua NHIỀU LƯỢT, dùng đúng build_chat_messages (lịch sử + <turn_status>).
Phát lại hội thoại trong jarvis.log 2026-09-27 20:42–21:00 (4 lượt liên tiếp đề nghị tin tức/chụp màn hình/
lịch/ghi chú không liên quan). Câu trả lời của model được đưa lại vào lịch sử y như production:
content sạch + cột ask_user/action_run riêng (memory.save_message).
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/overask_multiturn_probe.py [replays]
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

TURNS = [
    "xin chào jarvis",
    "bạn đang làm gì đó",
    "Jarvis có bạn mới rồi",
    "jarvis có bạn fox nhỏ đồng hành mascot đang ở trên thanh command",
    "tôi add cho bạn mà trên giao diện webui làm sao bạn thấy được",
    "không cần đâu bạn học là có bạn fox nhỏ trên thanh command là được rồi",
    "không cần ghi chú đâu bạn nhớ là được",
    "tôi đang xem hệ thống của bạn hoạt động như thế nào",
]


# --ref: mô phỏng khối <reference> mà engine/router/chat.py nạp ở production (kết quả agent gần nhất).
REFERENCE = {"agent_results": ['[email] "xem email" → thành công', '[search] "tìm tin tức công nghệ" → thành công']}


async def replay() -> list[str]:
    from engine.prompts.chat import build_chat_messages
    from engine.router.ask_user import extract, extract_action
    from engine.server.llm_server import call_llm
    history, offers = [], []
    for text in TURNS:
        history.append({"role": "user", "content": text})
        messages = build_chat_messages(text, conversation_history=history, route="general",
                                       reference_data=REFERENCE if "--ref" in sys.argv else None)
        r = await call_llm(messages=messages, stream=False, thinking=False)
        body = r.choices[0].message.content or ""
        clean, ask = extract(body)
        action = extract_action(body) if ask else ""
        offers.append(f"{action or '?'}:{ask[:30]}" if ask else "")
        history.append({"role": "assistant", "content": clean, "ask_user": ask, "action_run": action})
    return offers


async def main(replays: int):
    t0, total, c = time.time(), 0, Counter()
    for n in range(replays):
        offers = await replay()
        hit = [o for o in offers if o]
        total += len(hit)
        c.update(o.split(":")[0] for o in hit)
        print(f"replay {n + 1}: {len(hit)}/{len(TURNS)} lượt có đề nghị | " + " | ".join(o or "-" for o in offers))
    print(f"TOTAL overask={total}/{len(TURNS) * replays} {dict(c)} ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    asyncio.run(main(int(args[0]) if args else 3))
