"""Live probe (chỉ gọi llama-server 127.0.0.1:8080, không đụng JARVIS): vì sao chat "general" gợi ý liên tục?

Cùng bộ câu của ngài (cả lúc phàn nàn "lại gợi ý nữa") chạy qua nhiều biến thể prompt x sampling.
Prompt thật lấy từ engine.prompts.chat.build_chat_messages (đọc STYLE.md, Preferences.md hiện tại).

Prompt:  P0 như đang chạy | P1 bỏ <offer_protocol> | P2 P0 + luật "không tự gợi ý" đưa vào <style> (chỉ thị)
         P3 = P1 + P2 | PT = P1 + function calling gốc của Gemma 4 (tool offer_action) thay cho thẻ
Sampling: S0 production (0.4/0.8/40/min_p 0) | S1 Google (1.0/0.95/64/min_p 0.05)
Chỉ số (câu KHÔNG nên đề nghị): TAG = có <ask_user>/<action_run> (hoặc tool_call ở PT); Q = có "?" ở 160 ký tự cuối;
  SORRY = có "xin lỗi"; DRAMA = từ làm quá ("Ôi trời", "cam đoan", "hứa"...); LEN = số ký tự trung bình.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/suggestion_probe.py [runs=3] [--only P0S0,P3S1]
"""
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

URL = "http://127.0.0.1:8080/v1/chat/completions"
KEY = os.getenv("LOCAL_API_KEY", "")

_OFFERED = [{"role": "user", "content": "mở task manager"},
            {"role": "assistant", "content": "Tôi đã mở Task Manager thành công. Ngài có muốn tôi kiểm tra lịch hẹn của ngài không?"}]
CASES = [  # (id, câu của ngài, lịch sử, có nên đề nghị không)
    ("greet", "xin chào jarvis", [], False),
    ("tired", "Jarvis ơi, tôi mệt lắm đó", [], False),
    ("watching", "tôi đang xem hoạt động của bạn ra sao, xem có chút thay đổi thì bạn sẽ như thế nào", [], False),
    ("music_q", "Biết tôi thích nghe nhạc gì không?", [], False),
    ("agents", "có danh sách chi tiết các agents không", [], False),
    ("thanks", "cảm ơn nhé", [], False),
    ("happy", "hôm nay tôi vui lắm", [], False),
    ("ai", "bạn nghĩ sao về trí tuệ nhân tạo", [], False),
    ("complain1", "lại gợi ý nữa hạn chế đi bực rồi đó", _OFFERED, False),
    ("complain2", "hãy giảm tần xuất gợi ý lại nhé, tôi nhắc nhở nhiều lần lắm rồi đó.", _OFFERED, False),
    ("lazy_notepad", "tôi lười mở notepad quá", [], True),
    ("gold", "không biết giá vàng hôm nay thế nào nhỉ", [], True),
]
if "--all" in sys.argv:  # thêm 9 câu NÊN đề nghị + 10 câu chat thường của action_run_probe
    from tests.live.probes.action_run_probe import CASES as _AR
    CASES += [(f"ar{i}", t, [], k == "offer") for i, (k, t, _e) in enumerate(_AR)]
SAMPLING = {
    "S0": {"temperature": 0.4, "top_p": 0.8, "top_k": 40, "min_p": 0.0},
    "S1": {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "min_p": 0.05},
}
NO_SUGGEST_RULE = ("- Không tự đưa ra gợi ý, đề nghị hay câu hỏi thêm khi ngài chưa yêu cầu: "
                   "trả lời đúng điều ngài nói rồi dừng. Khi ngài phàn nàn thì nhận một câu ngắn gọn, không hứa hẹn dài dòng.")
OFFER_TOOL = {"type": "function", "function": {
    "name": "offer_action",
    "description": "Chỉ dùng khi ngài ngại hoặc lười tự làm một việc hệ thống làm được, để xin phép làm việc đó. Không dùng khi ngài chỉ trò chuyện.",
    "parameters": {"type": "object", "properties": {
        "tool": {"type": "string", "enum": ["open_app", "check_mail", "weather_search", "get_market_data", "search_media", "take_note"]},
        "command": {"type": "string", "description": "việc cần làm, ngắn gọn"}},
        "required": ["tool", "command"]}}}

