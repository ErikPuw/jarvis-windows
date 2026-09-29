"""Plan / Replan: model chọn đích + viết câu tra cứu dưới dạng JSON ràng buộc schema; code kiểm tra lại
(spec 2026-09-26 mục 5.2). Model KHÔNG nhận tools."""
import logging

from engine import prompts
from engine.core.json_parser import safe_json_loads
from engine.plans import MAX_QUERY_CHARS, MAX_STEPS_PER_ROUND, PLAN_TARGETS
from engine.plans.untrusted import frame, query_ok
from engine.prompts import catalog, persona
from engine.server import llm_server

log = logging.getLogger("jarvis.plans.planner")

# llama.cpp ép đầu ra theo schema (grammar): đích chỉ có thể là một trong PLAN_TARGETS.
SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "maxItems": MAX_STEPS_PER_ROUND,
                "items": {
                    "type": "object",
                    "properties": {
                        "target": {"type": "string", "enum": list(PLAN_TARGETS)},
                        "query": {"type": "string", "maxLength": MAX_QUERY_CHARS},
                    },
                    "required": ["target", "query"],
                },
            },
        },
        "required": ["steps"],
    },
}


def _normalize(query: str) -> str:
    return " ".join(str(query).lower().split())


def _targets_text() -> str:
    """Mô tả đích lấy từ prompt/tools.md (không dùng tiêu chí classifier). Đích "web" nằm cố định trong prompt."""
    agents = catalog.agents()
    return "\n".join(f"- {target}: {agents[agent]['description']}"
                     for target, (agent, tools) in PLAN_TARGETS.items() if tools is None)


def build_messages(goal: str, context: str, done: list[dict]) -> list[dict]:
    # Không đưa <about_user> cho planner: được xem sở thích thì nó nhét vào câu tra cứu gửi ra web (máy thật
    # 2026-09-27). Prompt chỉ báo sở thích đã lưu và solver sẽ dùng.
    system = prompts.load("plan_planner", persona_short=persona.short(), targets=_targets_text())
    if done:
        steps = "Các bước đã làm:\n" + "\n".join(frame(i, r) for i, r in enumerate(done, 1))
    else:
        steps = "Chưa có bước nào được thực hiện."
    user = f"Mục tiêu: {goal}\n\nNgữ cảnh hội thoại gần nhất:\n{context or '(không có)'}\n\n{steps}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def next_steps(goal: str, context: str, done: list[dict]) -> list[dict]:
    """[{"target","query"}] cho vòng tiếp theo; [] = dừng (đủ thông tin, hoặc lỗi — không bao giờ ném)."""
    content = ""
    try:
        response = await llm_server.call_llm(
            messages=build_messages(goal, context, done), stream=False, thinking=False,
            temperature=0.0, max_tokens=300, response_format=SCHEMA,
        )
        content = response.choices[0].message.content or ""
        data = safe_json_loads(content)
    except Exception as exc:
        log.warning("[PLAN] planner failed: %s", exc)
        return []
    raw = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        log.warning("[PLAN] planner returned no steps list: %r", content[:200])
        return []
    seen = {(r.get("agent"), _normalize(r.get("query", ""))) for r in done}
    steps = []
    for step in raw:
        if not isinstance(step, dict):
            continue
        target, query = step.get("target"), step.get("query")
        if target not in PLAN_TARGETS or not query_ok(query):
            log.info("[PLAN] step rejected: %r", step)
            continue
        query = " ".join(query.split())
        key = (PLAN_TARGETS[target][0], _normalize(query))
        if key in seen:
            continue
        seen.add(key)
        steps.append({"target": target, "query": query})
        if len(steps) == MAX_STEPS_PER_ROUND:
            break
    return steps
