# -*- coding: utf-8 -*-
"""
JARVIS Database & Wiki Safe Cleanup Script (Spec 2026-09-25 Task E).

Thực hiện dọn dẹp các mục rác và trùng lặp phát sinh trước khi chuẩn hóa prompt:
1. Sao lưu data/jarvis.db và data/wiki/System/.
2. In danh sách các mục sẽ dọn (mặc định DRY-RUN, không chạm DB/file).
3. Chỉ thực sự dọn khi chạy với cờ --apply.

Danh sách xử lý theo spec:
- Mục rác trong learnings: "lười mở Notepad", "Lịch sử Việt Nam 1945", "USER đã hoàn thành dự án…", "Hơi mệt mỏi vì phải kiểm tra hành vi…".
- Các bản trùng trong memories của những mục đã có ở learnings.
- agent_outcomes thất bại có tên app bị dịch ("Ghi chú (Notepad)", "Ghi chú").
- Luật STYLE "…hỏi lại người dùng nếu cần…".
- File .bak trong skills/self_evolution/ và data/wiki/System/.
- Dòng đề xuất giả do test cũ (tests/test_learning_reflection.py) ghi vào Evolution.md thật.
"""

import argparse
import datetime
import re
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "jarvis.db"
DEFAULT_WIKI_SYS_DIR = PROJECT_ROOT / "data" / "wiki" / "System"
DEFAULT_STYLE_DIR = PROJECT_ROOT / "skills" / "self_evolution"
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "backups"

# Từ khóa nhận diện rác trong learnings
JUNK_LEARNING_PATTERNS = [
    r"lười\s+mở",
    r"lịch\s+sử\s+việt\s+nam.*1945",
    r"1945.*tuyên\s+ngôn\s+độc\s+lập",
    r"hoàn\s+thành\s+dự\s+án",
    r"mệt\s+mỏi\s+vì\s+phải\s+kiểm\s+tra",
    r"kiểm\s+tra\s+hành\s+vi\s+của\s+jarvis",
]

JUNK_LEARNING_KEYS = {
    "lazy_notepad",
    "user_preference_for_automation",
    "history_1945",
    "vietnam_history_1945",
    "proj_done",
    "project_status_complete",
    "fatigue",
    "user_fatigue_with_behavior_checking",
}


def _normalize_text(text: str) -> str:
    """Chuẩn hóa chuỗi văn bản để so sánh nội dung."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return " ".join(text.split())


def find_junk_learnings(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Tìm các bản ghi rác trong bảng learnings."""
    cursor = conn.execute("SELECT id, type, semantic_key, content FROM learnings ORDER BY id ASC")
    rows = cursor.fetchall()
    junk = []
    for row in rows:
        r_id, r_type, r_key, r_content = row[0], row[1], row[2] or "", row[3] or ""
        norm_content = r_content.lower()
        is_junk = False

        if r_key in JUNK_LEARNING_KEYS:
            is_junk = True
        else:
            for pat in JUNK_LEARNING_PATTERNS:
                if re.search(pat, norm_content, re.IGNORECASE):
                    is_junk = True
                    break

        if is_junk:
            junk.append({
                "id": r_id,
                "type": r_type,
                "semantic_key": r_key,
                "content": r_content,
            })
    return junk


