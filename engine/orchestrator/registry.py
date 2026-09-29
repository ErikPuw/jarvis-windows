"""Central agent registry — single source of truth for route name -> agent
module/runner. Replaces both AGENT_MULTI_TOOLS (the old route_agents.py) and
the importlib dispatch block that used to live in execute_agent_route.

THÊM AGENT MỚI: xem README.md, mục "Thêm agent mới". Tóm tắt các chỗ phải sửa:
registry này + prompt/tools.md (tên @, mô tả, tool) + prompt/agents.md (tiêu chí)
+ commands/<tool>.md, rồi cập nhật tests/golden/classifier_tools.json và
EXPECTED_AGENT_CRITERIA trong tests/test_prompts_catalog.py. Khởi động lại JARVIS."""

import importlib
import logging

log = logging.getLogger("jarvis.orchestrator.registry")

AGENT_REGISTRY: dict[str, dict[str, str]] = {
    "goose":       {"module": "engine.agents.agent_goose",    "runner": "run_goose_agent"},
    "office":      {"module": "engine.agents.agent_office",   "runner": "run_office_agent"},
    "email":       {"module": "engine.agents.agent_email",    "runner": "run_email_agent"},
    "desktop":     {"module": "engine.agents.agent_desktop",  "runner": "run_desktop_agent"},
    "search":      {"module": "engine.agents.agent_search",   "runner": "run_search_agent"},
    "vietlott":    {"module": "engine.agents.agent_vietlott", "runner": "run_vietlott_agent"},
    "vision":      {"module": "engine.agents.agent_vision",   "runner": "run_vision_agent"},
    "webcam":      {"module": "engine.agents.agent_webcam",   "runner": "run_webcam_agent"},
    "media":       {"module": "engine.agents.agent_media",    "runner": "run_media_agent"},
    "history":     {"module": "engine.agents.agent_history",  "runner": "run_history_agent"},
    "notes":       {"module": "engine.agents.agent_notes",    "runner": "run_notes_agent"},
    "project":     {"module": "engine.agents.agent_project",  "runner": "run_project_agent"},
    "security":    {"module": "engine.agents.agent_security", "runner": "run_security_agent"},
    "image":       {"module": "engine.agents.agent_image",    "runner": "run_image_agent"},
    "legal":       {"module": "engine.agents.agent_legal",    "runner": "run_legal_agent"},
    "win_control": {"module": "engine.agents.agent_control",  "runner": "run_control_agent"},
    "rag":         {"module": "engine.agents.agent_rag",      "runner": "run_rag_agent"},
    "dream":       {"module": "engine.agents.agent_dream",    "runner": "run_dream_agent"},
}


def resolve_runner(agent_name: str, registry: dict = AGENT_REGISTRY):
    """Import and return the runner callable for agent_name, or None if the
    agent isn't registered."""
    entry = registry.get(agent_name)
    if entry is None:
        return None
    module = importlib.import_module(entry["module"])
    return getattr(module, entry["runner"])


def self_check(registry: dict = AGENT_REGISTRY) -> list[str]:
    """Import every registry entry and verify its runner exists. Returns a
    list of error strings; empty list means every entry resolves cleanly."""
    errors = []
    for agent_name, entry in registry.items():
        try:
            module = importlib.import_module(entry["module"])
        except Exception as exc:
            errors.append(f"{agent_name}: cannot import {entry['module']} ({exc})")
            continue
        if not hasattr(module, entry["runner"]):
            errors.append(f"{agent_name}: {entry['module']} has no attribute {entry['runner']}")
    return errors


if __name__ == "__main__":
    problems = self_check()
    if problems:
        for p in problems:
            print(f"FAIL: {p}")
        raise SystemExit(1)
    print(f"OK: all {len(AGENT_REGISTRY)} registry entries resolve")
