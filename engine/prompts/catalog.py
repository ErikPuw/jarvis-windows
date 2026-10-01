"""Module duy nhất đọc và quản lý danh mục agents & tools từ prompt/tools.md và prompt/agents.md (spec 2026-09-25 mục 1)."""
from pathlib import Path
from engine.orchestrator.registry import AGENT_REGISTRY

_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompt"
_AGENTS_MD_PATH = _PROMPT_DIR / "agents.md"

_AGENTS_CACHE: dict[str, dict] | None = None
_SYSTEM_TOOLS_CACHE: set[str] | None = None
_ALIAS_MAP_CACHE: dict[str, str] | None = None


_SKILLS_AGENTS_DIR = Path(__file__).resolve().parents[2] / "skills" / "agents"


def _parse_skill_md(file_path: Path) -> dict:
    """Parse YAML frontmatter từ file skill.md."""
    try:
        import yaml
        text = file_path.read_text(encoding="utf-8")
        if not text.startswith("---"):
            return {}
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}
        return yaml.safe_load(parts[1]) or {}
    except Exception:
        return {}


def _load_from_skills_dir() -> tuple[dict[str, dict], dict[str, str]] | None:
    """Quét động thư mục skills/agents/*/skill.md nếu tồn tại."""
    if not _SKILLS_AGENTS_DIR.is_dir():
        return None

    agent_dirs = [d for d in _SKILLS_AGENTS_DIR.iterdir() if d.is_dir() and (d / "skill.md").is_file()]
    if not agent_dirs:
        return None

    agents: dict[str, dict] = {}
    alias_map: dict[str, str] = {}

    for adir in sorted(agent_dirs):
        meta = _parse_skill_md(adir / "skill.md")
        if not meta or "name" not in meta:
            continue

        sec_name = meta["name"].strip().lower()
        aliases = [str(a).strip().lstrip("@").lower() for a in meta.get("aliases", []) if a]
        tools = []
        for t in meta.get("tools", []):
            if isinstance(t, dict) and "name" in t:
                tools.append({
                    "name": t["name"],
                    "label": t.get("label", ""),
                    "offer": bool(t.get("offer", False)),
                })

        agents[sec_name] = {
            "aliases": aliases,
            "description": meta.get("description", ""),
            "tools": tools,
        }

        alias_map[sec_name] = sec_name
        alias_map[f"agent_{sec_name}"] = sec_name
        for a in aliases:
            alias_map[a] = sec_name

    return (agents, alias_map) if agents else None


def _load_tools_md():
    global _AGENTS_CACHE, _SYSTEM_TOOLS_CACHE, _ALIAS_MAP_CACHE
    if _AGENTS_CACHE is not None:
        return

    skills_data = _load_from_skills_dir()
    if skills_data is not None:
        _AGENTS_CACHE, _ALIAS_MAP_CACHE = skills_data
        _SYSTEM_TOOLS_CACHE = {"install_extension", "mcp_call"}
        return

    _AGENTS_CACHE = {}
    _SYSTEM_TOOLS_CACHE = {"install_extension", "mcp_call"}
    _ALIAS_MAP_CACHE = {}


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