def find_duplicate_memories(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Tìm các bản ghi trong memories trùng lặp với learnings hoặc chứa thông tin rác."""
    # Lấy toàn bộ learnings còn lại (không kể rác) và kể cả rác để dọn sạch
    learnings_rows = conn.execute("SELECT content FROM learnings").fetchall()
    learnings_normalized = [_normalize_text(r[0] or "") for r in learnings_rows if r[0]]

    memories_cursor = conn.execute("SELECT id, type, content FROM memories ORDER BY id ASC")
    duplicates = []
    for row in memories_cursor.fetchall():
        m_id, m_type, m_content = row[0], row[1], row[2] or ""
        norm_m = _normalize_text(m_content)
        if not norm_m:
            continue

        is_dup = False
        # 1. So khớp với learnings
        for norm_l in learnings_normalized:
            if not norm_l:
                continue
            # Nếu trùng khớp hoàn toàn hoặc trùng lặp ý chính
            if norm_m == norm_l or norm_m in norm_l or norm_l in norm_m:
                is_dup = True
                break
            # Độ tương đồng tập từ vựng
            words_m = set(norm_m.split())
            words_l = set(norm_l.split())
            overlap = len(words_m & words_l)
            if overlap >= 4 and (overlap / max(len(words_m), 1)) >= 0.7:
                is_dup = True
                break

        # 2. Hoặc các nội dung rác đã biết trong memories
        if not is_dup:
            for pat in JUNK_LEARNING_PATTERNS:
                if re.search(pat, norm_m, re.IGNORECASE):
                    is_dup = True
                    break

        if is_dup:
            duplicates.append({
                "id": m_id,
                "type": m_type,
                "content": m_content,
            })
    return duplicates


def find_translated_app_failed_outcomes(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Tìm các bản ghi agent_outcomes thất bại có tên app bị dịch tiếng Việt."""
    cursor = conn.execute("SELECT id, agent, query, status, result FROM agent_outcomes ORDER BY id ASC")
    targets = []
    for row in cursor.fetchall():
        o_id, o_agent, o_query, o_status, o_result = row[0], row[1], row[2] or "", row[3] or "", row[4] or ""
        if str(o_status).lower() in ("failed", "error", "misrouted"):
            combined = (o_query + " " + o_result).lower()
            if "ghi chú" in combined or "ghi chú (notepad)" in combined or "lại ứng dụng ghi chú" in combined:
                targets.append({
                    "id": o_id,
                    "agent": o_agent,
                    "query": o_query,
                    "status": o_status,
                    "result": o_result[:80],
                })
    return targets


def find_bak_files(dirs: List[Path]) -> List[Path]:
    """Tìm tất cả các file .bak trong danh sách thư mục."""
    bak_files = []
    for d in dirs:
        if d.exists():
            for p in d.rglob("*.bak"):
                if p.is_file():
                    bak_files.append(p)
    return bak_files


def clean_style_rules(style_file: Path, dry_run: bool = True) -> int:
    """Loại bỏ luật STYLE có '...hỏi lại người dùng nếu cần...'."""
    if not style_file.exists():
        return 0
    text = style_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    new_lines = []
    removed_count = 0

    for line in lines:
        lower = line.lower()
        if "hỏi lại" in lower and "nếu cần" in lower:
            removed_count += 1
            continue
        new_lines.append(line)

    if not dry_run and removed_count > 0:
        cleaned_content = "\n".join(new_lines).rstrip()
        if cleaned_content:
            cleaned_content += "\n"
        style_file.write_text(cleaned_content, encoding="utf-8")

    return removed_count


# Dòng do test cũ ghi vào Evolution.md thật (test đã được cô lập, 2026-09-25)
TEST_JUNK_EVOLUTION_LINES = (
    "- [ĐỀ XUẤT] Tài liệu văn bản nên chuyển cho office agent (Bằng chứng: tài liệu này xử lý thế nào)",
)


def clean_evolution_test_lines(evo_file: Path, dry_run: bool = True) -> int:
    """Gỡ các dòng đề xuất giả do test ghi vào Evolution.md."""
    if not evo_file.exists():
        return 0
    lines = evo_file.read_text(encoding="utf-8").splitlines(keepends=True)
    kept = [ln for ln in lines if ln.rstrip() not in TEST_JUNK_EVOLUTION_LINES]
    removed = len(lines) - len(kept)
    if not dry_run and removed:
        evo_file.write_text("".join(kept), encoding="utf-8")
    return removed


def create_backup(db_path: Path, wiki_sys_dir: Path, backup_dir: Path, style_dir: Path | None = None) -> Path:
    """Tạo bản sao lưu an toàn cho jarvis.db, data/wiki/System/ và skills/self_evolution/."""
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_backup_dir = backup_dir / f"cleanup_{timestamp}"
    run_backup_dir.mkdir(parents=True, exist_ok=True)

    if db_path.exists():
        shutil.copy2(db_path, run_backup_dir / db_path.name)

    if wiki_sys_dir.exists():
        dest_wiki = run_backup_dir / "System"
        shutil.copytree(wiki_sys_dir, dest_wiki, dirs_exist_ok=True)

    if style_dir is not None and style_dir.exists():
        shutil.copytree(style_dir, run_backup_dir / style_dir.name, dirs_exist_ok=True)

    return run_backup_dir


def run_cleanup(
    db_path: Path = DEFAULT_DB_PATH,
    wiki_sys_dir: Path = DEFAULT_WIKI_SYS_DIR,
    style_dir: Path = DEFAULT_STYLE_DIR,
    backup_dir: Path = DEFAULT_BACKUP_DIR,
    apply: bool = False,
) -> Dict[str, Any]:
    """Hàm trung tâm điều khiển dọn dẹp theo spec Task E."""
    report: Dict[str, Any] = {
        "apply": apply,
        "backup_path": None,
        "junk_learnings": [],
        "duplicate_memories": [],
        "failed_outcomes": [],
        "bak_files": [],
        "style_rules_removed": 0,
        "evolution_test_lines": 0,
    }

    if not db_path.exists():
        return report

    conn = sqlite3.connect(db_path)

    # 1. Phát hiện các mục tiêu dọn dẹp
    junk_learnings = find_junk_learnings(conn)
    duplicate_memories = find_duplicate_memories(conn)
    failed_outcomes = find_translated_app_failed_outcomes(conn)
    bak_files = find_bak_files([style_dir, wiki_sys_dir])
    style_file = style_dir / "STYLE.md"
    evo_file = wiki_sys_dir / "Evolution.md"

    report["junk_learnings"] = junk_learnings
    report["duplicate_memories"] = duplicate_memories
    report["failed_outcomes"] = failed_outcomes
    report["bak_files"] = bak_files
    report["style_rules_removed"] = clean_style_rules(style_file, dry_run=True)
    report["evolution_test_lines"] = clean_evolution_test_lines(evo_file, dry_run=True)

    if not apply:
        conn.close()
        return report

    # 2. Khi apply=True: Sao lưu TRƯỚC mọi thay đổi (kể cả STYLE.md)
    backup_path = create_backup(db_path, wiki_sys_dir, backup_dir, style_dir)
    report["backup_path"] = backup_path
    clean_style_rules(style_file, dry_run=False)
    clean_evolution_test_lines(evo_file, dry_run=False)

    # 3. Dọn dẹp qua Memory Center / DB
    # Learnings: Dùng Memory Center nếu có, hoặc SQL trực tiếp
    learning_ids = [j["id"] for j in junk_learnings]
    memory_ids = [d["id"] for d in duplicate_memories]
    outcome_ids = [o["id"] for o in failed_outcomes]

    try:
        from engine.core.learning import get_learning_engine
        learning_engine = get_learning_engine()
    except Exception:
        learning_engine = None

    if learning_engine and db_path == DEFAULT_DB_PATH:
        for l_id in learning_ids:
            try:
                learning_engine.delete_learning_control_record("learning", l_id)
            except Exception:
                conn.execute("DELETE FROM learnings WHERE id=?", (l_id,))
        for o_id in outcome_ids:
            try:
                learning_engine.delete_learning_control_record("outcome", o_id)
            except Exception:
                conn.execute("DELETE FROM agent_outcomes WHERE id=?", (o_id,))
    else:
        for l_id in learning_ids:
            conn.execute("DELETE FROM learnings WHERE id=?", (l_id,))
        for o_id in outcome_ids:
            conn.execute("DELETE FROM agent_outcomes WHERE id=?", (o_id,))

    # Memories
    try:
        from engine.core.memory import delete_memory
        for m_id in memory_ids:
            if db_path == DEFAULT_DB_PATH:
                delete_memory(m_id)
            else:
                conn.execute("DELETE FROM memories WHERE id=?", (m_id,))
    except Exception:
        for m_id in memory_ids:
            conn.execute("DELETE FROM memories WHERE id=?", (m_id,))

    conn.commit()
    conn.close()

    # Xóa file .bak
    for bf in bak_files:
        try:
            bf.unlink(missing_ok=True)
        except OSError:
            pass

    # Đồng bộ lại Wiki
    if db_path == DEFAULT_DB_PATH:
        try:
            from engine.core.learning import get_learning_engine
            get_learning_engine()._sync_learning_wiki()
        except Exception:
            pass

    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Safe cleanup script for JARVIS DB and Wiki (2026-09-25 Task E)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply deletions (default is dry-run: inspect only)",
    )
    args = parser.parse_args()

    mode = "THỰC THI (--apply)" if args.apply else "DRY-RUN (CHỈ XEM)"
    print("============================================================")
    print(f"JARVIS CLEANUP SCRIPT 2026-09 — CHẾ ĐỘ: {mode}")
    print("============================================================")

    report = run_cleanup(apply=args.apply)

    print(f"\n1. MỤC RÁC TRONG LEARNINGS ({len(report['junk_learnings'])} mục):")
    for item in report["junk_learnings"]:
        print(f"   - [ID {item['id']}] ({item['semantic_key']}): {item['content']}")

    print(f"\n2. BẢN TRÙNG TRONG MEMORIES ({len(report['duplicate_memories'])} mục):")
    for item in report["duplicate_memories"]:
        print(f"   - [ID {item['id']}]: {item['content']}")

    print(f"\n3. AGENT OUTCOMES THẤT BẠI DỊCH TÊN ỨNG DỤNG ({len(report['failed_outcomes'])} mục):")
    for item in report["failed_outcomes"]:
        print(f"   - [ID {item['id']}]: query='{item['query']}'")

    print(f"\n4. LUẬT STYLE BỊ LOẠI BỎ: {report['style_rules_removed']} luật")

    print(f"\n5. DÒNG GIẢ DO TEST TRONG EVOLUTION.MD: {report['evolution_test_lines']} dòng")

    print(f"\n6. FILE .BAK TỒN TẠI ({len(report['bak_files'])} file):")
    for bf in report["bak_files"]:
        print(f"   - {bf}")

    if args.apply:
        print("\n✅ ĐÃ HOÀN TẤT DỌN DẸP AN TOÀN.")
        print(f"   Bản sao lưu tại: {report['backup_path']}")
    else:
        print("\n⚠️  CHẾ ĐỘ XEM TRƯỚC: Không có dữ liệu nào bị thay đổi.")
        print("   Để thực sự áp dụng dọn dẹp, hãy chạy lại với cờ --apply:")
        print("   rtk python scripts/cleanup_learning_2026_09.py --apply")
    print("============================================================")


if __name__ == "__main__":
    main()