MINI_PROTOCOL = (
    "<offer_protocol>\n"
    "Mặc định chỉ trả lời bằng lời, không gợi ý hay đề nghị gì thêm.\n"
    "Chỉ khi chính ngài nói mình ngại, lười hoặc muốn nhờ một việc trong danh sách bên dưới, mới kết thúc bằng một câu: "
    "Ngài có muốn tôi <ask_user>[việc]</ask_user> không?<action_run>[tên công cụ]</action_run>\n"
    "Danh sách công cụ: {tools}\n"
    "</offer_protocol>"
)
MINI_PROTOCOLS = {
    "M4": (
        "<offer_protocol>\n"
        "Mặc định chỉ trả lời bằng lời, không gợi ý hay đề nghị gì thêm.\n"
        "Ngoại lệ: khi câu của ngài nêu một nhu cầu hoặc thắc mắc mà đúng MỘT công cụ trong danh sách giải quyết trực tiếp "
        "(hoặc ngài ngại, lười tự làm việc đó), trả lời ngắn rồi kết thúc bằng một câu: "
        "Ngài có muốn tôi <ask_user>[việc]</ask_user> không?<action_run>[tên công cụ]</action_run>\n"
        "Trò chuyện, cảm xúc, câu hỏi kiến thức, hỏi về chính bạn hay về hệ thống: không dùng thẻ.\n"
        "Danh sách công cụ: {tools}\n"
        "</offer_protocol>"
    ),
    "M5": (
        "<offer_protocol>\n"
        "Mặc định chỉ trả lời bằng lời, không gợi ý hay đề nghị gì thêm.\n"
        "Chỉ khi ngài nêu một nhu cầu hoặc thắc mắc mà đúng MỘT công cụ trong danh sách làm được ngay, và ngài chưa tự làm, "
        "mới trả lời ngắn rồi kết thúc bằng một câu: "
        "Ngài có muốn tôi <ask_user>[việc]</ask_user> không?<action_run>[tên công cụ]</action_run>\n"
        "Không dùng thẻ khi ngài trò chuyện, nói cảm xúc, hỏi kiến thức, hỏi về chính bạn hay hệ thống, phàn nàn, hoặc nói việc ngài sẽ tự làm.\n"
        "Danh sách công cụ: {tools}\n"
        "</offer_protocol>"
    ),
}
WANTS_HELP_RE = re.compile(r"lười|ngại|nhờ\b|giúp (tôi|mình)|(làm|mở|tìm|kiểm tra|xem) (giúp|hộ|dùm)|chán quá|không biết .{0,50}(nhỉ|không)|lâu rồi chưa|đầy quá", re.I)

DRAMA_RE = re.compile(r"Ôi trời|Ôi chao|cam đoan|cam kết|tôi hứa|xin hứa|thề", re.I)


def build(prompt_id: str, text: str, history: list):
    from engine.prompts.chat import build_chat_messages
    msgs = build_chat_messages(text, conversation_history=list(history), route="general")
    sys0 = msgs[0]["content"]
    base = prompt_id.split("-")[0]
    if base in ("M1", "M2", "M3", "M4", "M5"):  # giao thức ngắn; M2 chỉ nạp khi câu ngài có dấu hiệu nhờ/lười; M3 đặt sát câu hỏi
        from engine.prompts import catalog
        mini = MINI_PROTOCOLS.get(base, MINI_PROTOCOL).format(tools=catalog.tool_list_text())
        sys0 = re.sub(r"<offer_protocol>.*?</offer_protocol>\s*", "", sys0, flags=re.S)
        if base in ("M1", "M4", "M5") or (base == "M2" and WANTS_HELP_RE.search(text)):
            sys0 = sys0.replace("<style>", mini + "\n\n<style>", 1) if "<style>" in sys0 else sys0.replace("<about_user>", mini + "\n\n<about_user>", 1)
        elif base == "M3":
            msgs.insert(len(msgs) - 1, {"role": "system", "content": mini})
    if base in ("P1", "P3", "PT"):
        sys0 = re.sub(r"<offer_protocol>.*?</offer_protocol>\s*", "", sys0, flags=re.S)
    if base in ("P2", "P3"):
        sys0 = re.sub(r"^.*reduce_suggestion_frequency.*\n", "", sys0, flags=re.M)
        if "</style>" in sys0:
            sys0 = sys0.replace("</style>", NO_SUGGEST_RULE + "\n</style>")
        else:
            sys0 = sys0.replace("<about_user>", f"<style>\n{NO_SUGGEST_RULE}\n</style>\n\n<about_user>", 1)
    # Ablation: "P1-cap" = P1 bỏ <capabilities>; -style/-soul/-about tương tự; -min chỉ giữ identity + current_time;
    # "P0-pref" = P0 bỏ đúng dòng reduce_suggestion_frequency (đo tác dụng của bài học đã lưu).
    for part in prompt_id.split("-")[1:]:
        if part == "pref":
            sys0 = re.sub(r"^.*reduce_suggestion_frequency.*\n", "", sys0, flags=re.M)
        elif part == "min":
            keep = [re.search(rf"<{t}>.*?</{t}>", sys0, re.S) for t in ("identity", "current_time")]
            sys0 = "\n\n".join(m.group(0) for m in keep if m)
        else:
            tag = {"cap": "capabilities", "style": "style", "soul": "soul_rules", "about": "about_user"}[part]
            sys0 = re.sub(rf"<{tag}>.*?</{tag}>\s*", "", sys0, flags=re.S)
    msgs[0] = {"role": "system", "content": sys0}
    return msgs


