"""
JARVIS Memory — persistent context for conversations.

Two systems:
1. Memories — facts, preferences, project context JARVIS learns from conversations
2. Messages — conversation history persistence

Everything stored in SQLite. Vector search via turbovec + embeddings for semantic recall.
Relevant memories injected into every LLM call via build_memory_context().
"""

import json
import logging
import os
import re
import sqlite3
import time
import threading
from pathlib import Path
from typing import Optional, Any, Callable

import numpy as np
from turbovec import IdMapIndex

log = logging.getLogger("jarvis.memory")

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"  # Regional indicator symbols (emoji cờ quốc gia)
    "\U0001F300-\U0001FAFF"  # Pictographs, emoticons, transport, supplemental symbols A/B, extended-A
    "\U00002600-\U000026FF"  # Miscellaneous Symbols
    "\U00002700-\U000027BF"  # Dingbats
    "\U00002B00-\U00002BFF"  # Miscellaneous Symbols and Arrows (★ ⭐ ...)
    "\U0000FE0F"              # Variation Selector-16 (emoji presentation selector)
    "\U0000200D"              # Zero Width Joiner (nối emoji ghép)
    "\U000020E3"              # Combining Enclosing Keycap (1️⃣ 2️⃣ ...)
    "]+",
    flags=re.UNICODE,
)

_IMAGE_RE = re.compile(
    r"!\[.*?\]\(.*?\)"                     # Markdown image ![alt](url)
    r"|data:image\/[a-zA-Z;,\/+=%0-9-]+"  # Base64 data URI
    r"|<img[^>]*>"                          # HTML img tag
    r"|!\[\[.*?\]\]",                       # Obsidian wiki embed [[image.png]]
    flags=re.UNICODE | re.IGNORECASE,
)


def strip_emojis(text: str) -> str:
    return _EMOJI_RE.sub("", text).strip()


def strip_images(text: str) -> str:
    return _IMAGE_RE.sub("", text).strip()


DB_PATH = Path(__file__).parent.parent.parent / "data" / "jarvis.db"
SEMANTIC_DIR = Path(__file__).parent.parent.parent / "data" / "semantic"
SEMANTIC_VEC_PATH = SEMANTIC_DIR / "semantic_vectors.tvim"
SEMANTIC_META_PATH = SEMANTIC_DIR / "semantic_metadata.json"


