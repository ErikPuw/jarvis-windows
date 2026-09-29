"""Module duy nhất đọc và quản lý danh mục agents & tools từ prompt/tools.md và prompt/agents.md (spec 2026-09-25 mục 1)."""
from pathlib import Path
from engine.orchestrator.registry import AGENT_REGISTRY

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompt"
_TOOLS_MD_PATH = _PROMPT_DIR / "tools.md"
_AGENTS_MD_PATH = _PROMPT_DIR / "agents.md"

_AGENTS_CACHE: dict[str, dict] | None = None
_SYSTEM_TOOLS_CACHE: set[str] | None = None
_ALIAS_MAP_CACHE: dict[str, str] | None = None


def _load_tools_md():
    global _AGENTS_CACHE, _SYSTEM_TOOLS_CACHE, _ALIAS_MAP_CACHE
    if _AGENTS_CACHE is not None:
        return

    content = _TOOLS_MD_PATH.read_text(encoding="utf-8")
    agents: dict[str, dict] = {}
    system_tools: set[str] = set()
    alias_map: dict[str, str] = {}

    current_section = None
    current_data = None

    for line in content.splitlines():
        line_s = line.strip()
        if not line_s:
            continue

        if line_s.startswith("## @"):
            sec_name = line_s[4:].strip().lower()
            current_section = sec_name
            if sec_name != "system":
                current_data = {
                    "aliases": [],
                    "description": "",
                    "tools": [],
                }
                agents[sec_name] = current_data
                alias_map[sec_name] = sec_name
                # Tự động hỗ trợ tiền tố agent_
                alias_map[f"agent_{sec_name}"] = sec_name
            else:
                current_data = None
            continue

        if current_section == "system":
            if line_s.startswith("- "):
                parts = [p.strip() for p in line_s[2:].split("|")]
                tool_name = parts[0]
                system_tools.add(tool_name)
            continue

        if current_data is not None:
            if line_s.lower().startswith("alias:"):
                raw_aliases = line_s.split(":", 1)[1]
                for a in raw_aliases.split(","):
                    a_clean = a.strip().lstrip("@").lower()
                    if a_clean:
                        current_data["aliases"].append(a_clean)
                        alias_map[a_clean] = current_section
            elif line_s.startswith("- "):
                parts = [p.strip() for p in line_s[2:].split("|")]
                tool_name = parts[0]
                label = parts[1] if len(parts) > 1 else ""
                offer = parts[2].lower() == "offer" if len(parts) > 2 else False
                current_data["tools"].append({
                    "name": tool_name,
                    "label": label,
                    "offer": offer,
                })
            else:
                if not current_data["description"]:
                    current_data["description"] = line_s
                else:
                    current_data["description"] += " " + line_s

    _AGENTS_CACHE = agents
    _SYSTEM_TOOLS_CACHE = system_tools
    _ALIAS_MAP_CACHE = alias_map


def agents() -> dict[str, dict]:
    """Trả về danh mục agents: {tên: {'aliases': [...], 'description': '...', 'tools': [...]}}."""
    _load_tools_md()
    return _AGENTS_CACHE


def agent_names_text() -> str:
    """"Agent Desktop, Agent Email, …" — chỉ tên, để chat trả lời khi ngài hỏi hệ thống có những agent nào."""
    return ", ".join("Agent " + name.replace("_", " ").title() for name in agents())


def system_tools() -> set[str]:
    """Trả về tập hợp các tool hệ thống không thuộc agent nào."""
    _load_tools_md()
    return _SYSTEM_TOOLS_CACHE


def resolve_alias(name: str) -> str | None:
    """Trả về tên agent thật trong AGENT_REGISTRY từ alias hoặc tên gốc (hỗ trợ có hoặc không có @)."""
    if not name:
        return None
    _load_tools_md()
    cleaned = name.strip().lstrip("@").lower()
    # Thử tra trong alias_map
    if cleaned in _ALIAS_MAP_CACHE:
        target = _ALIAS_MAP_CACHE[cleaned]
        return target if target in AGENT_REGISTRY else None
    # Thử bỏ tiền tố agent_
    stripped = cleaned.removeprefix("agent_")
    if stripped in AGENT_REGISTRY:
        return stripped
    if stripped in _ALIAS_MAP_CACHE:
        target = _ALIAS_MAP_CACHE[stripped]
        return target if target in AGENT_REGISTRY else None
    return None


def offerable_tools() -> dict[str, tuple[str, str]]:
    """Trả về {tool: (agent, nhãn)} cho các tool có cờ offer."""
    _load_tools_md()
    offers = {}
    for agent_name, info in _AGENTS_CACHE.items():
        for t in info["tools"]:
            if t["offer"]:
                offers[t["name"]] = (agent_name, t["label"])
    return offers


def tool_list_text() -> str:
    """Chuỗi danh sách tool cho prompt format: tool (nhãn). Chế độ mục tiêu không nằm ở đây: chỉ vào bằng
    lệnh @plans (2026-09-27 — đề nghị plan_goal qua chat làm model đề nghị lung tung)."""
    return ", ".join(f"{tool} ({label})" for tool, (_, label) in offerable_tools().items())


def agent_criteria() -> str:
    """Trả về text tiêu chí cho classifier từ prompt/agents.md."""
    return _AGENTS_MD_PATH.read_text(encoding="utf-8").strip()


def all_tools() -> list[str]:
    """Danh sách tất cả các tool thuộc agent."""
    _load_tools_md()
    res = []
    for info in _AGENTS_CACHE.values():
        for t in info["tools"]:
            res.append(t["name"])
    return res


def tool_to_agent_map() -> dict[str, str]:
    """Map {tool_name: agent_name}."""
    _load_tools_md()
    m = {}
    for agent_name, info in _AGENTS_CACHE.items():
        for t in info["tools"]:
            m[t["name"]] = agent_name
    return m
