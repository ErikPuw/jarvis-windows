"""Cause-isolation experiment: same model, same sentences, same sampling — only the SYSTEM PROMPT changes.
Answers: are bad <ask_user> results caused by the model, or by how the test/production prompt is assembled?

Chat stage only (the gate is unaffected by the chat prompt; it is measured by live_eval / pipeline_probe).
Variants (built from the real load_system_prompt() output in memory; no file is edited):
  P  production prompt, NO ask rule           -> how often production already ends on a question / "ra lệnh trực tiếp"
  A  production prompt + rule appended at end -> what pipeline_probe measured
  B  A with the three conflicts removed:
       * <capabilities>: "no tool runs this turn ... just tell the user to command directly" replaced by the ask rule
       * soul #1: "và gợi ý bước tiếp theo" removed
       * rule says clarifying questions are asked normally, never tagged
  C  B minus <user_preferences> and <style_rules> (topic noise: gym, 1945, project...)
Also checks the parser: PARSE = reply mentions ask_user but the regex found no well-formed tag.

Model profile: pass --gemma to use the gemma sampling profile in THIS process only (.env untouched).
Run:  PYTHONIOENCODING=utf-8 python .../prompt_ablation.py [runs] [--gemma]
"""
import asyncio, os, re, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
if "--gemma" in sys.argv:
    os.environ["CHANG_MODEL"] = "true"
args = [a for a in sys.argv[1:] if not a.startswith("--")]
RUNS = int(args[0]) if args else 3

ASK_RULE_TAIL = (
    "\n\nNếu muốn đề nghị CHÍNH BẠN làm một việc cụ thể trên máy tính hoặc lấy dữ liệu, đừng tự làm và đừng nói đã làm xong: "
    "kết thúc bằng đúng MỘT câu hỏi xin phép cho MỘT việc, nêu rõ việc và đối tượng, bọc trong <ask_user>...</ask_user>. "
    "Không dùng thẻ khi người dùng chỉ trò chuyện, hỏi cách tự làm, hoặc nói việc họ sẽ tự làm."
)
ASK_RULE_IN_CARD = (
    "Trong lượt trả lời này chưa có công cụ nào chạy và bạn không tự chạy: không nói mình đang hay đã làm gì. "
    "Nếu một việc trong danh sách trên thật sự giúp được ngài lúc này, kết thúc bằng đúng MỘT câu hỏi có/không xin phép "
    "làm MỘT việc đó (nêu rõ việc và đối tượng), bọc trong <ask_user>...</ask_user>; hệ thống chỉ chạy khi ngài đồng ý. "
    "Không dùng thẻ khi ngài chỉ trò chuyện, hỏi cách tự làm, hoặc nói việc ngài sẽ tự làm. "
    "Câu hỏi để làm rõ thông tin thì hỏi bình thường, không bọc thẻ.\n"
)
# Tolerant: small models close with "<ask_user>" (no slash) or not at all (Qwopus V3, 7/54 replies).
ASK_RE = re.compile(r"<ask_user>\s*(.*?)\s*(?:</ask_user>|<ask_user>|$)", re.S)
CLAIM_RE = re.compile(r"(?:tôi|mình|em)\s+(?:đã|vừa)\s+(?:mở|đóng|ghi|lưu|kiểm tra|tìm|tra|gửi|xóa|xoá|bật|tắt|phát|chụp|dọn)", re.I)
_YESNO_END = re.compile(r"(không|nhé|chứ|nha|được không|ạ)\s*\?\s*$", re.I)
_WH = re.compile(r"\b(nào|gì|sao|ai|bao nhiêu|đâu)\b", re.I)


_WRAP = re.compile(
    r"^(?:thưa ngài,?\s*)?(?:ngài\s+)?(?:có\s+)?(?:muốn|cần|cho phép)\s+tôi\s+|^(?:tôi\s+)?(?:có\s+)?nên\s+|^cho\s+(?:tôi\s+)?phép\s+(?:tôi\s+)?",
    re.I)
_TAIL = re.compile(r"\s*(?:cho ngài)?\s*(?:ngay)?\s*(?:không|nhé|chứ|nha|được không)?\s*(?:ạ|thưa ngài)?\s*\?\s*$", re.I)


def ask_to_command(ask: str) -> str:
    """'Ngài có muốn tôi xem hộp thư Outlook của ngài không ạ?' -> 'xem hộp thư Outlook của ngài'"""
    return _TAIL.sub("", _WRAP.sub("", ask.strip())).strip(" ,.")



def is_actionable(ask: str) -> bool:
    """Spec §4: a single yes/no offer for ONE action (either/or and open questions are rejected)."""
    ask = re.sub(r"[^\w?.!)\"'\s]+$", "", ask.strip()).strip()  # trailing emoji/cues after the '?'
    a = " " + ask.lower() + " "
    return (ask.count("?") == 1 and len(ask) <= 200 and " hay " not in a and " hoặc " not in a
            and bool(_YESNO_END.search(ask)))


