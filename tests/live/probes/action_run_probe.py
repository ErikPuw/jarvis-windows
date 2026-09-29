"""Live, read-only probe (no production code changed): can the chat model emit
    <ask_user>short command</ask_user><action_run>real_tool_name</action_run>
when it offers to do something, and stay silent on plain chat?

Variants (same model, sentences, sampling; only the capability-card rule differs):
  CUR  production prompt as shipped (one <ask_user> tag holding the QUESTION)
  NEW  two tags: <ask_user> = short command to run, <action_run> = one tool name from OFFERABLE
Chat stage only (the gate is not involved). Scoring per reply:
  offer case: PASS = tags present, action_run in OFFERABLE and in the case's expected tools,
              ask_user is a short command (<= 8 words, no "?")
              BADTOOL = action_run missing/not a real offerable tool; WRONGTOOL = real tool, wrong one;
              NOTCMD = ask_user is a question/too long; MISS = no tag
  chat case : PASS = no tag; OVERASK = any tag
  CLAIM (both): says it already did something.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/action_run_probe.py [runs]
"""
import asyncio, os, re, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# Default RUNS value; will be overridden from sys.argv in main() if run directly
RUNS = 3

# Tools a chat offer may name (read-only or opening things). Excluded on purpose: win_control,
# office_tool, rag_tool, dream, install_extension, mcp_call (need confirmation/attachment or are internal).
OFFERABLE = {
    "open_app": "mở ứng dụng", "close_app": "đóng ứng dụng", "check_mail": "xem email",
    "check_calendar": "xem lịch hẹn", "weather_search": "tra thời tiết", "search_news": "tìm tin tức",
    "get_market_data": "giá vàng/xăng/tỷ giá", "get_cgv_movies": "lịch chiếu phim",
    "get_epic_free_games": "game miễn phí", "search_media": "mở nhạc/phim/video",
    "cap_screen": "chụp màn hình", "read_screen": "xem màn hình", "take_note": "ghi chú",
    "query_history": "xem lại lịch sử trò chuyện", "get_vannien_data": "lịch vạn niên",
}
TOOL_LIST = ", ".join(f"{k} ({v})" for k, v in OFFERABLE.items())
NEW_RULE = (
    "Trong lượt trả lời này chưa có công cụ nào chạy và bạn không tự chạy: không nói mình đang hay đã làm gì. "
    "Nếu một việc trong danh sách trên thật sự giúp được ngài lúc này, hãy hỏi xin phép bằng lời như bình thường, "
    "rồi thêm ở cuối hai thẻ: <ask_user>câu lệnh ngắn cho đúng MỘT việc đó</ask_user><action_run>tên công cụ</action_run>. "
    f"Tên công cụ chỉ được chọn một trong: {TOOL_LIST}. Hệ thống chỉ chạy khi ngài đồng ý. "
    "Không dùng thẻ khi ngài chỉ trò chuyện, hỏi cách tự làm, hoặc nói việc ngài sẽ tự làm. "
    "Câu hỏi để làm rõ thông tin thì hỏi bình thường, không dùng thẻ.\n"
)
NEWQ_RULE = NEW_RULE.replace(
    "hãy hỏi xin phép bằng lời như bình thường, rồi thêm ở cuối hai thẻ: <ask_user>câu lệnh ngắn cho đúng MỘT việc đó</ask_user>",
    "kết thúc bằng đúng MỘT câu hỏi có/không xin phép làm MỘT việc đó (nêu rõ việc và đối tượng) bọc trong <ask_user>...</ask_user>, "
    "ngay sau đó là",
)
assert NEWQ_RULE != NEW_RULE

