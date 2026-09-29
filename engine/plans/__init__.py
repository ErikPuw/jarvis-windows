"""Chế độ mục tiêu: Plan → Execute → Replan → Solve (docs/superpowers/specs/2026-09-26-goal-plans-design.md).
Cửa vào duy nhất: lệnh "@plans <mục tiêu>" (engine/router/fast_paths.plan_mention, 2026-09-27).
File này chỉ chứa hằng số, không import module nặng ở đây."""

# Đích planner được chọn → (agent trong AGENT_REGISTRY, tools bắt buộc hoặc None). Chỉ đích ĐỌC.
PLAN_TARGETS: dict[str, tuple[str, list[str] | None]] = {
    "search": ("search", None),
    "web": ("search", ["web_research"]),
    "history": ("history", None),
}

MAX_ROUNDS = 3
MAX_STEPS_PER_ROUND = 3
MAX_TOTAL_STEPS = 5
STEP_TIMEOUT_S = 60
REPORT_CHARS = 1500
MAX_QUERY_CHARS = 120
CONTEXT_MESSAGES = 4
CONTEXT_CHARS = 300
