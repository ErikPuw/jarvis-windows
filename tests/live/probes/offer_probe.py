"""Read-only live probe: gate -> classifier | chat+<offer> tag. No production code touched."""
import asyncio, re, sys
from pathlib import Path
ROOT = Path(r"E:\workspace\jarvis")
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from engine.core import learning, memory
le = learning.get_learning_engine()
le.get_exact_workflow_candidates = lambda text: []
le.unlearn_last_route = lambda text, max_age_seconds=600: False
memory.build_unified_routing_history = lambda current_text, fallback_history, limit=12: list(fallback_history or [])[-limit:]

TAG_RULE = (
    "\n\nNếu trong câu trả lời bạn đề nghị CHÍNH BẠN làm đúng một việc cụ thể trên máy tính hoặc lấy dữ liệu "
    "và hỏi người dùng có muốn không, thêm ở cuối: <offer>câu lệnh ngắn</offer>. "
    "Không bao giờ nói là đã làm xong việc gì. Không thêm thẻ trong mọi trường hợp khác."
)

# (text, expected): "run" = gate orchestrator + right agent; "offer" = general + tag; "chat" = general, no tag
CASES = [
    ("jarvis nay tôi lười quá nhờ bạn mở cho tôi ứng dụng notepad", "run:desktop"),
    ("hôm nay mệt ghê, bật giùm tôi bài nhạc lofi đi", "run:media"),
    ("chán quá, xem giúp tôi giá vàng hôm nay", "run:search"),
    ("trời ơi quên mất, kiểm tra email giùm cái", "run:email"),
    ("ê jarvis, tắt chrome hộ tôi với, nó ngốn RAM quá", "run:desktop"),
    ("mở notepad", "run:desktop"),
    ("tôi lười mở notepad quá", "offer"),
    ("máy tôi chậm quá", "offer"),
    ("hộp thư đầy quá", "offer"),
    ("không biết chiều nay Hà Nội có mưa không nhỉ", "offer|run:search"),
    ("chrome của tôi ngốn RAM ghê", "offer"),
    ("tôi đang định tự mở notepad để viết", "chat"),
    ("notepad mở kiểu gì", "chat"),
    ("tôi mệt quá", "chat"),
    ("cảm ơn nhé", "chat"),
    ("bạn thấy giọng đọc hôm nay thế nào", "chat"),
    ("tối nay tôi sẽ tự dọn dẹp máy", "chat"),
]


async def main():
    from engine.router import TurnContext
    from engine.router.decide import decide
    from engine.orchestrator.classifier import classify_tasks
    from engine.prompts.chat import build_chat_system_prompt as load_system_prompt
    from engine.server.llm_server import call_llm
    system = load_system_prompt() + TAG_RULE
    ok = 0
    for text, exp in CASES:
        d = await decide(text, TurnContext(ws=object(), send_json=None, conversation_history=[]))
        route = d.kind
        got, detail = route, ""
        if route == "orchestrator":
            tasks = await classify_tasks(text, conversation_history=[])
            got = "run:" + ",".join(t["agent"] for t in tasks) if tasks else "run:NONE"
            detail = str([(t["agent"], t["query"]) for t in tasks])
        elif route == "general":
            r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                               stream=False, thinking=False, temperature=0.0)
            body = r.choices[0].message.content or ""
            m = re.search(r"<offer>(.*?)</offer>", body, re.S)
            got = "offer" if m else "chat"
            detail = (f"offer={m.group(1).strip()!r} " if m else "") + "reply=" + " ".join(re.sub(r"<offer>.*?</offer>", "", body, flags=re.S).split())[:160]
        passed = got in exp.split("|")
        ok += passed
        print(f"{'PASS' if passed else 'FAIL'} {text!r:62} exp={exp:18} got={got:14} {detail}")
    print(f"\nTOTAL {ok}/{len(CASES)}")

asyncio.run(main())
