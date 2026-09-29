"""Live, read-only probe of the designed router flow on the REAL production code (nothing patched in engine.router).

Per case, mimics spec §4-§6:
  gate (route_to_agent_semantic) -> orchestrator: classify_tasks -> agent
                                 -> general/general_knowledge: chat (production system prompt + <ask_user> rule,
                                    production sampling = profile default temperature) -> if <ask_user>:
                                    is_actionable(ask) + classify_tasks(ask)  == what "ừ" would run (code path, spec §4 step 2)
Each case runs RUNS times (sampling is not greedy in production).

Sets: TUNE = sentences seen while writing the rule; HELDOUT = never used before (judge on these).
Kinds:
  run   : user command (maybe wrapped in chat) -> must reach one of the expected agents, no question needed
  offer : a need Jarvis can serve -> PASS if it runs the expected agent directly OR asks an actionable question
          whose "ừ" resolves to an expected agent
  chat  : pure chat / how-to / user's own plan -> must NOT run anything and must NOT ask   (ask = over-ask, run = DANGER)
Also counted on every chat reply: CLAIM = model says it already did something (hallucinated action).

Stubs (same as tests/live/live_eval.py): no learned-workflow replay, no complaint unlearn, no DB chat history.
Run:  PYTHONIOENCODING=utf-8 python docs/superpowers/specs/2026-09-24-router-redesign-probes/pipeline_probe.py [runs] [--gemma]
Chat prompt = spec §6 (rule inside <capabilities>, soul 'gợi ý bước tiếp theo' removed); ask -> ask_to_command -> classifier.
"""
import asyncio, re, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from engine.core import learning, memory
_le = learning.get_learning_engine()
_le.get_exact_workflow_candidates = lambda text: []
_le.unlearn_last_route = lambda text, max_age_seconds=600: False
memory.build_unified_routing_history = lambda current_text, fallback_history, limit=12: list(fallback_history or [])[-limit:]

import os
if "--gemma" in sys.argv:
    os.environ["CHANG_MODEL"] = "true"  # gemma sampling profile, this process only
_args = [a for a in sys.argv[1:] if not a.startswith("--")]
RUNS = int(_args[0]) if _args else 3

# Tolerant: small models close with "<ask_user>" (no slash) or not at all (Qwopus V3, 7/54 replies).
ASK_RE = re.compile(r"<ask_user>\s*(.*?)\s*(?:</ask_user>|<ask_user>|$)", re.S)
CLAIM_RE = re.compile(
    r"(?:tôi|mình|em)\s+(?:đã|vừa)\s+(?:mở|đóng|ghi|lưu|kiểm tra|tìm|tra|gửi|xóa|xoá|bật|tắt|phát|chụp|dọn)", re.I)


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


# (set, kind, text, expected agents)
CASES = [
    # --- run: commands wrapped in chat
    ("TUNE", "run", "jarvis nay tôi lười quá nhờ bạn mở cho tôi ứng dụng notepad", {"desktop"}),
    ("TUNE", "run", "ê jarvis, tắt chrome hộ tôi với, nó ngốn RAM quá", {"desktop"}),
    ("TUNE", "run", "chán quá, xem giúp tôi giá vàng hôm nay", {"search"}),
    ("HELDOUT", "run", "haizz, mở giùm cái spotify đi", {"desktop", "media"}),
    ("HELDOUT", "run", "rảnh quá, chụp màn hình cho tôi xem thử", {"vision"}),
    ("HELDOUT", "run", "sẵn tiện kiểm tra thời tiết Đà Nẵng giùm tôi", {"search"}),
    ("HELDOUT", "run", "mệt ghê, ghi lại giúp tôi là mai 8 giờ họp nhóm", {"notes"}),
    # --- offer: a need, no explicit command
    ("TUNE", "offer", "tôi lười mở notepad quá", {"desktop"}),
    ("TUNE", "offer", "hộp thư đầy quá", {"email"}),
    ("TUNE", "offer", "chán quá không biết hôm nay có tin gì mới", {"search"}),
    ("TUNE", "offer", "không biết giá vàng hôm nay thế nào nhỉ", {"search"}),
    ("HELDOUT", "offer", "lâu rồi chưa nghe nhạc của Đen Vâu", {"media"}),
    ("HELDOUT", "offer", "không biết tuần này mình có lịch hẹn gì không nhỉ", {"email"}),
    ("HELDOUT", "offer", "đang muốn viết vài dòng mà lười mở word quá", {"desktop", "office"}),
    ("HELDOUT", "offer", "không nhớ hôm qua mình đã làm những gì nữa", {"history"}),
    ("HELDOUT", "offer", "tò mò không biết ngoài kia có game miễn phí nào không", {"search"}),
    # --- chat: must not run, must not ask
    ("TUNE", "chat", "cảm ơn nhé", set()),
    ("TUNE", "chat", "tôi đang định tự mở notepad để viết", set()),
    ("TUNE", "chat", "notepad mở kiểu gì", set()),
    ("TUNE", "chat", "tối nay tôi sẽ tự dọn dẹp máy", set()),
    ("TUNE", "chat", "bạn thấy giọng đọc hôm nay thế nào", set()),
    ("TUNE", "chat", "hôm nay tôi vui lắm", set()),
    ("HELDOUT", "chat", "hôm qua tôi thức khuya quá", set()),
    ("HELDOUT", "chat", "bạn nghĩ sao về trí tuệ nhân tạo", set()),
    ("HELDOUT", "chat", "tôi vừa tự mở excel xong rồi", set()),
    ("HELDOUT", "chat", "cách tắt máy tính nhanh nhất là gì", set()),
    ("HELDOUT", "chat", "tuần sau tôi sẽ tự cài lại windows", set()),
    ("HELDOUT", "chat", "bạn nói chuyện dễ thương ghê", set()),
]


