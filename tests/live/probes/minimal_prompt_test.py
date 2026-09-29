"""Short test: does the SYSTEM PROMPT make the model misbehave on <ask_user>?
Same model, same sentences, same sampling — three prompts:
  R  rule only       : capability list + ask rule, nothing else (no persona, no system rules)
  M2 minimal persona + simpler rule with ONE format example (no 'có/không', 'việc và đối tượng' to parrot)
  M  minimal persona : R + 2 hard lines (Vietnamese, xưng "tôi", gọi "ngài")
  S  system prompt   : full production prompt with the spec §6 fix (variant B of prompt_ablation)
  S2 S with the M2 rule (one format example) in place of the §6 rule
Scoring, parser, is_actionable, ask_to_command are reused from prompt_ablation.py (single source).
Run: PYTHONIOENCODING=utf-8 python .../minimal_prompt_test.py [runs] [--gemma]
"""
import asyncio, os, re, time
from collections import Counter
p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt_ablation.py")
src = open(p, encoding="utf-8").read().replace("asyncio.run(main())", "")
A = {"__file__": p, "__name__": "abl"}
exec(compile(src, p, "exec"), A)

CAPS = ("Hệ thống làm được khi được đồng ý: mở/đóng ứng dụng; xem email và lịch Outlook; tra thời tiết, tin tức, giá vàng/xăng/tỷ giá, "
        "lịch chiếu phim, game miễn phí; chụp màn hình; mở nhạc, phim, video; ghi chú; xem lại lịch sử trò chuyện.")
R = CAPS + "\n" + A["ASK_RULE_IN_CARD"]
M = "Bạn là JARVIS, trợ lý của ngài. Luôn trả lời bằng tiếng Việt, ngắn gọn; xưng \"tôi\", gọi người dùng là \"ngài\".\n\n" + R
RULE2 = ("Bạn chưa làm gì cả. Nếu một việc trong danh sách trên giúp được ngài ngay lúc này, cuối câu trả lời hãy hỏi xin phép đúng "
         # Example topic must NOT appear in CASES (a Notepad example contaminated the notepad cases: 3/3 copied).
         "một việc bằng thẻ, ví dụ: <ask_user>Ngài có muốn tôi xem thời tiết hôm nay không?</ask_user>\n"
         "Chỉ trò chuyện, hỏi cách tự làm, hoặc việc ngài tự làm thì không dùng thẻ. Cần hỏi thêm thông tin thì hỏi bình thường, không dùng thẻ.\n")
M2 = M.replace(A["ASK_RULE_IN_CARD"], RULE2)
assert M2 != M

CASES = [  # shorter set: 4 offer + 6 chat
    ("offer", "tôi lười mở notepad quá", {"desktop"}),
    ("offer", "hộp thư đầy quá", {"email"}),
    ("offer", "lâu rồi chưa nghe nhạc của Đen Vâu", {"media"}),
    ("offer", "tò mò không biết ngoài kia có game miễn phí nào không", {"search"}),
    ("chat", "cảm ơn nhé", set()),
    ("chat", "tôi đang định tự mở notepad để viết", set()),
    ("chat", "bạn thấy giọng đọc hôm nay thế nào", set()),
    ("chat", "hôm qua tôi thức khuya quá", set()),
    ("chat", "tôi vừa tự mở excel xong rồi", set()),
    ("chat", "bạn nói chuyện dễ thương ghê", set()),
]
BAN = re.compile(r"\bbạn\b", re.I)  # identity hard rule: never call the user "bạn"


async def main():
    from engine.server.llm_server import call_llm, active_model_key
    from engine.orchestrator.classifier import classify_tasks
    S = A["build_variants"]()["B"]
    S2 = S.replace(A["ASK_RULE_IN_CARD"], RULE2)  # system prompt + simpler rule with one format example
    assert S2 != S and "<ask_user>Ngài có muốn tôi xem thời tiết hôm nay không?</ask_user>" in S2
    assert not any("thời tiết" in text for _, text, _ in CASES), "example topic leaks into the test set"
    variants = {"R": R, "M": M, "M2": M2, "S": S, "S2": S2}
    runs = A["RUNS"]
    print(f"profile={active_model_key()} runs={runs}  prompt chars: " + ", ".join(f"{k}={len(v)}" for k, v in variants.items()))
    t0 = time.time()
    rows, examples = {}, {}
    for name, system in variants.items():
        c, ex = Counter(), []
        for kind, text, exp in CASES:
            for _ in range(runs):
                r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                                   stream=False, thinking=False)
                body = r.choices[0].message.content or ""
                m = A["ASK_RE"].search(body)
                c["BAN"] += bool(BAN.search(A["ASK_RE"].sub("", body)))
                c["CLAIM"] += bool(A["CLAIM_RE"].search(A["ASK_RE"].sub("", body)))
                c["WELLFORMED"] += "</ask_user>" in body
                c["TAGGED"] += bool(m)
                if not m:
                    mark = "PASS" if kind == "chat" else "MISS"
                    ask = ""
                else:
                    ask = " ".join(m.group(1).split())
                    if not A["is_actionable"](ask):
                        mark = "OVERASK-TALK" if kind == "chat" else "VAGUE"
                    else:
                        agents = {t["agent"] for t in await classify_tasks(A["ask_to_command"](ask), conversation_history=[])}
                        mark = ("OVERASK-TOOL" if agents else "OVERASK-TALK") if kind == "chat" else ("PASS" if agents & exp else "WRONG")
                c[f"{kind}:{mark}"] += 1
                if mark != "PASS" and len(ex) < 5:
                    ex.append(f"{mark:12} {text!r:44} -> {ask[:110]}")
        rows[name], examples[name] = c, ex
        print(f"  {name} done ({time.time() - t0:.0f}s)", flush=True)
    no, nc = 4 * runs, 6 * runs
    print(f"\n{'':2} {'offer OK':>9} {'MISS':>4} {'VAGUE':>5} {'WRONG':>5} | {'chat OK':>8} {'O-TOOL':>6} {'O-TALK':>6} | "
          f"{'tag ok </>':>10} {'CLAIM':>5} {'gọi bạn':>7}")
    for k, c in rows.items():
        print(f"{k:2} {c['offer:PASS']:>6}/{no} {c['offer:MISS']:>4} {c['offer:VAGUE']:>5} {c['offer:WRONG']:>5} | "
              f"{c['chat:PASS']:>5}/{nc} {c['chat:OVERASK-TOOL']:>6} {c['chat:OVERASK-TALK']:>6} | "
              f"{c['WELLFORMED']:>5}/{c['TAGGED']:<4} {c['CLAIM']:>5} {c['BAN']:>7}")
    for k, ex in examples.items():
        print(f"\n[{k}]")
        for line in ex:
            print("   " + line)

asyncio.run(main())
