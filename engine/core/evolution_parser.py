# -*- coding: utf-8 -*-
"""Parser tách kết quả LLM từ Evolution Engine thành 2 track riêng biệt."""
import logging
from typing import Any

log = logging.getLogger("jarvis.evolution_parser")


def _extract_block(content: str, marker: str) -> str:
    """Lấy nội dung sau marker cho tới hết chuỗi (hoặc hết content)."""
    if marker not in content:
        return ""
    return content.split(marker, 1)[1].strip()


def _split_by_block(content: str) -> dict[str, str]:
    """Tách content thành dict theo thứ tự marker: ROUTING_RULES, STYLE_RULES.

    Vì STYLE_RULES nằm cuối, block sau marker đầu tiên cần được tách tiếp
    bởi marker thứ hai.
    """
    blocks: dict[str, str] = {}
    if "ROUTING_RULES:" in content:
        after_routing, _, rest = content.partition("ROUTING_RULES:")
        blocks["routing_rules"] = rest.split("STYLE_RULES:", 1)[0].strip() if "STYLE_RULES:" in rest else rest.strip()
        blocks["style_rules"] = _extract_block(rest, "STYLE_RULES:")
    return blocks


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Bỏ dòng mở ```markdown/```json
        lines = lines[1:] if len(lines) > 1 else []
        text = "\n".join(lines).strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return text


def parse_evolution_response(content: str) -> dict[str, Any]:
    """Parse phản hồi LLM thành {'need_evolution', 'reason', 'routing_rules', 'style_rules'}."""
    result = {"need_evolution": False, "reason": "", "routing_rules": "", "style_rules": ""}
    if not content:
        return result

    decision_part = content.split("DECISION_JSON:", 1)[1] if "DECISION_JSON:" in content else content
    decision_json_str = decision_part.split("ROUTING_RULES:", 1)[0].strip()

    from engine.core.json_parser import safe_json_loads
    parsed = safe_json_loads(decision_json_str)
    if isinstance(parsed, dict):
        result["need_evolution"] = bool(parsed.get("need_evolution", False))
        result["reason"] = str(parsed.get("reason", ""))

    blocks = _split_by_block(content)
    routing = _strip_fences(blocks.get("routing_rules", ""))
    style = _strip_fences(blocks.get("style_rules", ""))
    result["routing_rules"] = routing
    result["style_rules"] = style
    return result
