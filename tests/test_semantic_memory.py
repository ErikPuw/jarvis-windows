"""Regression tests for the semantic memory cache in engine.core.memory.

Every path is redirected to a temp dir first — this never touches data/jarvis.db.
Run: python tests/test_semantic_memory.py
"""
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np

import engine.core.memory as memory

# Redirect persistence BEFORE anything writes. init_db() already ran against the
# real path at import time (CREATE TABLE IF NOT EXISTS only), but from here on
# every read/write in this process goes to the sandbox.
_TMP = Path(tempfile.mkdtemp(prefix="jarvis_memtest_"))
memory.DB_PATH = _TMP / "jarvis.db"
memory.SEMANTIC_DIR = _TMP / "semantic"
memory.SEMANTIC_VEC_PATH = memory.SEMANTIC_DIR / "semantic_vectors.tvim"
memory.SEMANTIC_META_PATH = memory.SEMANTIC_DIR / "semantic_metadata.json"
memory.init_db()


class FakeIndex:
    """Stands in for turbovec IdMapIndex, recording what gets removed."""
    def __init__(self, dim=8, bit_width=4):
        self.dim = dim
        self.removed = []
        self.ids = []

    def remove(self, mid):
        self.removed.append(int(mid))

    def add_with_ids(self, vecs, ids):
        self.ids.extend(int(i) for i in ids)

    def write(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text("fake-index", encoding="utf-8")

    def __len__(self):
        return len(self.ids)


def _fresh_engine():
    sm = memory.SemanticMemoryEngine.get_instance()
    sm.initialized = True
    sm.vector_index = FakeIndex()
    sm.mem_contents = {}
    sm._embed_func = None
    sm._embed_client = None
    return sm


def _wait_until(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _seed_memories(rows):
    """rows: list of (content, source). Returns inserted ids."""
    conn = memory._get_db()
    ids = []
    for content, source in rows:
        cur = conn.execute(
            "INSERT INTO memories (type, content, source, importance, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            ("fact", content, source, 1, time.time()),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    conn.close()
    return ids


def test_save_cache_survives_a_failed_write():
    """A crash mid-write must not corrupt the cache.

    _load_cache() reacts to invalid JSON by deleting both files and
    re-embedding the whole corpus, so an in-place truncating write turned one
    interrupted save into a full re-embed.
    """
    sm = _fresh_engine()
    sm.mem_contents = {"db_1": {"content": "good", "type": "fact"}}
    sm._save_cache()
    before = memory.SEMANTIC_META_PATH.read_text(encoding="utf-8")
    assert json.loads(before)["db_1"]["content"] == "good"

    original_dump = memory.json.dump

    def exploding_dump(obj, fp, **kwargs):
        fp.write('{"db_1": {"content": "par')  # partial write, then die
        raise RuntimeError("disk died mid-write")

    memory.json.dump = exploding_dump
    try:
        sm.mem_contents = {"db_1": {"content": "newer", "type": "fact"}}
        sm._save_cache()  # swallows the error by design
    finally:
        memory.json.dump = original_dump

    after = memory.SEMANTIC_META_PATH.read_text(encoding="utf-8")
    assert after == before, "failed write corrupted the existing cache file"
    assert json.loads(after)["db_1"]["content"] == "good"


def test_delete_by_source_removes_vectors_not_just_metadata():
    """Orphan vectors kept winning top-k slots and then got filtered out,
    silently shrinking recall results forever."""
    sm = _fresh_engine()
    ids = _seed_memories([("noi dung mot", "test_source"), ("noi dung hai", "test_source")])
    for mid in ids:
        sm.mem_contents[f"db_{mid}"] = {"content": "x", "type": "fact"}
        sm.vector_index.ids.append(mid)

    assert memory.delete_memory_by_source("test_source") is True

    for mid in ids:
        assert f"db_{mid}" not in sm.mem_contents, "metadata not cleaned"
    assert sorted(sm.vector_index.removed) == sorted(ids), (
        f"vectors left orphaned: removed={sm.vector_index.removed} expected={ids}"
    )


def test_embedding_runs_outside_the_init_lock():
    """_get_embedding is an HTTP call that can block for 30s; holding
    _init_lock across it stalls every other cache reader and writer."""
    sm = _fresh_engine()
    observed = []

    def probing_embed(text):
        # threading.Lock is not reentrant: a successful non-blocking acquire
        # from this thread proves the lock was not already held.
        free = sm._init_lock.acquire(blocking=False)
        observed.append(free)
        if free:
            sm._init_lock.release()
        return np.zeros(8, dtype=np.float32)

    sm.set_embed_func(probing_embed)
    memory._invalidate_semantic_memory_cache(77, content="noi dung moi", mem_type="fact")

    assert _wait_until(lambda: observed), "embedding was never called"
    assert observed == [True], "embedding ran while holding _init_lock"
    assert _wait_until(lambda: "db_77" in sm.mem_contents), "updated entry never landed"


def test_invalidate_with_no_content_drops_vector_and_metadata():
    sm = _fresh_engine()
    sm.mem_contents["db_55"] = {"content": "cu", "type": "fact"}
    memory._invalidate_semantic_memory_cache(55)
    assert _wait_until(lambda: "db_55" not in sm.mem_contents), sm.mem_contents
    assert 55 in sm.vector_index.removed, sm.vector_index.removed


def test_failed_embedding_drops_the_entry_instead_of_keeping_a_stale_vector():
    sm = _fresh_engine()
    sm.mem_contents["db_88"] = {"content": "cu", "type": "fact"}
    sm.set_embed_func(lambda text: None)  # embedding server down
    memory._invalidate_semantic_memory_cache(88, content="noi dung moi", mem_type="fact")
    assert _wait_until(lambda: "db_88" not in sm.mem_contents), sm.mem_contents
    assert 88 in sm.vector_index.removed


def _cleanup():
    shutil.rmtree(_TMP, ignore_errors=True)


if __name__ == "__main__":
    try:
        test_save_cache_survives_a_failed_write()
        test_delete_by_source_removes_vectors_not_just_metadata()
        test_embedding_runs_outside_the_init_lock()
        test_invalidate_with_no_content_drops_vector_and_metadata()
        test_failed_embedding_drops_the_entry_instead_of_keeping_a_stale_vector()
        print("OK: all semantic memory regression tests passed")
    finally:
        _cleanup()