def call(msgs, sampling, tools=None):
    body = {"model": "x", "messages": msgs, "max_tokens": 400, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}, **sampling}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    req = urllib.request.Request(URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/json"})
    m = json.load(urllib.request.urlopen(req, timeout=120))["choices"][0]["message"]
    return (m.get("content") or ""), bool(m.get("tool_calls"))


def judge(text: str, tool_called: bool) -> dict:
    tag = ("<ask_user>" in text) or ("<action_run>" in text) or tool_called
    clean = re.sub(r"<ask_user>|</ask_user>|<action_run>.*?</action_run>", "", text, flags=re.S)
    return {"tag": tag, "q": "?" in clean[-160:], "sorry": "xin lỗi" in clean.lower(),
            "drama": bool(DRAMA_RE.search(clean)), "len": len(clean)}


def run_one(args):
    variant, case, n = args
    prompt_id, samp_id = variant[:-2], variant[-2:]
    cid, text, hist, should = case
    msgs = build(prompt_id, text, hist)
    out, tc = call(msgs, SAMPLING[samp_id], [OFFER_TOOL] if prompt_id == "PT" else None)
    return variant, cid, should, judge(out, tc), out


def main():
    runs = int(next((a for a in sys.argv[1:] if a.isdigit()), 3))
    only = next((a.split("=", 1)[1] if "=" in a else sys.argv[sys.argv.index(a) + 1] for a in sys.argv if a.startswith("--only")), "")
    allv = ("P0S0", "P0S1", "P1S0", "P1S1", "P2S0", "P3S1", "PTS1")
    variants = only.split(",") if only else list(allv)
    jobs = [(v, c, n) for v in variants for c in CASES for n in range(runs)]
    with ThreadPoolExecutor(max_workers=3) as ex:
        res = list(ex.map(run_one, jobs))
    print(f"\n{'biến thể':8} | câu KHÔNG nên đề nghị: TAG  Q(?)  SORRY DRAMA  LEN | câu NÊN đề nghị: TAG")
    for v in variants:
        neg = [r[3] for r in res if r[0] == v and not r[2]]
        pos = [r[3] for r in res if r[0] == v and r[2]]
        f = lambda xs, k: sum(1 for x in xs if x[k])
        print(f"{v:8} | {f(neg,'tag'):3}/{len(neg)}  {f(neg,'q'):3}/{len(neg)}  {f(neg,'sorry'):3}/{len(neg)}  "
              f"{f(neg,'drama'):3}/{len(neg)}  {sum(x['len'] for x in neg)//max(1,len(neg)):4} | {f(pos,'tag')}/{len(pos)}")
    for v in variants:
        print(f"\n--- [{v}] câu KHÔNG nên đề nghị mà vẫn gắn thẻ / câu NÊN đề nghị mà thiếu thẻ:")
        for cid, text, _h, should in CASES:
            n = [r[3]["tag"] for r in res if r[0] == v and r[1] == cid]
            if n and (sum(n) > 0 if not should else sum(n) < len(n)):
                print(f"  {cid:13} should_offer={should!s:5} tag={sum(n)}/{len(n)} | {text[:60]}")
    print("\n--- Ví dụ câu complain1 mỗi biến thể:")
    for v in variants:
        ex_ = next((r[4] for r in res if r[0] == v and r[1] == "complain1"), "")
        print(f"  [{v}] {' '.join(ex_.split())[:230]}")


if __name__ == "__main__":
    main()