# Candidate code-side command extraction for NEWQ (wider wrapper than engine/router/ask_user.ask_to_command).
_WRAP = re.compile(
    r"^(?:thưa ngài,?\s*)?(?:ngài\s+)?(?:có\s+)?(?:muốn|cần|cho phép|đồng ý (?:cho|để)|để)\s+tôi\s+"
    r"|^(?:tôi\s+)?(?:có\s+)?(?:nên|được phép|có thể)\s+|^cho\s+(?:tôi\s+)?phép\s+(?:tôi\s+)?|^để\s+tôi\s+", re.I)
_TAIL = re.compile(r"(?:\s+(?:cho ngài|giúp ngài|ngay bây giờ|ngay lúc này|bây giờ|ngay|lần nữa|luôn))*"
                   r"\s*(?:không|nhé|chứ|nha|được không)?\s*(?:ạ|thưa ngài)?\s*\?\s*$", re.I)
_YESNO_END = re.compile(r"(không|nhé|chứ|nha|được không|ạ)\s*\?\s*$", re.I)


def ask_to_command(ask):
    return _TAIL.sub("", _WRAP.sub("", ask.strip())).strip(" ,.")


def is_actionable(ask):
    a = " " + ask.lower() + " "
    return (ask.count("?") == 1 and len(ask) <= 200 and " hay " not in a and " hoặc " not in a
            and bool(_YESNO_END.search(ask)))


ASK_RE = re.compile(r"<ask_user>\s*(.*?)\s*(?:</ask_user>|<ask_user>|<action_run>|$)", re.S)
RUN_RE = re.compile(r"<action_run>\s*(.*?)\s*(?:</action_run>|<action_run>|$)", re.S)
TAG_RE = re.compile(r"</?(?:ask_user|action_run)>")
CLAIM_RE = re.compile(r"(?:tôi|mình|em)\s+(?:đã|vừa)\s+(?:mở|đóng|ghi|lưu|kiểm tra|tìm|tra|gửi|xóa|xoá|bật|tắt|phát|chụp|dọn)", re.I)

CASES = [  # (kind, text, expected tools)
    ("offer", "tôi lười mở notepad quá", {"open_app"}),
    ("offer", "hộp thư đầy quá", {"check_mail"}),
    ("offer", "chán quá không biết hôm nay có tin gì mới", {"search_news"}),
    ("offer", "không biết giá vàng hôm nay thế nào nhỉ", {"get_market_data"}),
    ("offer", "lâu rồi chưa nghe nhạc của Đen Vâu", {"search_media"}),
    ("offer", "không biết tuần này mình có lịch hẹn gì không nhỉ", {"check_calendar"}),
    ("offer", "đang muốn viết vài dòng mà lười mở word quá", {"open_app"}),
    ("offer", "không nhớ hôm qua mình đã làm những gì nữa", {"query_history"}),
    ("offer", "tò mò không biết ngoài kia có game miễn phí nào không", {"get_epic_free_games"}),
    ("chat", "cảm ơn nhé", set()),
    ("chat", "tôi đang định tự mở notepad để viết", set()),
    ("chat", "notepad mở kiểu gì", set()),
    ("chat", "tối nay tôi sẽ tự dọn dẹp máy", set()),
    ("chat", "bạn thấy giọng đọc hôm nay thế nào", set()),
    ("chat", "hôm nay tôi vui lắm", set()),
    ("chat", "hôm qua tôi thức khuya quá", set()),
    ("chat", "bạn nghĩ sao về trí tuệ nhân tạo", set()),
    ("chat", "tôi vừa tự mở excel xong rồi", set()),
    ("chat", "tuần sau tôi sẽ tự cài lại windows", set()),
]


