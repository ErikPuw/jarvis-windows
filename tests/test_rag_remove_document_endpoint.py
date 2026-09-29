"""Regression tests for DELETE /api/rag/document.

Bug 1: api_rag_remove_document() called rag.remove_document() (an async
method) via asyncio.to_thread(), which only *constructs* the coroutine in the
worker thread instead of running it - the removal never executed and the
endpoint returned an unawaited coroutine object instead of an int, which then
failed to JSON-serialize.

Bug 2: even once removal ran, the endpoint never told engine.core.rag_watcher
about it. rag_watch.db's `indexed_files` row for that file survived, so
scan_existing()/_is_indexed() kept believing the file was already indexed and
would never re-index it even after the user fixed and re-saved it - the API
path and the filesystem-watcher path (which does call mark_removed) fell out
of sync.

Run: python tests/test_rag_remove_document_endpoint.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import engine.core.rag_engine as rag_engine_mod
import engine.core.rag_watcher as rag_watcher_mod
from engine.UIUX.ui_engine import api_rag_remove_document


class FakeRAGEngine:
    def __init__(self):
        self.calls = []
        self.document_id_calls = []

    async def remove_document(self, file_path: str) -> int:
        self.calls.append(file_path)
        return 3

    async def remove_by_document_id(self, document_id: str) -> int:
        self.document_id_calls.append(document_id)
        return 5


def test_remove_document_endpoint_actually_removes_and_returns_int():
    fake = FakeRAGEngine()
    original_get_rag_engine = rag_engine_mod.get_rag_engine
    original_mark_removed = rag_watcher_mod.mark_removed
    rag_engine_mod.get_rag_engine = lambda: fake
    rag_watcher_mod.mark_removed = lambda file_path: None
    try:
        result = asyncio.run(api_rag_remove_document("some/file.txt"))
    finally:
        rag_engine_mod.get_rag_engine = original_get_rag_engine
        rag_watcher_mod.mark_removed = original_mark_removed

    assert fake.calls == ["some/file.txt"], (
        f"remove_document body never ran: calls={fake.calls}"
    )
    assert result == {"success": True, "chunks_removed": 3}, result


def test_remove_document_endpoint_syncs_watch_db():
    fake = FakeRAGEngine()
    original_get_rag_engine = rag_engine_mod.get_rag_engine
    original_mark_removed = rag_watcher_mod.mark_removed
    mark_removed_calls = []
    rag_engine_mod.get_rag_engine = lambda: fake
    rag_watcher_mod.mark_removed = lambda file_path: mark_removed_calls.append(file_path)
    try:
        asyncio.run(api_rag_remove_document("some/file.txt"))
    finally:
        rag_engine_mod.get_rag_engine = original_get_rag_engine
        rag_watcher_mod.mark_removed = original_mark_removed

    expected = str(Path("some/file.txt").resolve())
    assert mark_removed_calls == [expected], (
        "watch DB was not synced after removal via the API - a future "
        f"scan_existing() would still think the file is indexed: {mark_removed_calls}"
    )


def test_remove_document_endpoint_by_document_id_skips_watch_db():
    """Chunks persisted via the chat "luu lai" flow carry a document_id but no
    user-facing file_path (rag_watch.db only tracks watcher-indexed files) -
    document_id-based removal must not touch the watch DB at all."""
    fake = FakeRAGEngine()
    original_get_rag_engine = rag_engine_mod.get_rag_engine
    original_mark_removed = rag_watcher_mod.mark_removed
    mark_removed_calls = []
    rag_engine_mod.get_rag_engine = lambda: fake
    rag_watcher_mod.mark_removed = lambda file_path: mark_removed_calls.append(file_path)
    try:
        result = asyncio.run(api_rag_remove_document(document_id="doc-abc123"))
    finally:
        rag_engine_mod.get_rag_engine = original_get_rag_engine
        rag_watcher_mod.mark_removed = original_mark_removed

    assert fake.document_id_calls == ["doc-abc123"], fake.document_id_calls
    assert fake.calls == [], "file_path removal must not run for a document_id request"
    assert mark_removed_calls == [], "watch DB has no entry for chat-persisted documents"
    assert result == {"success": True, "chunks_removed": 5}, result


def test_remove_document_endpoint_requires_an_identifier():
    fake = FakeRAGEngine()
    original_get_rag_engine = rag_engine_mod.get_rag_engine
    rag_engine_mod.get_rag_engine = lambda: fake
    try:
        response = asyncio.run(api_rag_remove_document())
    finally:
        rag_engine_mod.get_rag_engine = original_get_rag_engine

    assert response.status_code == 400, response.status_code
    body = json.loads(response.body)
    assert body["success"] is False
    assert fake.calls == [] and fake.document_id_calls == []


if __name__ == "__main__":
    test_remove_document_endpoint_actually_removes_and_returns_int()
    test_remove_document_endpoint_syncs_watch_db()
    test_remove_document_endpoint_by_document_id_skips_watch_db()
    test_remove_document_endpoint_requires_an_identifier()
    print("OK: DELETE /api/rag/document removes, returns an int, and syncs the watch DB")
