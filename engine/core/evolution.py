# -*- coding: utf-8 -*-
"""
JARVIS Evolution Engine — Quản lý tiến hóa hành vi và prompt động.

Đọc Learning.md/Preferences.md, tách bài học thành 2 track:
- STYLE: cách Jarvis nói/hành xử trong chat (giọng điệu, emoji, và cả các quy tắc
  hành vi phát ngôn như "không nói đang dùng công cụ khi chỉ đang chat thường").
  Ghi thẳng vào skills/self_evolution/STYLE.md — file này ĐƯỢC nạp vào system
  prompt mỗi lượt chat (engine/prompts/chat.py), nên chỉ chứa nội dung an toàn để chat
  model tự do diễn giải: sai chỉ làm câu trả lời dở hơn, không làm gãy routing.
- ROUTING: agent nào nên xử lý loại yêu cầu nào. KHÔNG có file "SKILL.md" sống
  nữa — engine/router (gate) và orchestrator/classifier.py (chọn agent) đã đo
  thực nghiệm rằng tiêm luật routing tự sinh vào đó làm giảm độ chính xác định
  tuyến (spec 2026-09-21: mất 7/53 route đúng). Nên ROUTING chỉ được ghi vào
  data/wiki/System/Evolution.md dưới dạng ĐỀ XUẤT chờ người duyệt — không nơi
  nào trong hệ thống tự động đọc và áp dụng nó.
"""

import asyncio
import difflib
import logging
import os
import re
from pathlib import Path
from engine.server.llm_server import call_llm
from engine.core.evolution_parser import parse_evolution_response

log = logging.getLogger("jarvis.evolution")

PROJECT_ROOT = Path(__file__).parent.parent.parent

STYLE_FILE = PROJECT_ROOT / "skills" / "self_evolution" / "STYLE.md"
EVOLUTION_LOG = PROJECT_ROOT / "data" / "wiki" / "System" / "Evolution.md"

# Chỉ 1 vòng tiến hóa được ghi file cùng lúc — tránh 2 lượt idle gần nhau
# đọc cùng bản STYLE.md/Evolution.md cũ rồi ghi đè chồng lên nhau.
_evolution_lock = asyncio.Lock()

# ponytail: in-memory, so one extra run after each restart; persist to disk if that ever matters.
_last_inputs: tuple[str, str] | None = None


def _write_text_atomic(path: Path, content: str) -> None:
    """Write `content` to `path` atomically (temp file + os.replace).

    engine/prompts/chat.py re-reads STYLE.md on every single LLM call — a crash
    mid-write with a plain write_text() would leave a truncated file fed
    straight into every subsequent request's system prompt.
    """
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(str(tmp_path), str(path))


_MAX_RULE_BULLETS = 6
_MAX_RULE_CHARS = 900


def _cap_rules(text: str) -> str:
    """Hard limit for rule files that are re-read into prompts on every call:
    the "4-6 bullets" ask in the LLM prompt is only a request. Keeps the
    header, drops duplicate bullets, then at most 6 bullets / 900 chars."""
    head, bullets, seen = [], [], set()
    for line in text.splitlines():
        if line.lstrip().startswith("- "):
            key = re.sub(r"\W+", " ", line).strip().lower()
            if key not in seen:
                seen.add(key)
                bullets.append(line.rstrip())
        else:
            head.append(line)
    kept, size = [], 0
    for b in bullets[:_MAX_RULE_BULLETS]:
        if size + len(b) > _MAX_RULE_CHARS:
            break
        kept.append(b)
        size += len(b)
    return "\n".join(head).rstrip() + ("\n" + "\n".join(kept) if kept else "") + "\n"


_MAX_INPUT_ENTRIES = 20


def _newest_entries(text: str, limit: int = _MAX_INPUT_ENTRIES) -> str:
    """Learning.md/Preferences.md grow with the DB; feed evolution only the
    newest `limit` "- [`key`] ..." entries (DB order is oldest first)."""
    lines = text.splitlines()
    entry_idx = [i for i, l in enumerate(lines) if l.startswith("- [`")]
    drop = set(entry_idx[:-limit]) if len(entry_idx) > limit else set()
    return "\n".join(l for i, l in enumerate(lines) if i not in drop)