def _get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT DEFAULT '',
            importance INTEGER DEFAULT 5,
            created_at REAL NOT NULL,
            last_accessed REAL,
            access_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
            content, type, source,
            content='memories', content_rowid='id'
        );

        CREATE TABLE IF NOT EXISTS pins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            label TEXT NOT NULL,
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_pins_coords ON pins(lat, lng);

        CREATE TABLE IF NOT EXISTS feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id TEXT DEFAULT '',
            rating INTEGER NOT NULL,
            comment TEXT DEFAULT '',
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);

        CREATE TABLE IF NOT EXISTS memory_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            semantic_key TEXT NOT NULL,
            mem_type TEXT NOT NULL,
            memory_id INTEGER NOT NULL,
            wiki_scope TEXT DEFAULT '',
            updated_at REAL NOT NULL,
            UNIQUE(mem_type, semantic_key)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_registry_memory ON memory_registry(memory_id);
    """)
    # Cột ask_user (spec §6): câu Jarvis xin phép ở lượt đó; content giữ bản sạch cho FTS/UI/Telegram.
    if "ask_user" not in {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}:
        conn.execute("ALTER TABLE messages ADD COLUMN ask_user TEXT DEFAULT ''")
    # Cột action_run (spec §11): tên tool khi có <action_run>; chỉ trả về nếu ask_user cũng có.
    if "action_run" not in {r["name"] for r in conn.execute("PRAGMA table_info(messages)")}:
        conn.execute("ALTER TABLE messages ADD COLUMN action_run TEXT DEFAULT ''")
    conn.commit()
    conn.close()
    log.info("🗄️ Memory database initialized with pins support")


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------

def save_memory(content: str, mem_type: str = "fact", source: str = "", importance: int = 5) -> int:
    content = strip_images(strip_emojis(content.strip()))

    conn = _get_db()
    existing = conn.execute(
        "SELECT id FROM memories WHERE type = ? AND LOWER(TRIM(content)) = LOWER(?)",
        (mem_type, content)
    ).fetchone()

    if existing:
        mem_id = existing["id"]
        conn.execute(
            "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id = ?",
            (time.time(), mem_id)
        )
        conn.commit()
        conn.close()
        log.info(f"📝 Memory [{mem_type}] duplicate skipped, id={mem_id}")
        return mem_id

    cur = conn.execute(
        "INSERT INTO memories (type, content, source, importance, created_at) VALUES (?, ?, ?, ?, ?)",
        (mem_type, content, source, importance, time.time())
    )
    mem_id = cur.lastrowid
    conn.execute(
        "INSERT INTO memory_fts (rowid, content, type, source) VALUES (?, ?, ?, ?)",
        (mem_id, content, mem_type, source)
    )
    conn.commit()
    conn.close()

    sm = SemanticMemoryEngine.get_instance()
    sm.add_memory(mem_id, content, mem_type)

    log.info(f"📝 Stored memory [{mem_type}]")
    return mem_id


def upsert_distilled_memory(
    content: str, mem_type: str, source: str, importance: int, semantic_key: str,
) -> dict:
    """Persist a Learning-approved item and replace its prior value by stable semantic key."""
    if mem_type not in {"fact", "preference"}:
        raise ValueError("Unsupported distilled memory type")
    content = strip_images(strip_emojis(content.strip()))
    semantic_key = re.sub(r"[^a-z0-9_-]+", "_", semantic_key.lower()).strip("_")[:80]
    if not content or not semantic_key:
        raise ValueError("Distilled memory requires content and semantic key")

    # The learning task may be the first writer after a fresh database reset.
    # Make its storage path independent from startup ordering.
    init_db()
    conn = _get_db()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS memory_registry (
            id INTEGER PRIMARY KEY AUTOINCREMENT, semantic_key TEXT NOT NULL,
            mem_type TEXT NOT NULL, memory_id INTEGER NOT NULL, wiki_scope TEXT DEFAULT '',
            updated_at REAL NOT NULL, UNIQUE(mem_type, semantic_key))"""
    )
    row = conn.execute(
        """SELECT r.memory_id, m.content FROM memory_registry r
           JOIN memories m ON m.id=r.memory_id WHERE r.mem_type=? AND r.semantic_key=?""",
        (mem_type, semantic_key),
    ).fetchone()
    conn.close()
    if row:
        mem_id = row["memory_id"]
        if " ".join(row["content"].split()).lower() == " ".join(content.split()).lower():
            log.info("🧠 Memory [%s] duplicate: key=%s id=%s", mem_type, semantic_key, mem_id)
            return {"status": "duplicate", "memory_id": mem_id}
        if not update_memory(
            mem_id, content, importance, mem_type, source=source
        ):
            raise RuntimeError(f"Unable to update memory {mem_id}")
        conn = _get_db()
        conn.execute("UPDATE memory_registry SET updated_at=? WHERE mem_type=? AND semantic_key=?",
                     (time.time(), mem_type, semantic_key))
        conn.commit()
        conn.close()
        log.info("🧠 Memory [%s] updated: key=%s id=%s", mem_type, semantic_key, mem_id)
        return {"status": "updated", "memory_id": mem_id}

    mem_id = save_memory(content, mem_type, source, importance)
    conn = _get_db()
    conn.execute(
        "INSERT OR REPLACE INTO memory_registry (semantic_key, mem_type, memory_id, updated_at) VALUES (?, ?, ?, ?)",
        (semantic_key, mem_type, mem_id, time.time()),
    )
    conn.commit()
    conn.close()
    log.info("🧠 Memory [%s] created: key=%s id=%s", mem_type, semantic_key, mem_id)
    return {"status": "created", "memory_id": mem_id}


