"""Live (read-only): đo prompt chat production (khối <offer_protocol>, 2026-09-25).
Trước khi áp dụng (PROD cũ, 3 lượt): offer PASS 20/27, overask 1/30, app OK 0/15, QOUT 11, PAREN 1.
INLINE = thẻ <ask_user> chỉ bọc câu lệnh (không có '?'), dạng user chốt 2026-09-25.
Offer: PASS = thẻ đủ, tool đúng, câu hỏi dùng được (như action_run_probe NEWQ).
Chỉ số thêm (trên các lượt có thẻ):
  QOUT   = có câu xin phép nằm ngoài thẻ trước <ask_user> (ngài thấy hỏi 2 lần)
  UNTAG_PERM = xin phép bằng lời thường, không có thẻ (case đề nghị/app)
  PAREN  = câu trong <ask_user> có ngoặc (dịch tên + chú thích)
  APPBAD = case mở app: extract_app_name(ask_to_command(ask)) không phải tên gốc
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/offer_protocol_probe.py [runs]
"""
import asyncio, re, sys, time
from collections import Counter
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from tests.live.probes.action_run_probe import CASES, CLAIM_RE, TAG_RE
from engine.prompts.catalog import offerable_tools
OFFERABLE_TOOLS = offerable_tools()
from engine.router.ask_user import ask_to_command as _cmd, extract, extract_action, is_actionable


def judge(kind, exp, body, _variant=None):
    """Chấm bằng đúng logic production (engine.router.ask_user)."""
    _, ask = extract(body)
    tagged = "<ask_user>" in body or "<action_run>" in body
    if kind == "chat":
        return ("OVERASK", ask) if tagged else ("PASS", "")
    if not ask:
        return "MISS", ""
    tool = extract_action(body)
    if tool not in OFFERABLE_TOOLS:
        return "BADTOOL", ask
    if tool not in exp:
        return "WRONGTOOL", f"{ask} | {tool}"
    cmd = _cmd(ask)
    if not is_actionable(ask) or len(cmd.split()) < 2:
        return "VAGUE", ask
    return "PASS", cmd

APP_CASES = [  # (câu, tên gốc chấp nhận được sau extract_app_name)
    ("tôi lười mở notepad quá", {"notepad"}),
    ("đang muốn tính mấy con số mà lười mở máy tính bỏ túi quá", {"calculator"}),
    ("muốn viết code mà lười mở vscode ghê", {"vscode", "vs code", "visual studio code", "code"}),
    ("lười mở word quá", {"word", "microsoft word"}),
    ("lười mở trình duyệt chrome ghê", {"chrome", "google chrome"}),
]

def build_prompts():
    from engine.prompts.chat import build_chat_system_prompt
    return {"PROD": build_chat_system_prompt()}


# Câu xin phép (không phải câu cảm thán "hộp thư đầy hả ngài?")
PERM_Q = re.compile(r"(?:muốn|có nên|cho phép|để)\s+tôi[^?.!]*\?|tôi có thể[^?.!]*\?", re.I)


def fmt_marks(body):
    i = body.find("<ask_user>")
    m = re.search(r"<ask_user>\s*(.*?)\s*(?:</ask_user>|<action_run>|$)", body, re.S)
    ask = " ".join(m.group(1).split()) if m else ""
    return bool(PERM_Q.search(body[:i])), ("(" in ask), ask


async def main():
    from engine.server.llm_server import call_llm
    from engine.router.ask_user import ask_to_command
    from engine.tools.desktop_automation import extract_app_name
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = int(args[0]) if args else 2
    t0 = time.time()

    async def ask_llm(system, text):
        r = await call_llm(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                           stream=False, thinking=False)
        return r.choices[0].message.content or ""

    for name, system in build_prompts().items():
        c, ex = Counter(), []
        for kind, text, exp in CASES:
            for _ in range(runs):
                body = await ask_llm(system, text)
                mark, note = judge(kind, exp, body, "PROD")
                c[f"{kind}:{mark}"] += 1
                c["CLAIM"] += bool(CLAIM_RE.search(TAG_RE.sub("", body)))
                if kind == "offer" and "<ask_user>" not in body and PERM_Q.search(body):
                    c["UNTAG_PERM"] += 1
                if "<ask_user>" in body:
                    c["tagged"] += 1
                    qout, paren, _ = fmt_marks(body)
                    c["QOUT"] += qout
                    c["PAREN"] += paren
                    c["INLINE"] += "?" not in extract(body)[1]
                    if qout and len(ex) < 6:
                        ex.append("QOUT  " + " ".join(body.split())[:200])
        for text, names in APP_CASES:
            for _ in range(runs):
                body = await ask_llm(system, text)
                if "<ask_user>" not in body:
                    c["app:MISS"] += 1
                    c["UNTAG_PERM"] += bool(PERM_Q.search(body))
                    continue
                c["tagged"] += 1
                qout, paren, ask = fmt_marks(body)
                c["QOUT"] += qout
                c["PAREN"] += paren
                app = (extract_app_name(ask_to_command(ask)) or "").lower()
                ok = app in names
                c["app:OK" if ok else "app:APPBAD"] += 1
                if not ok and len(ex) < 12:
                    ex.append(f"APPBAD {text!r} -> ask={ask!r} app={app!r}")
        n_off, n_chat, n_app = 9 * runs, 10 * runs, len(APP_CASES) * runs
        grp = lambda p: ", ".join(f"{k.split(':')[1]}={v}" for k, v in sorted(c.items()) if k.startswith(p))
        print(f"\n[{name}] ({time.time() - t0:.0f}s) offer: {grp('offer:')} (/{n_off}) | chat: {grp('chat:')} (/{n_chat})"
              f" | app: {grp('app:')} (/{n_app}) | tagged={c['tagged']} INLINE={c['INLINE']} QOUT={c['QOUT']} PAREN={c['PAREN']} UNTAG_PERM={c['UNTAG_PERM']} CLAIM={c['CLAIM']}")
        for line in ex:
            print("   " + line)


if __name__ == "__main__":
    asyncio.run(main())