def _backup_before_overwrite(path: Path) -> None:
    """Sao lưu bản hiện tại sang <path>.bak trước khi Evolution ghi đè, để có
    thể khôi phục thủ công nếu LLM đánh giá sai và loại bỏ nhầm luật tốt."""
    if not path.exists():
        return
    try:
        backup_path = path.with_suffix(path.suffix + ".bak")
        _write_text_atomic(backup_path, path.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning(f"🧬 Không sao lưu được {path.name} trước khi ghi đè: {e}")


def _extract_bullets(md_text: str) -> list[str]:
    """Pull just the '- ...' rule lines out of a SKILL.md/STYLE.md body, ignoring
    the YAML frontmatter and the '# ... Rules' heading."""
    return [line.strip() for line in md_text.splitlines() if line.strip().startswith("- ")]


# Measured on the real log: 0.80 merged "news" and "price" routing rules (a wrong merge
# silently drops a real rule), 0.83 kept them apart; 0.85 leaves margin. A missed
# paraphrase is harmless, a wrong merge is not, so err high.
_EMBED_SIMILAR = 0.85
_VEC_CACHE: dict[str, list] = {}


def _vec(norm_text: str) -> list | None:
    """Embedding via the same embedder Learning uses; None when it is unavailable."""
    if norm_text not in _VEC_CACHE:
        from engine.core.learning import LearningEngine
        v = LearningEngine._embed_text(norm_text)
        if v is None:
            return None
        _VEC_CACHE[norm_text] = v
    return _VEC_CACHE[norm_text]


def _similar(a: str, b: str) -> bool:
    """Same rule, reworded or extended? Cheap text checks first (near-identical, or the
    shorter one contained in the other), then embedding cosine for rewrites that share
    few words. Embedder down -> text checks only."""
    norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
    na, nb = norm(a), norm(b)
    if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.8:
        return True
    wa, wb = set(na.split()), set(nb.split())
    if min(len(wa), len(wb)) >= 4 and len(wa & wb) / min(len(wa), len(wb)) >= 0.8:
        return True
    va, vb = _vec(na), _vec(nb)
    if not va or not vb:
        return False
    from engine.core.learning import LearningEngine
    return LearningEngine._cosine_similarity(va, vb) >= _EMBED_SIMILAR


def _merge_rules(new_text: str, old_text: str) -> str | None:
    """None = same bullet set as current, nothing to write. A block with under half
    the current bullets is a delta, not a rewrite: merge it in new-first so the
    existing rules are not clobbered."""
    old_b = _extract_bullets(old_text)
    # A reworded copy of an existing rule keeps the old wording, so it is not "new".
    new_text = "\n".join(
        next((o for o in old_b if _similar(l, o)), l) if l.lstrip().startswith("- ") else l
        for l in new_text.splitlines()
    ) + "\n"
    if len(_extract_bullets(new_text)) * 2 < len(old_b):
        new_text = _cap_rules(new_text + "\n" + "\n".join(old_b))
    return None if set(_extract_bullets(new_text)) == set(old_b) else new_text


# Measured against the real lessons: invented rules scored 0.38-0.67, real ones 0.76-0.98.
_GROUNDED_COSINE = 0.72


def _entries(text: str) -> list[str]:
    """Lesson/preference texts from Learning.md / Preferences.md ("- [`key`] text")."""
    return re.findall(r"(?m)^- \[`[^`]+`\] (.*)$", text)


def _bad_rule(line: str, sources: list[str], routing: bool) -> str | None:
    """Why this rule must not be written, else None: it names an agent/@control usage
    that does not exist, or no lesson supports it (the LLM invented it). Can't verify
    (embedder down) -> refuse: a wrong rule goes into every prompt, a skipped run costs nothing."""
    if not routing:
        forbidden = ["hỏi", "xin phép", "công cụ", "tool", "agent", "thẻ", "<ask_user>", "<action_run>", "<offer_protocol>"]
        line_lower = line.lower()
        for kw in forbidden:
            if kw in line_lower:
                return f"luật STYLE vi phạm chủ đề bị cấm ({kw}): do persona, soul_rules và offer_protocol quản lý độc quyền"

    if routing:
        from engine.orchestrator.registry import AGENT_REGISTRY
        known = set(AGENT_REGISTRY) | {f"agent_{k}" for k in AGENT_REGISTRY} | {"agent_control"}
        if re.search(r"@control\s+`?agent_(?!control)", line):
            return "@control chỉ dành cho agent_control"
        unknown = [t for t in re.findall(r"\bagent_[a-z_]+", line) if t not in known]
        if unknown:
            return f"agent không tồn tại: {unknown[0]}"
    norm = lambda s: re.sub(r"\W+", " ", s).strip().lower()
    v = _vec(norm(line))
    if v is None:
        return "không kiểm chứng được (embedder không sẵn sàng)"
    from engine.core.learning import LearningEngine
    for s in sources:
        sv = _vec(norm(s))
        if sv and LearningEngine._cosine_similarity(v, sv) >= _GROUNDED_COSINE:
            return None
    return "không có bài học nào làm căn cứ"


def _prepare_rules(new_text: str, old_text: str, sources: list[str], routing: bool) -> str | None:
    """Drop unsupported/invented rules from the new block, then merge with the current one."""
    kept = []
    for line in new_text.splitlines():
        why = _bad_rule(line, sources, routing) if line.lstrip().startswith("- ") else None
        if why:
            log.warning("🧬 Bỏ luật không hợp lệ (%s): %s", why, line.strip())
        else:
            kept.append(line)
    return _merge_rules("\n".join(kept) + "\n", old_text)


def _write_evolution_log(skill_lines: list[str], style_lines: list[str]) -> None:
    """Evolution.md = the rules evolution has added so far, per area. No dates and no
    per-run entries: a rule already listed (or a rewording of it) is not added again,
    so the file only grows when evolution learns something genuinely new."""
    try:
        text = EVOLUTION_LOG.read_text(encoding="utf-8") if EVOLUTION_LOG.exists() else ""
        areas: dict[str, list[str]] = {"Routing": [], "Giao tiếp": []}
        area = None
        for line in text.splitlines():
            if line.startswith("## "):
                area = line[3:].strip()
            elif line.startswith("- ") and area in areas:
                areas[area].append(line)
        for name, lines in (("Routing", skill_lines), ("Giao tiếp", style_lines)):
            for line in lines:
                if not any(_similar(line, old) for old in areas[name]):
                    areas[name].append(line)
        out = "# Jarvis Evolution Log\n\n<!-- JARVIS-MANAGED-EVOLUTION -->\n"
        for name, lines in areas.items():
            if lines:
                out += f"\n## {name}\n" + "\n".join(lines) + "\n"
        EVOLUTION_LOG.parent.mkdir(parents=True, exist_ok=True)
        EVOLUTION_LOG.write_text(out, encoding="utf-8")
        log.info("🧬 Đã cập nhật Evolution.md")
    except Exception as e:
        log.warning(f"🧬 Không ghi được Evolution.md: {e}")


async def trigger_cognitive_evolution() -> dict:
    """Entry point công khai — đảm bảo tối đa 1 vòng tiến hóa chạy cùng lúc."""
    if _evolution_lock.locked():
        log.info("🧬 Bỏ qua: một vòng tiến hóa khác đang chạy, tránh ghi đè chồng chéo STYLE.md/Evolution.md.")
        return {"success": True, "path": "", "error": None, "skipped": "already_running"}
    # Learning preempts itself for a live turn but spawned this as a free
    # running task, so the heaviest job in the system kept calling the shared
    # local LLM while the user was mid-conversation.
    from engine.core.activity_gate import wait_until_chat_idle
    await wait_until_chat_idle()
    async with _evolution_lock:
        return await _run_cognitive_evolution()


def _current_routing_proposals() -> str:
    """Đề xuất routing đã có trong Evolution.md (mục '## Routing'), để prompt không
    đề xuất lại y hệt điều đã ghi."""
    if not EVOLUTION_LOG.exists():
        return ""
    area = None
    lines = []
    for line in EVOLUTION_LOG.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            area = line[3:].strip()
        elif line.startswith("- ") and area == "Routing":
            lines.append(line)
    return "\n".join(lines)


async def _run_cognitive_evolution() -> dict:
    """Đọc Learning.md/Preferences.md, tự phân tích và ghi STYLE.md (sống) +
    đề xuất routing vào Evolution.md (chờ duyệt, không tự động áp dụng)."""
    log.info("🧬 Bắt đầu tiến trình tự tích lũy & tiến hóa (Self-Evolution)...")
    results = {
        "success": False,
        "path": "",
        "error": None
    }

    learning_path = PROJECT_ROOT / "data" / "wiki" / "System" / "Learning.md"
    pref_path = PROJECT_ROOT / "data" / "wiki" / "System" / "Preferences.md"

    learning_content = learning_path.read_text(encoding="utf-8").strip() if learning_path.exists() else ""
    pref_content = pref_path.read_text(encoding="utf-8").strip() if pref_path.exists() else ""

    learning_content = _newest_entries(learning_content)
    pref_content = _newest_entries(pref_content)

    if not learning_content and not pref_content:
        log.warning("🧬 Không tìm thấy dữ liệu học để tự tiến hóa.")
        return results

    global _last_inputs
    if (learning_content, pref_content) == _last_inputs:
        log.info("🧬 Learning/Preferences không đổi từ lần tiến hóa trước, bỏ qua.")
        results["success"] = True
        return results

    sources = _entries(learning_content) + _entries(pref_content)

    try:
        # 1. Đọc trạng thái hiện tại: STYLE.md sống, đề xuất routing đã có trong Evolution.md
        current_style = STYLE_FILE.read_text(encoding="utf-8").strip() if STYLE_FILE.exists() else ""
        current_routing_proposals = _current_routing_proposals()

        from engine.prompts.learning import build_evolution_prompt
        prompt = build_evolution_prompt(
            pref_content=pref_content,
            learning_content=learning_content,
            current_routing_proposals=current_routing_proposals,
            current_style=current_style,
        )

        response = await call_llm(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            thinking=False
        )
        content = response.choices[0].message.content.strip()

        parsed = parse_evolution_response(content)
        _last_inputs = (learning_content, pref_content)
        need_evolution = parsed["need_evolution"]
        reason = parsed.get("reason", "")
        log.info(f"🧬 Đánh giá nhu cầu tiến hóa: ({reason})")

        if not need_evolution:
            log.info("🧬 Không cần tiến hóa thêm ở lượt này.")
            results["success"] = True
            results["path"] = str(STYLE_FILE) if STYLE_FILE.exists() else ""
            return results

        # 3. Routing: lọc luật bịa/vô căn cứ, KHÔNG ghi file sống — chỉ đưa vào
        #    Evolution.md làm đề xuất. Style: vẫn ghi STYLE_FILE (sống, đọc mỗi lượt chat).
        style_written = False

        # Emoji chỉ thể hiện lúc chat trực tiếp; luật lưu vào STYLE.md/Evolution.md không giữ emoji.
        from engine.core.memory import strip_emojis

        routing_rules_raw = _cap_rules(strip_emojis(parsed.get("routing_rules", "").strip()))
        routing_bullets = []
        if "# Self Evolution Routing Rules" in routing_rules_raw:
            for line in routing_rules_raw.splitlines():
                if not line.lstrip().startswith("- "):
                    continue
                why = await asyncio.to_thread(_bad_rule, line, sources, True)
                if why:
                    log.warning("🧬 Bỏ đề xuất routing không hợp lệ (%s): %s", why, line.strip())
                else:
                    routing_bullets.append(line.strip())

        style_rules = _cap_rules(strip_emojis(parsed.get("style_rules", "").strip()))
        if "# Self Evolution Style Rules" in style_rules and (style_rules := await asyncio.to_thread(_prepare_rules, style_rules, current_style, sources, False)):
            STYLE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _backup_before_overwrite(STYLE_FILE)
            _write_text_atomic(STYLE_FILE, style_rules)
            style_written = True
            log.info(f"🧬 Đã cập nhật style rules: {STYLE_FILE} (bản cũ lưu tại {STYLE_FILE.name}.bak)")

        if routing_bullets or style_written:
            final_style = style_rules if style_written else current_style
            await asyncio.to_thread(
                _write_evolution_log,
                routing_bullets,
                _extract_bullets(final_style),
            )
            results["success"] = True
            results["path"] = str(STYLE_FILE)
        else:
            log.info("🧬 Cần tiến hóa nhưng không có nội dung mới hợp lệ.")
            results["success"] = True
    except Exception as e:
        log.error(f"🧬 Thất bại trong quá trình tự tiến hóa: {e}", exc_info=True)
        results["error"] = str(e)
        
    return results