def build_prompts():
    from engine import prompts
    from engine.prompts.chat import build_chat_system_prompt
    cur = build_chat_system_prompt()
    card = prompts.load("capabilities")
    i = card.index("Trong lượt trả lời này chưa có công cụ nào chạy")
    j = card.index("không dùng thẻ.\n") + len("không dùng thẻ.\n")
    new = cur.replace(card, card[:i] + NEW_RULE + card[j:])
    newq = cur.replace(card, card[:i] + NEWQ_RULE + card[j:])
    prod = cur  # production prompt now uses NEWQ_RULE measured design
    assert new != cur and "<action_run>" in new and "<action_run>" in cur and newq != new
    only = [a[2:] for a in sys.argv[1:] if a.startswith("--") and a[2:] in ("CUR", "NEW", "NEWQ", "PROD")]
    allp = {"CUR": cur, "NEW": new, "NEWQ": newq, "PROD": prod}
    return {k: allp[k] for k in (only or allp)}


def judge(kind, exp, body, variant):
    m, r = ASK_RE.search(body), RUN_RE.search(body)
    if kind == "chat":
        return ("OVERASK", (m.group(1) if m else "") + " | " + (r.group(1) if r else "")) if (m or r) else ("PASS", "")
    if not m:
        return "MISS", ""
    ask = " ".join(m.group(1).split())
    if variant == "CUR":  # two-tag design: the tag holds the question; the command is extracted by code
        if not is_actionable(ask):
            return "VAGUE", ask
        return "TAGGED", ask
    tool = (r.group(1).strip().strip("`'\" ") if r else "")
    if tool not in OFFERABLE:
        return "BADTOOL", f"{ask} | {tool!r}"
    if tool not in exp:
        return "WRONGTOOL", f"{ask} | {tool}"
    if variant in ("NEWQ", "PROD"):  # tag holds the question; the command is extracted by code
        if not is_actionable(ask):
            return "VAGUE", f"{ask} | {tool}"
        cmd = ask_to_command(ask)
        if len(cmd.split()) < 2 or "?" in cmd:
            return "BADCMD", f"{ask} -> {cmd!r} | {tool}"
        return "PASS", f"{cmd!r} | {tool}"
    if "?" in ask or len(ask.split()) > 8:
        return "NOTCMD", f"{ask} | {tool}"
    return "PASS", f"{ask} | {tool}"


async def main():
    global RUNS
    import json, urllib.request
    from engine.server.llm_server import active_model_key, call_llm
    # Parse sys.argv for RUNS when run directly (not when imported)
    _args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if _args:
        try:
            RUNS = int(_args[0])
        except (ValueError, IndexError):
            RUNS = 3
    req = urllib.request.Request("http://127.0.0.1:8080/props", headers={"Authorization": "Bearer " + os.getenv("LOCAL_API_KEY", "")})
    print(f"model={json.load(urllib.request.urlopen(req, timeout=3)).get('model_path')!r} profile={active_model_key()} runs={RUNS}")
    prompts = build_prompts()
    t0 = time.time()
    for name, system in prompts.items():
        c, ex = Counter(), []
        for kind, text, exp in CASES:
            for _ in range(RUNS):
                r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                                   stream=False, thinking=False)
                body = r.choices[0].message.content or ""
                mark, note = judge(kind, exp, body, name)
                c[f"{kind}:{mark}"] += 1
                c["CLAIM"] += bool(CLAIM_RE.search(TAG_RE.sub("", body)))
                c["SHOWN_TAG"] += 0  # markers are stripped by the stream filter in production
                if mark not in ("PASS",) and len(ex) < 14:
                    ex.append(f"{kind:5} {mark:9} {text[:40]!r:44} -> {note[:110]}")
        n_off, n_chat = 9 * RUNS, 10 * RUNS
        print(f"\n[{name}] ({time.time() - t0:.0f}s) offer: " + ", ".join(f"{k.split(':')[1]}={v}" for k, v in sorted(c.items()) if k.startswith("offer:"))
              + f"  (/{n_off}) | chat: " + ", ".join(f"{k.split(':')[1]}={v}" for k, v in sorted(c.items()) if k.startswith("chat:"))
              + f"  (/{n_chat}) | CLAIM={c['CLAIM']}")
        for line in ex:
            print("   " + line)


if __name__ == "__main__":
    asyncio.run(main())
