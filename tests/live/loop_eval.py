"""Live check of the tool-call loop (spec 2026-09-21, hướng A): real run_orchestrator + classify_tasks +
next_tasks + dispatcher against the running llama.cpp server. Only the agents are stubbed, so nothing
is opened or written. Run: python tests/live/loop_eval.py"""
import sys, io, os, asyncio, logging, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))
logging.disable(logging.CRITICAL)
import engine.orchestrator as orch
from engine.orchestrator import dispatcher, registry

EMAIL = "Ngài có 3 thư mới: 1) Google cảnh báo bảo mật đăng nhập lạ vào tài khoản của ngài; 2) Nebius cập nhật điều khoản dịch vụ; 3) Epic Games gửi biên lai đơn hàng SPX8891234 cho ngài."
SEARCH = "Theo bản tin TK-4471, giá xăng RON95 hôm nay tăng lên 24.850 đồng/lít; báo cáo TK-4472 nhận định xu hướng còn tiếp tục trong tuần tới, ngành vận tải chịu áp lực chi phí."

log = []          # (agent, user_text passed to the agent, silent, history tail)
saved = []        # what the fake notes agent would write


def make_runner(name):
    async def runner(user_text, conversation_history, silent=False, **kw):
        log.append((name, user_text, silent))
        if name == "email":
            return EMAIL
        if name == "search":
            return SEARCH
        if name == "notes":
            body = conversation_history[-1]["content"] if user_text.startswith("lưu lại kết quả: ") else user_text
            saved.append(body)
            return "Đã ghi note: " + body[:60]
        if name == "desktop":
            return f"Đã thực hiện: {user_text}"
        return f"OK {name}"
    return runner


class Ws: pass


async def run(text, hist=None):
    del log[:]; del saved[:]
    delivered = []

    async def fake_deliver(ws, t):
        delivered.append(t)
        return t

    orig = (registry.resolve_runner, dispatcher.record_outcome, orch.deliver)
    registry.resolve_runner = lambda n: make_runner(n)
    dispatcher.record_outcome = lambda *a, **k: (1, "success")
    orch.deliver = fake_deliver
    try:
        res = await orch.run_orchestrator(text, hist or [], Ws())
    finally:
        registry.resolve_runner, dispatcher.record_outcome, orch.deliver = orig
    return res, list(log), list(saved), delivered


async def main():
    ok = tot = 0
    cases = [
        ("kiểm tra email của tôi rồi ghi lại vào note", ["email", "notes"], "SPX8891234"),
        ("xem thư mới rồi lưu nội dung vào ghi chú", ["email", "notes"], "SPX8891234"),
        ("xem giá xăng hôm nay rồi lưu kết quả vào ghi chú", ["search", "notes"], "TK-4471"),
        ("tìm thông tin về RAM DDR5 sau đó ghi note lại giúp tôi", ["search", "notes"], "TK-4471"),
        ("tìm tin tức về AI rồi ghi lại vào note", ["search", "notes"], "TK-4471"),
    ]
    print("--- chains: the note must contain the agent's real report")
    for q, want, token in cases:
        res, lg, sv, dl = await run(q)
        agents = [a for a, _, _ in lg]
        good = agents == want and len(sv) == 1 and token in sv[0]
        ok += good; tot += 1
        print("PASS" if good else "FAIL", q[:46].ljust(48), agents, "| silent:", [s for _, _, s in lg], "| saved has token:", bool(sv and token in sv[0]), "| delivered:", len(dl))
    print("--- independent / single (no chain): agents and streaming mode")
    plain = [
        ("mở Notepad rồi ghi note mua sữa", ["desktop", "notes"], "mua sữa"),
        ("kiểm tra thời tiết và xem email mới giúp tôi", None, None),
        ("kiểm tra email của tôi", ["email"], None),
        ("mở Paint", ["desktop"], None),
    ]
    for q, want, own in plain:
        res, lg, sv, dl = await run(q)
        agents = [a for a, _, _ in lg]
        if want is None:
            good = set(agents) == {"search", "email"}
        else:
            good = agents == want and (own is None or (len(sv) == 1 and own in sv[0]))
        ok += good; tot += 1
        print("PASS" if good else "FAIL", q[:46].ljust(48), agents, "| silent:", [s for _, _, s in lg], "| saved:", [x[:30] for x in sv], "| delivered:", len(dl))
    print(f"integration: {ok}/{tot}")

if __name__ == "__main__":
    asyncio.run(main())
