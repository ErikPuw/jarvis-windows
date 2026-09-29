"""Solve: kết luận cho mục tiêu từ các báo cáo đã làm sạch (spec 2026-09-26 mục 5.3). Model KHÔNG có tools;
câu trả lời qua sanitize_answer (bỏ thẻ, ảnh, liên kết lạ)."""
import logging

from engine import prompts
from engine.plans.untrusted import frame, sanitize_answer, sources_of
from engine.prompts import persona
from engine.server import llm_server

log = logging.getLogger("jarvis.plans.solver")

FALLBACK = "Tôi chưa tìm được đủ thông tin để gợi ý, thưa ngài."


def build_messages(goal: str, context: str, done: list[dict]) -> list[dict]:
    from engine.prompts import chat
    system = prompts.load("plan_solve", persona_short=persona.short())
    about = chat.about_user_block()
    if about:
        system += "\n\n" + about
    data = "\n".join(frame(i, r) for i, r in enumerate(done, 1)) or "(không có dữ liệu)"
    user = (f"Mục tiêu: {goal}\n\nNgữ cảnh hội thoại gần nhất:\n{context or '(không có)'}\n\n"
            f"Dữ liệu các bước tra cứu:\n{data}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def solve(goal: str, context: str, done: list[dict]) -> str:
    from engine.orchestrator.synthesizer import _restore_tables
    try:
        response = await llm_server.call_llm(
            messages=build_messages(goal, context, done), stream=False, thinking=False, temperature=0.3,
        )
        text = llm_server.strip_think(response.choices[0].message.content or "")
    except Exception as exc:
        log.warning("[PLAN] solver failed: %s", exc)
        return FALLBACK
    if not text.strip():
        return FALLBACK
    text = sanitize_answer(_restore_tables(text, done), sources_of(done))
    return text or FALLBACK
