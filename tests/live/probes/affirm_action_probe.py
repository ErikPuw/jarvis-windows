"""Read-only live probe.
Part 1: gate+classifier on short replies WITH history, short-reply fast-path removed (in memory only).
Part 2: chat model with <action> commit rule.
"""
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

from engine.router.fast_paths import resolve_mention, VOICE_CONTROL
from engine.router.replay import find_replay
from engine.router.gate import classify_bucket
from engine.router.types import TurnContext


async def gate(text, conversation_history=None):
    """engine.router.decide.decide() với short-reply fast-path bị vô hiệu — đó chính
    là điều probe này đo (spec §4 dự kiến xoá fast-path này ở Pha 3)."""
    clean = text.strip()
    agent, clean = resolve_mention(clean)
    if agent:
        return "agent"
    if VOICE_CONTROL.match(clean):
        return "agent"
    wf = await find_replay(clean, None)
    if wf:
        return "replay"
    ctx = TurnContext(ws=object(), send_json=None, conversation_history=conversation_history or [])
    return await classify_bucket(clean, ctx)


def h(assistant, user):
    return [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]

NOTEPAD = h("Tôi có thể mở Notepad cho ngài, ngài có muốn không?", "tôi cần ghi chú nhanh")
GOLD = h("Giá vàng biến động theo USD và lãi suất Fed. Ngài có muốn tôi tìm tin mới nhất về giá vàng hôm nay không?", "vì sao giá vàng hay lên xuống")
EMAIL = h("Ngài có muốn tôi kiểm tra hộp thư xem có thư mới không?", "sáng nay có ai gửi gì không nhỉ")
CHROME = h("Chrome đang ngốn RAM. Ngài có muốn tôi đóng Chrome không?", "máy chậm quá")
CHAT = h("Dạ, chúc ngài một ngày tốt lành ạ.", "cảm ơn nhé")
VOICE = h("Giọng hôm nay vẫn giọng miền Nam như mọi khi ạ. Ngài thấy ổn chứ?", "giọng đọc hôm nay sao")
FACT = h("La Mã tồn tại hơn 1000 năm. Ngài có muốn nghe thêm về Caesar không?", "kể về La Mã")

# (reply, history, expected) expected: "run:<agent>" | "general" | "general_knowledge"
P1 = [
    ("ừ", NOTEPAD, "run:desktop"), ("ok", NOTEPAD, "run:desktop"), ("có", GOLD, "run:search"),
    ("làm đi", EMAIL, "run:email"), ("ừ đóng đi", CHROME, "run:desktop"), ("vâng", CHROME, "run:desktop"),
    ("không", NOTEPAD, "general"), ("thôi khỏi", GOLD, "general"), ("để sau", EMAIL, "general"),
    ("chắc vậy", CHROME, "general|run:desktop"),
    ("ừ", CHAT, "general"), ("ok", CHAT, "general"), ("ừ", VOICE, "general"), ("có", VOICE, "general"),
    ("có", FACT, "general|general_knowledge"),
]

ACTION_RULE = (
    "\n\nKhi người dùng than phiền hay bày tỏ một nhu cầu mà bạn có thể tự giải quyết bằng MỘT việc cụ thể trên máy tính "
    "hoặc lấy dữ liệu (mở/đóng ứng dụng, tìm tin, xem giá, kiểm tra email...), hãy nói ngắn gọn rằng bạn sẽ làm ngay và "
    "thêm ở cuối: <action>câu lệnh ngắn tự nhiên</action>. Không hỏi lại, không nói là đã làm xong. "
    "Không thêm thẻ khi người dùng chỉ trò chuyện, hỏi cách tự làm, hoặc nói việc họ sẽ tự làm."
)
P2 = [
    ("tôi lười mở notepad quá", "action"), ("máy tôi chậm quá, chrome ngốn RAM ghê", "action"),
    ("hộp thư đầy quá", "action"), ("chán quá không biết hôm nay có tin gì mới", "action"),
    ("không biết giá vàng hôm nay thế nào nhỉ", "action"),
    ("tôi mệt quá", "chat"), ("cảm ơn nhé", "chat"), ("tôi đang định tự mở notepad để viết", "chat"),
    ("notepad mở kiểu gì", "chat"), ("tối nay tôi sẽ tự dọn dẹp máy", "chat"),
    ("bạn thấy giọng đọc hôm nay thế nào", "chat"), ("hôm nay tôi vui lắm", "chat"),
]


async def main():
    from engine.orchestrator.classifier import classify_tasks
    from engine.prompts.chat import build_chat_system_prompt as load_system_prompt
    from engine.server.llm_server import call_llm
    ok = 0
    for reply, hist, exp in P1:
        route = await gate(reply, conversation_history=hist)
        got, det = route, ""
        if route == "orchestrator":
            tasks = await classify_tasks(reply, conversation_history=hist)
            got = "run:" + (",".join(t["agent"] for t in tasks) or "NONE")
            det = str([(t["agent"], t["query"]) for t in tasks])
        p = got in exp.split("|"); ok += p
        print(f"P1 {'PASS' if p else 'FAIL'} {reply!r:12} after {hist[1]['content'][:48]!r:52} exp={exp:24} got={got:14} {det}")
    print(f"P1 TOTAL {ok}/{len(P1)}\n")

    system = load_system_prompt() + ACTION_RULE
    ok = 0
    for text, exp in P2:
        r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                           stream=False, thinking=False, temperature=0.0)
        body = r.choices[0].message.content or ""
        m = re.search(r"<action>(.*?)</action>", body, re.S)
        got = "action" if m else "chat"
        p = got == exp; ok += p
        reply = " ".join(re.sub(r"<action>.*?</action>", "", body, flags=re.S).split())[:130]
        print(f"P2 {'PASS' if p else 'FAIL'} {text!r:44} exp={exp:6} got={got:6} {('action=' + repr(m.group(1).strip())) if m else ''} | {reply}")
    print(f"P2 TOTAL {ok}/{len(P2)}")

asyncio.run(main())