def get_important_memories(limit: int = 10) -> list[dict]:
    conn = _get_db()
    results = conn.execute(
        "SELECT * FROM memories ORDER BY importance DESC, access_count DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in results]


def _list_memory_table(
    table: str,
    columns: str,
    search_columns: tuple[str, ...],
    order_column: str,
    q: str,
    limit: int,
    offset: int,
) -> dict:
    if table not in {"memories", "memory_registry", "messages"}:
        raise ValueError("unsupported_table")
    page_limit = max(1, min(int(limit), 200))
    page_offset = max(0, int(offset))
    query = (q or "").strip().lower()
    params: list[object] = []
    where = ""
    if query:
        where = " WHERE " + " OR ".join(
            f"LOWER(CAST({column} AS TEXT)) LIKE ?"
            for column in search_columns
        )
        params = [f"%{query}%"] * len(search_columns)
    conn = _get_db()
    total = conn.execute(
        f"SELECT COUNT(*) FROM {table}{where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""SELECT {columns} FROM {table}{where}
            ORDER BY {order_column} DESC LIMIT ? OFFSET ?""",
        [*params, page_limit, page_offset],
    ).fetchall()
    conn.close()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "limit": page_limit,
        "offset": page_offset,
    }


def list_memory_records(
    q: str = "", limit: int = 50, offset: int = 0
) -> dict:
    return _list_memory_table(
        "memories",
        (
            "id, type, content, source, importance, created_at, "
            "last_accessed, access_count"
        ),
        ("type", "content", "source"),
        "created_at",
        q,
        limit,
        offset,
    )


def list_registry_records(
    q: str = "", limit: int = 50, offset: int = 0
) -> dict:
    return _list_memory_table(
        "memory_registry",
        "id, semantic_key, mem_type, memory_id, wiki_scope, updated_at",
        ("semantic_key", "mem_type", "memory_id", "wiki_scope"),
        "updated_at",
        q,
        limit,
        offset,
    )


def list_conversation_records(
    q: str = "", limit: int = 50, offset: int = 0
) -> dict:
    return _list_memory_table(
        "messages",
        "id, role, content, session_id, created_at",
        ("role", "content", "session_id"),
        "created_at",
        q,
        limit,
        offset,
    )


def get_memory_control_counts() -> dict[str, int]:
    conn = _get_db()
    try:
        return {
            "memories": conn.execute(
                "SELECT COUNT(*) FROM memories"
            ).fetchone()[0],
            "registry": conn.execute(
                "SELECT COUNT(*) FROM memory_registry"
            ).fetchone()[0],
            "conversations": conn.execute(
                "SELECT COUNT(*) FROM messages"
            ).fetchone()[0],
        }
    finally:
        conn.close()


def get_memory_by_id(mem_id: int) -> dict | None:
    conn = _get_db()
    row = conn.execute(
        """SELECT id, type, content, source, importance,
                  created_at, last_accessed, access_count
           FROM memories WHERE id=?""",
        (mem_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def _invalidate_semantic_memory_cache(
    mem_id: int, content: str | None = None, mem_type: str | None = None
) -> None:
    """Incrementally sync the semantic vector cache for one changed memory.

    Previously this dropped the in-RAM entry, discarded the vector index,
    and spawned initialize_cache() in a background thread — which never
    persisted first, so it always saw a "stale" on-disk cache vs. the DB
    and wiped + re-embedded every memory row. Instead: remove/replace only
    this one id in the turbovec index (which supports id-level removal)
    and persist the cache immediately, so a normal edit never looks stale
    to initialize_cache() again.
    """
    sm = SemanticMemoryEngine.get_instance()
    if not sm.initialized:
        # Cache not loaded yet in this process — the eventual
        # initialize_cache() call will read the already-updated DB row
        # directly, so there's nothing to fix up here.
        return

    key = f"db_{mem_id}"

    def _apply():
        # Embed before taking the lock: this is an HTTP call that can block for
        # the full embed timeout, and holding _init_lock across it stalls every
        # other cache reader and writer for that whole time.
        vec = sm._get_embedding(content) if content is not None else None
        if content is not None and vec is None:
            log.warning(
                "Semantic sync for memory id=%s has no embedding; dropping it from "
                "recall until the next cache rebuild.", mem_id,
            )
        try:
            with sm._init_lock:
                if sm.vector_index is not None:
                    try:
                        sm.vector_index.remove(mem_id)
                    except Exception:
                        pass
                if vec is None:
                    sm.mem_contents.pop(key, None)
                else:
                    if sm.vector_index is None:
                        sm.vector_index = IdMapIndex(dim=len(vec), bit_width=4)
                    sm.vector_index.add_with_ids(
                        np.array([vec], dtype=np.float32),
                        np.array([mem_id], dtype=np.uint64),
                    )
                    sm.mem_contents[key] = {"content": content, "type": mem_type or "fact"}
                sm._save_cache()
        except Exception:
            # Without this the thread died silently: the vector was already
            # removed but the cache was never saved, leaving RAM and disk
            # disagreeing with no trace in the log.
            log.exception("Semantic sync failed for memory id=%s", mem_id)

    threading.Thread(target=_apply, daemon=True).start()


def delete_memory(mem_id: int) -> bool:
    """Xóa một ghi nhớ dài hạn khỏi sqlite, FTS, và bộ chỉ mục vector."""
    try:
        conn = _get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "DELETE FROM memory_registry WHERE memory_id=?", (mem_id,)
            )
            affected = conn.execute(
                "DELETE FROM memories WHERE id=?", (mem_id,)
            ).rowcount
            conn.execute("DELETE FROM memory_fts WHERE rowid=?", (mem_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if not affected:
            return False
        _invalidate_semantic_memory_cache(mem_id)
        log.info(f"📝 Deleted memory id={mem_id}")
        return True
    except Exception as e:
        log.error(f"Failed to delete memory: {e}", exc_info=True)
        return False


def update_memory(
    mem_id: int,
    content: str,
    importance: int = 5,
    mem_type: str = "fact",
    *,
    source: str | None = None,
) -> bool:
    """Cập nhật ghi nhớ dài hạn và reload vector index."""
    try:
        content = strip_images(strip_emojis(content.strip()))
        conn = _get_db()
        row = conn.execute(
            "SELECT source FROM memories WHERE id=?", (mem_id,)
        ).fetchone()
        if not row:
            conn.close()
            return False
        final_source = row["source"] if source is None else source
        conn.execute(
            """UPDATE memories
               SET content=?, type=?, source=?, importance=? WHERE id=?""",
            (content, mem_type, final_source, importance, mem_id),
        )
        conn.execute(
            """UPDATE memory_fts
               SET content=?, type=?, source=? WHERE rowid=?""",
            (content, mem_type, final_source, mem_id),
        )
        conn.commit()
        conn.close()
        _invalidate_semantic_memory_cache(mem_id, content, mem_type)
        log.info(f"📝 Updated memory id={mem_id}")
        return True
    except Exception as e:
        log.error(f"Failed to update memory: {e}", exc_info=True)
        return False


def update_memory_control_record(
    kind: str, record_id: int, values: dict
) -> bool:
    schemas = {
        "memory": (
            "memories",
            {"type", "content", "source", "importance"},
        ),
        "registry": (
            "memory_registry",
            {"semantic_key", "mem_type", "memory_id", "wiki_scope"},
        ),
        "conversation": (
            "messages",
            {"role", "content", "session_id"},
        ),
    }
    if kind not in schemas:
        raise ValueError("unsupported_kind")
    table, allowed = schemas[kind]
    clean = {key: value for key, value in values.items() if key in allowed}
    if not clean or clean.keys() != values.keys():
        raise ValueError("invalid_payload")
    if kind == "memory":
        current = get_memory_by_id(record_id)
        if not current:
            return False
        return update_memory(
            record_id,
            str(clean.get("content", current["content"])),
            int(clean.get("importance", current["importance"])),
            str(clean.get("type", current["type"])),
            source=str(clean.get("source", current["source"])),
        )
    conn = _get_db()
    if kind == "registry" and "memory_id" in clean:
        clean["memory_id"] = int(clean["memory_id"])
        exists = conn.execute(
            "SELECT 1 FROM memories WHERE id=?", (clean["memory_id"],)
        ).fetchone()
        if not exists:
            conn.close()
            raise ValueError("invalid_reference")
    if kind == "conversation" and "role" in clean:
        if clean["role"] not in {"user", "assistant", "system", "tool"}:
            conn.close()
            raise ValueError("invalid_role")
    assignments = ", ".join(f"{field}=?" for field in clean)
    affected = conn.execute(
        f"UPDATE {table} SET {assignments} WHERE id=?",
        [*clean.values(), record_id],
    ).rowcount
    if kind == "registry" and affected:
        conn.execute(
            "UPDATE memory_registry SET updated_at=? WHERE id=?",
            (time.time(), record_id),
        )
    conn.commit()
    conn.close()
    return affected > 0


def preview_memory_dependencies(kind: str, record_id: int) -> dict:
    table = {
        "memory": "memories",
        "registry": "memory_registry",
        "conversation": "messages",
    }.get(kind)
    if not table:
        raise ValueError("unsupported_kind")
    conn = _get_db()
    row = conn.execute(
        f"SELECT * FROM {table} WHERE id=?", (record_id,)
    ).fetchone()
    if not row:
        conn.close()
        raise LookupError("not_found")
    registry_rows = []
    memory_row = None
    if kind == "memory":
        registry_rows = conn.execute(
            "SELECT * FROM memory_registry WHERE memory_id=?", (record_id,)
        ).fetchall()
    elif kind == "registry":
        memory_row = conn.execute(
            "SELECT * FROM memories WHERE id=?", (row["memory_id"],)
        ).fetchone()
    conn.close()
    records = [dict(row)]
    if memory_row:
        records.append(dict(memory_row))
    records.extend(dict(item) for item in registry_rows)
    return {
        "will_delete": {
            "records": records,
            "registry_ids": [item["id"] for item in registry_rows],
            "wiki_paths": [],
        },
        "will_update": (
            ["memory_fts"] if kind in {"memory", "registry"} else []
        ),
        "related_only": [],
    }


def delete_memory_control_record(kind: str, record_id: int) -> bool:
    preview = preview_memory_dependencies(kind, record_id)
    if kind == "memory":
        return delete_memory(record_id)
    if kind == "registry":
        registry = preview["will_delete"]["records"][0]
        return delete_memory(int(registry["memory_id"]))
    if kind == "conversation":
        conn = _get_db()
        affected = conn.execute(
            "DELETE FROM messages WHERE id=?", (record_id,)
        ).rowcount
        conn.commit()
        conn.close()
        return affected > 0
    raise ValueError("unsupported_kind")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def save_message(role: str, content: str, session_id: str = "", ask_user: str = "", action_run: str = "") -> int:
    content = strip_images(strip_emojis(content))
    conn = _get_db()

    # Duplicate = same role AND content as the very last row of the whole table.
    # Comparing against the last row "of the same role" (old behaviour) skipped a
    # genuine repeat like a second "ừ" whenever an assistant turn came in between,
    # which then hid it from get_pending_ask() (spec §6).
    last = conn.execute(
        "SELECT id, role, content FROM messages ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if last and last["role"] == role and last["content"] == content:
        conn.close()
        log.info(f"💬 Message duplicate skipped: role={role}")
        return last["id"]

    cur = conn.execute(
        "INSERT INTO messages (role, content, session_id, created_at, ask_user, action_run) VALUES (?, ?, ?, ?, ?, ?)",
        (role, content, session_id, time.time(), ask_user or "", action_run or ""),
    )
    conn.commit()
    conn.close()
    log.info(f"💬 Message [{role}]")
    return cur.lastrowid


def get_pending_offer(max_age_seconds: int = 600) -> tuple[str, str]:
    """(Câu <ask_user>, tên tool <action_run>) của tin assistant NGAY TRƯỚC tin user hiện tại.
    Có lượt khác chen vào hoặc quá max_age_seconds → ("", "").
    action_run trả về chỉ nếu ask_user cũng có (spec §11)."""
    conn = _get_db()
    rows = conn.execute("SELECT role, ask_user, action_run, created_at FROM messages ORDER BY id DESC LIMIT 2").fetchall()
    conn.close()
    if len(rows) == 2 and rows[0]["role"] == "user" and rows[1]["role"] == "assistant":
        if time.time() - (rows[1]["created_at"] or 0) > max_age_seconds:
            return "", ""
        ask = rows[1]["ask_user"] or ""
        return ask, ((rows[1]["action_run"] or "") if ask else "")
    return "", ""


def get_pending_ask(max_age_seconds: int = 600) -> str:
    """Câu <ask_user> của tin assistant NGAY TRƯỚC tin user hiện tại (user được lưu trước khi định tuyến).
    Có lượt khác chen vào → "" (câu hỏi hết hiệu lực). Câu hỏi quá cũ (mặc định >600s,
    cùng ý tưởng cửa sổ an toàn với learning.unlearn_last_route) cũng → ""."""
    return get_pending_offer(max_age_seconds)[0]


def get_messages(limit: int = 100, session_id: str = "") -> list[dict]:
    conn = _get_db()
    if session_id:
        rows = conn.execute(
            "SELECT role, content, created_at, ask_user, action_run FROM messages WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT role, content, created_at, ask_user, action_run FROM messages ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    conn.close()
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def build_unified_routing_history(
    current_text: str,
    fallback_history: list[dict] | None = None,
    limit: int = 12,
    max_chars: int = 4800,
) -> list[dict]:
    safe_limit = max(1, min(int(limit), 30))
    try:
        history = get_messages(limit=safe_limit)
    except Exception as exc:
        log.warning("Routing history DB fallback: %s", exc)
        history = list(fallback_history or [])[-safe_limit:]

    normalized: list[dict] = []
    for item in history:
        role = str(item.get("role", "")).strip()
        content = str(item.get("content", "")).strip()
        if not role or not content:
            continue
        # Chỉ gộp bản ghi trùng liền kề; "ừ" lặp lại ở lượt khác vẫn là một lượt thật.
        if normalized and (normalized[-1]["role"], normalized[-1]["content"]) == (role, content):
            continue
        entry = {"role": role, "content": content}
        if item.get("ask_user"):
            entry["ask_user"] = item["ask_user"]
            entry["action_run"] = item.get("action_run") or ""
        normalized.append(entry)

    clean_current = str(current_text or "").strip()
    if clean_current and (not normalized or (normalized[-1]["role"], normalized[-1]["content"]) != ("user", clean_current)):
        normalized.append({"role": "user", "content": clean_current})

    bounded: list[dict] = []
    remaining = max(256, int(max_chars))
    for item in reversed(normalized[-safe_limit:]):
        content = item["content"]
        if remaining <= 0:
            break
        if len(content) > remaining:
            content = content[:remaining]
        bounded.append({**item, "content": content})
        remaining -= len(content)
    bounded.reverse()
    return bounded


# ---------------------------------------------------------------------------
# Map Pins Storage Helpers
# ---------------------------------------------------------------------------

def save_pin_to_db(label: str, lat: float, lng: float) -> bool:
    try:
        conn = _get_db()
        # Xoá pin cũ ở cùng tọa độ nếu có
        conn.execute("DELETE FROM pins WHERE ABS(lat - ?) < 0.00001 AND ABS(lng - ?) < 0.00001", (lat, lng))
        conn.execute(
            "INSERT INTO pins (label, lat, lng, created_at) VALUES (?, ?, ?, ?)",
            (label.strip(), lat, lng, time.time())
        )
        conn.commit()
        conn.close()
        log.info(f"📍 Saved pin '{label}' at {lat}, {lng}")
        return True
    except Exception as e:
        log.error(f"Failed to save pin to DB: {e}")
        return False

def get_pins_from_db() -> list[dict]:
    try:
        conn = _get_db()
        rows = conn.execute("SELECT label, lat, lng FROM pins ORDER BY id DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.error(f"Failed to get pins from DB: {e}")
        return []

def delete_pin_from_db(lat: float, lng: float) -> bool:
    try:
        conn = _get_db()
        conn.execute("DELETE FROM pins WHERE ABS(lat - ?) < 0.00001 AND ABS(lng - ?) < 0.00001", (lat, lng))
        conn.commit()
        conn.close()
        log.info(f"📍 Deleted pin near {lat}, {lng}")
        return True
    except Exception as e:
        log.error(f"Failed to delete pin from DB: {e}")
        return False



# ---------------------------------------------------------------------------
# Semantic Memory — Vector search with turbovec
# ---------------------------------------------------------------------------

class SemanticMemoryEngine:
    _instance = None
    _lock = threading.Lock()
    _init_lock = threading.Lock()

    def __init__(self):
        self.vector_index: Optional[IdMapIndex] = None
        self.mem_contents: dict[str, dict] = {}
        self.initialized = False
        self._embed_client: Optional[Any] = None
        self._embed_func: Optional[Callable] = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def set_embed_client(self, client: Any):
        self._embed_client = client

    def set_embed_func(self, func: Callable[[str], Optional[np.ndarray]]):
        self._embed_func = func

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        if self._embed_func:
            return self._embed_func(text)

        # Cơ chế tự động kết nối và khởi tạo client từ .env khi chạy độc lập
        if not self._embed_client:
            import os
            local_embed_api = os.getenv("LOCAL_EMBED_API")
            local_embed_url = os.getenv("LOCAL_EMBED_URL")
            if local_embed_api and local_embed_url:
                try:
                    from openai import OpenAI
                    self._embed_client = OpenAI(api_key=local_embed_api, base_url=local_embed_url)
                    log.info(f"⚡ Autoconnected to embeddings server at {local_embed_url}")
                except Exception as e:
                    log.warning(f"Failed to auto-initialize embed_client: {e}")

        if self._embed_client:
            try:
                import os
                model = os.getenv("LOCAL_EMBED_MODEL")
                # Giới hạn cứng độ dài chuỗi đầu vào (6000 ký tự ~ 1500-2000 tokens) để không vượt quá giới hạn 2048 tokens của port 8081
                truncated_text = text[:6000] if len(text) > 6000 else text
                if len(text) > 6000:
                    log.warning(f"⚡ Truncating embedding input from {len(text)} to 6000 chars to avoid port 8081 token limit.")
                embed_timeout = float(os.getenv("LOCAL_EMBED_TIMEOUT_SECONDS", "30"))
                resp = self._embed_client.embeddings.create(input=[truncated_text], model=model, timeout=embed_timeout)
                vec = np.array(resp.data[0].embedding, dtype=np.float32)
                log.info(f"⚡ Embedding vector: {len(vec)}d")
                return vec
            except Exception as e:
                log.warning(f"Embedding via client failed: {e}")
                return None
        log.warning("No embedder set")
        return None

    def _save_cache(self):
        try:
            SEMANTIC_DIR.mkdir(parents=True, exist_ok=True)
            if self.vector_index is not None:
                self.vector_index.write(str(SEMANTIC_VEC_PATH))
            # Write-then-rename: an in-place truncating write leaves invalid
            # JSON behind if it is interrupted or races a concurrent writer,
            # and _load_cache() answers invalid JSON by deleting both files and
            # re-embedding the entire corpus. Incremental sync calls this on
            # every edit, so that window is no longer rare.
            tmp_path = SEMANTIC_META_PATH.with_name(SEMANTIC_META_PATH.name + ".tmp")
            with open(str(tmp_path), "w", encoding="utf-8") as f:
                json.dump(self.mem_contents, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(str(tmp_path), str(SEMANTIC_META_PATH))
        except Exception as e:
            log.warning(f"Failed to save semantic cache: {e}")

    def _load_cache(self) -> bool:
        try:
            if not SEMANTIC_VEC_PATH.exists() or not SEMANTIC_META_PATH.exists():
                return False
            self.vector_index = IdMapIndex.load(str(SEMANTIC_VEC_PATH))
            with open(str(SEMANTIC_META_PATH), "r", encoding="utf-8") as f:
                self.mem_contents = json.load(f)
            if any(item.get("type") == "wiki" for item in self.mem_contents.values()):
                self.vector_index = None
                self.mem_contents = {}
                SEMANTIC_VEC_PATH.unlink(missing_ok=True)
                SEMANTIC_META_PATH.unlink(missing_ok=True)
                log.info("Removed legacy Obsidian entries from semantic cache")
                return False
            log.info(f"⚡ Loaded semantic cache: {len(self.vector_index)} vectors, {len(self.mem_contents)} entries")
            return True
        except Exception as e:
            log.warning(f"Failed to load semantic cache: {e}")
            self.vector_index = None
            self.mem_contents = {}
            try:
                if SEMANTIC_VEC_PATH.exists(): SEMANTIC_VEC_PATH.unlink()
                if SEMANTIC_META_PATH.exists(): SEMANTIC_META_PATH.unlink()
            except Exception: pass
            return False

    def initialize_cache(self):
        with self._init_lock:
            if self.initialized:
                return
            log.info("⚡ Initializing Semantic Memory vector cache...")
            cache_loaded = self._load_cache()
            conn = _get_db()
            try:
                rows = conn.execute("SELECT id, type, content FROM memories").fetchall()
            except Exception:
                rows = []
            finally:
                conn.close()

            expected_contents = {
                f"db_{r['id']}": {
                    "content": r["content"],
                    "type": r["type"],
                }
                for r in rows
            }
            # Previously any drift vs. jarvis.db (even a single row) wiped
            # mem_contents/vector_index and the on-disk cache entirely, then
            # re-embedded every memory over HTTP. Instead, only remove/replace
            # the rows that actually differ — everything already matching is
            # left untouched, so drift no longer costs a full corpus re-embed.
            synced_stale = False
            if cache_loaded:
                stale_keys = set(self.mem_contents) - set(expected_contents)
                changed_keys = {
                    mid for mid, val in expected_contents.items()
                    if mid in self.mem_contents and self.mem_contents[mid] != val
                }
                drift_keys = stale_keys | changed_keys
                if drift_keys:
                    for mid in drift_keys:
                        try:
                            db_id = int(mid.split("_", 1)[1])
                        except (IndexError, ValueError):
                            continue
                        if self.vector_index is not None:
                            try:
                                self.vector_index.remove(db_id)
                            except Exception:
                                pass
                        self.mem_contents.pop(mid, None)
                    synced_stale = True
                    log.info(
                        "⚡ Semantic cache drift vs jarvis.db: incrementally synced %d entries",
                        len(drift_keys),
                    )

            vecs: list[np.ndarray] = []
            ids: list[int] = []
            for r in rows:
                mid = f"db_{r['id']}"
                if mid in self.mem_contents:
                    continue
                vec = self._get_embedding(r["content"])
                if vec is not None:
                    if self.vector_index is None:
                        self.vector_index = IdMapIndex(dim=len(vec), bit_width=4)
                    vecs.append(vec)
                    ids.append(r["id"])
                    self.mem_contents[mid] = {"content": r["content"], "type": r["type"]}

            if vecs and ids:
                vecs_np = np.array(vecs, dtype=np.float32)
                ids_np = np.array(ids, dtype=np.uint64)
                self.vector_index.add_with_ids(vecs_np, ids_np)
                self._save_cache()
                log.info(f"⚡ Vectorized {len(ids)} new memories → total index size: {len(self.vector_index)}")
            elif synced_stale:
                self._save_cache()
            elif not cache_loaded:
                log.info("⚡ No memories to vectorize yet")

            self.initialized = True
            log.info(f"⚡ Semantic Memory ready: {len(self.vector_index) if self.vector_index else 0} vectors")

    def add_memory(self, mid: int, content: str, mtype: str):
        if not self.initialized:
            threading.Thread(target=self.initialize_cache, daemon=True).start()
            return

        key = f"db_{mid}"
        if key in self.mem_contents:
            return

        # Embedded outside _init_lock on purpose — see _apply() in
        # _invalidate_semantic_memory_cache.
        vec = self._get_embedding(content)
        if vec is None:
            log.warning(f"Skip vectorize memory id={mid}: no embedding")
            return

        with self._init_lock:
            if key in self.mem_contents:
                return
            if self.vector_index is None:
                self.vector_index = IdMapIndex(dim=len(vec), bit_width=4)
            vec_np = np.array([vec], dtype=np.float32)
            self.vector_index.add_with_ids(vec_np, np.array([mid], dtype=np.uint64))
            self.mem_contents[key] = {"content": content, "type": mtype}
            self._save_cache()
        log.info(f"⚡ Add vector: id={mid} type={mtype}")

    def semantic_recall(self, query: str, limit: int = 3) -> list[dict]:
        if not self.initialized:
            return []

        if self.vector_index is None or len(self.vector_index) == 0:
            return []

        q_vec = self._get_embedding(query)
        if q_vec is None:
            return []

        query_np = np.array([q_vec], dtype=np.float32)
        scores, ids = self.vector_index.search(query_np, k=limit)

        source_by_id: dict[int, str] = {}
        candidate_ids = [int(mid) for mid in ids[0] if mid != -1] if len(ids) and len(ids[0]) else []
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            conn = _get_db()
            try:
                rows = conn.execute(
                    f"SELECT id, source FROM memories WHERE id IN ({placeholders})", candidate_ids
                ).fetchall()
                source_by_id = {int(row["id"]): str(row["source"] or "") for row in rows}
            finally:
                conn.close()

        results = []
        if len(ids) > 0 and len(ids[0]) > 0:
            for score, mid_val in zip(scores[0], ids[0]):
                if mid_val != -1:
                    key = f"db_{mid_val}"
                    if key in self.mem_contents:
                        info = self.mem_contents[key]
                        results.append({
                            "id": mid_val,
                            "type": info["type"],
                            "content": info["content"],
                            "source": source_by_id.get(int(mid_val), ""),
                            "score": float(score)
                        })
        if results:
            log.info("🔮 Semantic recall")
        return results


# ---------------------------------------------------------------------------
# Context Builder
# ---------------------------------------------------------------------------

def filter_context_memories(memories: list[dict]) -> list[dict]:
    """Keep unverified legacy distillations out of live LLM context."""
    return [
        memory for memory in memories
        if memory.get("source") not in {
            "conversation_learning",
            "conversation_distillation",
        }
    ]


def build_memory_context(user_message: str) -> str:
    """Nạp memory cho general route.

    Không tính điểm/vector/từ khóa theo câu hỏi (semantic_recall và FTS recall
    từng ở đây gây "mù" — luôn trả top-k dù không liên quan, hoặc trật lất
    khi trùng chữ ngẫu nhiên). Thay vào đó nạp cố định top memory quan trọng
    nhất theo importance đã gán lúc lưu — cùng một tập hợp mỗi lượt, dễ đoán,
    không phụ thuộc embedding server.
    """
    if len(user_message) <= 5:
        return ""

    parts: list[str] = []

    important = filter_context_memories(get_important_memories(limit=5))
    if important:
        imp_lines = [f"  - [{m['type']}] {m['content']}" for m in important]
        parts.append("KEY FACTS:\n" + "\n".join(imp_lines))

    try:
        from engine.router.replay import recent_outcomes_context as get_session_tool_context
        sess_tools = get_session_tool_context(limit=3)
        if sess_tools:
            parts.append(sess_tools)
    except Exception:
        pass

    return "\n\n".join(parts) if parts else ""


# ---------------------------------------------------------------------------
# Conversation Quality Metrics (Feature 4)
# ---------------------------------------------------------------------------

def save_feedback(message_id: str, rating: int, comment: str = "") -> int:
    """Lưu feedback thumbs up/down từ người dùng về phản hồi của JARVIS.
    rating: 1 = thumbs up, -1 = thumbs down, 0 = neutral.
    """
    conn = _get_db()
    cur = conn.execute(
        "INSERT INTO feedback (message_id, rating, comment, created_at) VALUES (?, ?, ?, ?)",
        (str(message_id), int(rating), str(comment), time.time())
    )
    fb_id = cur.lastrowid
    conn.commit()
    conn.close()
    log.info(f"Feedback saved: id={fb_id}, rating={rating}, msg_id={message_id!r}")
    return fb_id


def get_feedback_stats(days: int = 30) -> dict:
    """Trả về thống kê feedback trong N ngày gần nhất."""
    since = time.time() - days * 86400
    conn = _get_db()
    rows = conn.execute(
        "SELECT rating, COUNT(*) as cnt FROM feedback WHERE created_at >= ? GROUP BY rating",
        (since,)
    ).fetchall()
    conn.close()
    stats = {"thumbs_up": 0, "thumbs_down": 0, "total": 0, "days": days}
    for row in rows:
        if row["rating"] > 0:
            stats["thumbs_up"] += row["cnt"]
        elif row["rating"] < 0:
            stats["thumbs_down"] += row["cnt"]
        stats["total"] += row["cnt"]
    if stats["total"] > 0:
        stats["satisfaction_pct"] = round(stats["thumbs_up"] / stats["total"] * 100, 1)
    else:
        stats["satisfaction_pct"] = None
    return stats


def delete_memory_by_source(source: str) -> bool:
    """Xóa tất cả memories và FTS mapping liên quan đến một source xác định."""
    if not source or not isinstance(source, str) or not source.strip():
        log.warning("⚠️ Guard: Refused to delete memory. Source is empty or invalid.")
        return False
        
    source = source.strip()
    # Rào chắn bảo vệ: Ngăn chặn xóa bừa bãi bằng nguồn quá ngắn hoặc chứa từ khóa nguy hiểm
    if len(source) < 3 or source.lower() in ["none", "null", "all", "*", "conversation", "reflection"]:
        log.warning(f"⚠️ Guard: Refused to delete memory. Source {source!r} is too short or dangerous.")
        return False

    try:
        conn = _get_db()
        rows = conn.execute("SELECT id FROM memories WHERE source = ?", (source,)).fetchall()
        ids_to_delete = [r["id"] for r in rows]
        
        if not ids_to_delete:
            conn.close()
            return False
            
        conn.execute("DELETE FROM memories WHERE source = ?", (source,))
        conn.execute("DELETE FROM memory_fts WHERE source = ?", (source,))
        conn.commit()
        conn.close()
        
        # Đồng bộ xóa trong Semantic Memory metadata cache
        sm = SemanticMemoryEngine.get_instance()
        cleaned_any = False
        with sm._init_lock:
            for mid in ids_to_delete:
                key = f"db_{mid}"
                if key in sm.mem_contents:
                    del sm.mem_contents[key]
                    cleaned_any = True
                # Dropping only the metadata stranded the vector permanently:
                # incremental sync never revisits ids that are absent from
                # mem_contents, so orphans keep taking top-k slots and then get
                # filtered out, silently shrinking every recall.
                if sm.vector_index is not None:
                    try:
                        sm.vector_index.remove(mid)
                        cleaned_any = True
                    except Exception:
                        pass
            if cleaned_any:
                sm._save_cache()
            
        log.info(f"🗑️ Deleted {len(ids_to_delete)} memories with source={source}")
        return True
    except Exception as e:
        log.error(f"Failed to delete memory by source: {e}")
        return False


# ---------------------------------------------------------------------------
# Module init
# ---------------------------------------------------------------------------

init_db()
# Không auto-start initialize_cache ở đây — server sẽ gọi sau khi set embed client