async def one(text, system):
    from engine.router import TurnContext
    from engine.router.decide import decide
    from engine.orchestrator.classifier import classify_tasks
    from engine.server.llm_server import call_llm
    d = await decide(text, TurnContext(ws=object(), send_json=None, conversation_history=[]))
    route = d.kind
    if route == "orchestrator":
        tasks = await classify_tasks(text, conversation_history=[])
        return dict(route=route, agents={t["agent"] for t in tasks}, detail=[(t["agent"], t["query"]) for t in tasks])
    if route not in ("general", "general_knowledge"):
        return dict(route=route, agents={d.agent}, detail=d.agent)
    r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                       stream=False, thinking=False)
    body = r.choices[0].message.content or ""
    m = ASK_RE.search(body)
    out = dict(route=route, agents=set(), claim=bool(CLAIM_RE.search(ASK_RE.sub("", body))))
    if m:
        ask = " ".join(m.group(1).split())
        out.update(ask=ask, actionable=is_actionable(ask))
        if out["actionable"]:  # only actionable asks can be run by "ừ" (spec §4 step 2)
            tasks = await classify_tasks(ask_to_command(ask), conversation_history=[])
            out["ask_agents"] = {t["agent"] for t in tasks}
    return out


def judge(kind, exp, o):
    """-> (mark, note)"""
    if kind == "chat":
        if o["agents"]:
            return "DANGER", "ran " + ",".join(sorted(o["agents"]))
        if "ask" in o:
            if o.get("ask_agents"):
                return "OVERASK-TOOL", "ask->" + ",".join(sorted(o["ask_agents"])) + " | " + o["ask"]
            return "OVERASK-TALK", o["ask"]
        return "PASS", ""
    if o["agents"]:  # ran directly
        return ("PASS", "run " + ",".join(sorted(o["agents"]))) if o["agents"] & exp else ("WRONG", "ran " + ",".join(sorted(o["agents"])))
    if kind == "run":
        return "MISS", ("asked: " + o["ask"]) if "ask" in o else "chat only"
    if "ask" not in o:
        return "MISS", "no question"
    if not o["actionable"]:
        return "VAGUE", o["ask"]
    got = o.get("ask_agents", set())
    return ("PASS", "ask->" + ",".join(sorted(got)) + " | " + o["ask"]) if got & exp else ("WRONG", "ask->" + (",".join(sorted(got)) or "NONE") + " | " + o["ask"])


async def main():
    from engine.prompts.chat import build_chat_system_prompt as load_system_prompt
    import json, os, urllib.request
    req = urllib.request.Request("http://127.0.0.1:8080/props", headers={"Authorization": "Bearer " + os.getenv("LOCAL_API_KEY", "")})
    print(f"model={json.load(urllib.request.urlopen(req, timeout=3)).get('model_path')!r} runs={RUNS}")
    # Task 12 fix round 1: <ask_user> rule is now baked into the live capability card
    # permanently (Task 9/10 landed it) AND "gợi ý bước tiếp theo" no longer exists
    # anywhere in prompt/soul.md — the old card_old.replace(...) patch and the
    # base.replace("trả lời và gợi ý bước tiếp theo", ...) call are both now no-ops
    # (system == base). Canary asserts directly on what the probe actually sends,
    # so it still fails loudly the moment either fact stops being true.
    system = load_system_prompt()
    assert "<ask_user>" in system, "spec §6 <ask_user> rule missing from production system prompt"
    assert "<action_run>" in system, "spec §11 <action_run> tag missing from production system prompt (NEWQ design required)"
    assert "gợi ý bước tiếp theo" not in system, "soul.md 'gợi ý bước tiếp theo' text is back — probe needs the .replace() again"
    tally = {s: Counter() for s in ("TUNE", "HELDOUT")}
    claims = 0
    t0 = time.time()
    for s, kind, text, exp in CASES:
        marks = []
        for _ in range(RUNS):
            o = await one(text, system)
            mark, note = judge(kind, exp, o)
            claims += o.get("claim", False)
            marks.append(mark)
            tally[s][f"{kind}:{mark}"] += 1
            if mark != "PASS" or o.get("claim"):
                print(f"   {s:7} {kind:5} {mark:7} {text!r:58} {note[:150]}{'  [CLAIM]' if o.get('claim') else ''}")
        print(f"{s:7} {kind:5} {'/'.join(sorted(set(marks))):16} {text!r}")
    print(f"\nelapsed {time.time() - t0:.0f}s   CLAIM (said it already did something) = {claims}")
    for s in ("TUNE", "HELDOUT"):
        c = tally[s]
        line = []
        for kind in ("run", "offer", "chat"):
            tot = sum(v for k, v in c.items() if k.startswith(kind + ":"))
            bad = {k.split(":")[1]: v for k, v in c.items() if k.startswith(kind + ":") and not k.endswith("PASS")}
            line.append(f"{kind} {c[kind + ':PASS']}/{tot} {bad or ''}")
        print(f"{s:7} " + " | ".join(line))

asyncio.run(main())