def build_variants():
    from engine import prompts
    from engine.prompts.chat import build_chat_system_prompt
    base = build_chat_system_prompt()
    card_old = prompts.load("capabilities")
    i = card_old.index("Trong lượt trả lời này KHÔNG")
    j = card_old.index("ra lệnh trực tiếp.\n") + len("ra lệnh trực tiếp.\n")
    card_new = card_old[:i] + ASK_RULE_IN_CARD + card_old[j:]
    b = base.replace(card_old, card_new).replace("trả lời và gợi ý bước tiếp theo", "trả lời")
    assert b != base and card_new in b and "gợi ý bước tiếp theo" not in b, "prompt pieces moved; update ablation"
    # Match whole blocks only (tag alone on its line): identity.md mentions "<style_rules>" inside a sentence.
    c = re.sub(r"(?m)^<user_preferences>\n.*?\n</user_preferences>\n*", "", b, flags=re.S)
    c = re.sub(r"(?m)^<style_rules>\n.*?\n</style_rules>\n*", "", c, flags=re.S)
    assert "</user_preferences>" not in c and "</style_rules>" not in c
    assert card_new in c and "<soul_rules>" in c and len(b) - len(c) < 2500, "block strip ate more than the two blocks"
    return {"P": base, "A": base + ASK_RULE_TAIL, "B": b, "C": c}


CASES = [  # (kind, text, expected agents) — offer/chat cases of pipeline_probe (TUNE + HELDOUT)
    ("offer", "tôi lười mở notepad quá", {"desktop"}),
    ("offer", "hộp thư đầy quá", {"email"}),
    ("offer", "chán quá không biết hôm nay có tin gì mới", {"search"}),
    ("offer", "lâu rồi chưa nghe nhạc của Đen Vâu", {"media"}),
    ("offer", "không biết tuần này mình có lịch hẹn gì không nhỉ", {"email"}),
    ("offer", "đang muốn viết vài dòng mà lười mở word quá", {"desktop", "office"}),
    ("offer", "không nhớ hôm qua mình đã làm những gì nữa", {"history"}),
    ("offer", "tò mò không biết ngoài kia có game miễn phí nào không", {"search"}),
    ("chat", "cảm ơn nhé", set()),
    ("chat", "tôi đang định tự mở notepad để viết", set()),
    ("chat", "tối nay tôi sẽ tự dọn dẹp máy", set()),
    ("chat", "bạn thấy giọng đọc hôm nay thế nào", set()),
    ("chat", "hôm nay tôi vui lắm", set()),
    ("chat", "hôm qua tôi thức khuya quá", set()),
    ("chat", "bạn nghĩ sao về trí tuệ nhân tạo", set()),
    ("chat", "tôi vừa tự mở excel xong rồi", set()),
    ("chat", "tuần sau tôi sẽ tự cài lại windows", set()),
    ("chat", "bạn nói chuyện dễ thương ghê", set()),
]


async def run_variant(name, system, stats, samples):
    from engine.server.llm_server import call_llm
    from engine.orchestrator.classifier import classify_tasks
    for kind, text, exp in CASES:
        for _ in range(RUNS):
            r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                               stream=False, thinking=False)
            body = r.choices[0].message.content or ""
            m = ASK_RE.search(body)
            rest = ASK_RE.sub("", body)
            s = stats[name]
            s["CLAIM"] += bool(CLAIM_RE.search(rest))
            s["DIRECT_CMD"] += "ra lệnh trực tiếp" in body.lower()
            s["ENDS_Q"] += rest.rstrip().endswith("?")
            s["PARSE"] += (not m) and ("ask_user" in body.lower())
            if not m:
                mark = "PASS" if kind == "chat" else "MISS"
            else:
                ask = " ".join(m.group(1).split())
                if not is_actionable(ask):
                    mark = "OVERASK-TALK" if kind == "chat" else "VAGUE"
                else:
                    agents = {t["agent"] for t in await classify_tasks(ask_to_command(ask), conversation_history=[])}
                    if kind == "chat":
                        mark = "OVERASK-TOOL" if agents else "OVERASK-TALK"
                    else:
                        mark = "PASS" if agents & exp else "WRONG"
                if len(samples[name]) < 6 and mark != "PASS":
                    samples[name].append(f"{mark:12} {text!r:48} -> {ask[:120]}")
            s[f"{kind}:{mark}"] += 1


async def main():
    import json, urllib.request
    from engine.server.llm_server import active_model_key
    req = urllib.request.Request("http://127.0.0.1:8080/props", headers={"Authorization": "Bearer " + os.getenv("LOCAL_API_KEY", "")})
    print(f"model={json.load(urllib.request.urlopen(req, timeout=3)).get('model_path')!r} profile={active_model_key()} runs={RUNS}")
    variants = build_variants()
    stats = {k: Counter() for k in variants}
    samples = {k: [] for k in variants}
    t0 = time.time()
    for name, system in variants.items():
        await run_variant(name, system, stats, samples)
        print(f"  variant {name} done ({time.time() - t0:.0f}s)", flush=True)
    n_off, n_chat = 8 * RUNS, 10 * RUNS
    print(f"\n{'':3} {'offer PASS':>10} {'MISS':>5} {'VAGUE':>5} {'WRONG':>5} | {'chat PASS':>9} {'O-TOOL':>6} {'O-TALK':>6} | "
          f"{'CLAIM':>5} {'DIRECT':>6} {'ENDS?':>5} {'PARSE':>5}")
    for k, s in stats.items():
        print(f"{k:3} {s['offer:PASS']:>7}/{n_off} {s['offer:MISS']:>5} {s['offer:VAGUE']:>5} {s['offer:WRONG']:>5} | "
              f"{s['chat:PASS']:>6}/{n_chat} {s['chat:OVERASK-TOOL']:>6} {s['chat:OVERASK-TALK']:>6} | "
              f"{s['CLAIM']:>5} {s['DIRECT_CMD']:>6} {s['ENDS_Q']:>5} {s['PARSE']:>5}")
    for k, lines in samples.items():
        print(f"\n[{k}] examples of non-PASS")
        for line in lines:
            print("   " + line)

asyncio.run(main())
