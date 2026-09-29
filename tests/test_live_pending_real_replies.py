"""LIVE — real chat model with the REAL production system prompt generates the offers
(not hand-written ones), then the pending-action prototype + code guards judge them.
No production code touched, nothing executes. Output is for human review.

Run: python tests/test_live_pending_real_replies.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from test_live_confirmation_rewrite import _llm_server_up, _grounded, _h  # noqa: E402
from test_live_pending_action import extract_pending, _guards_pass  # noqa: E402

PROMPTS = [
    "tôi cần ghi chú nhanh", "notepad mở kiểu gì", "máy tôi chậm quá", "hộp thư đầy quá",
    "tôi mệt quá", "tôi muốn làm việc", "chrome của tôi ngốn RAM ghê", "trời hôm nay có mưa không nhỉ",
    "tôi đang buồn", "file word của tôi bị lỗi font", "tôi muốn nghe nhạc", "dạo này tin tức có gì hot",
    "máy tính kêu to quá", "tôi quên lịch họp chiều nay rồi", "ổ C của tôi sắp đầy",
    "tôi muốn học tiếng Anh", "wifi nhà tôi chập chờn", "tôi hay quên uống nước",
]


async def main_async():
    from engine.prompts.chat import build_chat_system_prompt as load_system_prompt
    from engine.server.llm_server import call_llm
    system = load_system_prompt()
    for p in PROMPTS:
        resp = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": p}],
                              stream=False, thinking=False, temperature=0.0)
        reply = " ".join((resp.choices[0].message.content or "").split())
        if not reply.rstrip().endswith("?"):
            print(f"[no '?'] {p!r}: {reply[-140:]!r}\n")
            continue
        raw = await extract_pending(reply)
        grounded = raw != "NONE" and _grounded(raw, _h(reply))
        final = raw if grounded and _guards_pass(raw, reply) else "NONE"
        print(f"USER   : {p}\nJARVIS : ...{reply[-260:]}\nPENDING: raw={raw!r} grounded={grounded} -> FINAL={final!r}\n")


if __name__ == "__main__":
    if _llm_server_up():
        asyncio.run(main_async())
    else:
        print("LLM server (127.0.0.1:8080) không chạy -- bỏ qua.")
