"""Vòng lặp chế độ mục tiêu: Plan → Execute → Replan → Solve (spec 2026-09-26 mục 5.4).
Mọi bước chạy silent; chỉ deliver() gửi câu trả lời, đúng một lần."""
import logging

from engine.orchestrator import dispatcher, synthesizer
from engine.plans import (
    CONTEXT_CHARS, CONTEXT_MESSAGES, MAX_ROUNDS, MAX_TOTAL_STEPS, PLAN_TARGETS, STEP_TIMEOUT_S,
    planner, solver,
)
from engine.plans.untrusted import clean, looks_injected

log = logging.getLogger("jarvis.plans.runner")

_INJECTED = "Nội dung bước này bị loại vì có dấu hiệu chèn lệnh."
_ROLE = {"user": "Người dùng", "assistant": "Jarvis"}


def _context(history) -> str:
    """Tối đa CONTEXT_MESSAGES tin user/assistant gần nhất, bỏ câu trả lời hiện tại ("ừ"), đã làm sạch."""
    msgs = [m for m in (history or []) if m.get("role") in _ROLE and str(m.get("content") or "").strip()]
    if msgs and msgs[-1]["role"] == "user":
        msgs = msgs[:-1]
    return "\n".join(f"{_ROLE[m['role']]}: {clean(m['content']).strip()[:CONTEXT_CHARS]}"
                     for m in msgs[-CONTEXT_MESSAGES:])


def _guard(result: dict) -> dict:
    """Làm sạch báo cáo; nghi chèn lệnh → thay bằng câu loại bỏ và đánh failed (mục 7, lớp 3–4)."""
    r = dict(result)
    text = clean(r.get("result", ""))
    if looks_injected(text):
        log.warning("[PLAN] injection suspected in %s report, dropped: %r", r.get("agent"), text[:160])
        r.update(result=_INJECTED, status="failed")
    else:
        r["result"] = text
    return r


async def run_plan(goal: str, ctx) -> str:
    context = _context(ctx.conversation_history)
    done: list[dict] = []
    for round_no in range(1, MAX_ROUNDS + 1):
        room = MAX_TOTAL_STEPS - len(done)
        if room <= 0:
            break
        steps = (await planner.next_steps(goal, context, done))[:room]
        if not steps:
            break
        tasks, targets = [], {}
        for step in steps:
            agent, tools = PLAN_TARGETS[step["target"]]
            task = {"agent": agent, "query": step["query"]}
            if tools:
                task["runner_kwargs"] = {"tools": list(tools)}
            tasks.append(task)
            targets[(agent, step["query"])] = step["target"]
        log.info("[PLAN] round=%d steps=%s", round_no, steps)
        async with ctx.flow_tracker.step(f"Kế hoạch vòng {round_no}"):
            results = await dispatcher.dispatch_tasks(
                tasks, user_text=goal, conversation_history=ctx.conversation_history, ws=ctx.ws,
                flow_tracker=ctx.flow_tracker, flow_agents=ctx.flow_agents,
                silent=True, step_timeout=STEP_TIMEOUT_S,
            )
        if not results:
            break
        round_done = []
        for result in results:
            r = _guard(result)
            r["target"] = targets.get((r.get("agent"), r.get("query")), r.get("agent"))
            round_done.append(r)
        done.extend(round_done)
        if not any(r.get("status") == "success" for r in round_done):
            # Cả vòng không bước nào thành công: lập lại chỉ đổi câu chữ rồi hỏng tiếp (máy thật 2026-09-27).
            log.info("[PLAN] round=%d had no successful step, stop replanning", round_no)
            break
    if not done:
        log.info("[PLAN] no step ran for %r, handing back to chat", goal[:120])
        return ""
    text = await solver.solve(goal, context, done)
    log.info("[PLAN] done total=%d ok=%d", len(done), sum(1 for r in done if r.get("status") == "success"))
    return await synthesizer.deliver(ctx.ws, text)
