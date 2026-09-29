"""Regression tests for RAGEngine.remove_by_document_id.

Chunks persisted through the chat-attachment "luu lai" flow
(engine.tools.rag_tool.handle_rag_query -> RAGEngine.index_prepared_pages)
carry a `document_id` but no user-facing file_path (their file_path points at
internal page-XXXX.md files under data/rag_index/documents/<hash>/pages/).
remove_document() can only match by file_path/filename, so there was no way
to remove those chunks from the index at all.

Run: python tests/test_rag_remove_by_document_id.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.core.rag_engine import RAGEngine


class FakeVectorIndex:
    def __init__(self):
        self.removed = []

    def remove(self, chunk_id):
        self.removed.append(int(chunk_id))


def _engine_with_chunks(chunks):
    rag = RAGEngine(dim=8, persistent=False)
    rag.chunks = chunks
    rag.vector_index = FakeVectorIndex()
    rag._rebuild_bm25()
    return rag


def test_remove_by_document_id_removes_only_matching_chunks():
    rag = _engine_with_chunks([
        {"id": 1, "document_id": "doc-a", "content": "noi dung a1", "filename": "a.pdf"},
        {"id": 2, "document_id": "doc-a", "content": "noi dung a2", "filename": "a.pdf"},
        {"id": 3, "document_id": "doc-b", "content": "noi dung b1", "filename": "b.pdf"},
    ])

    removed = asyncio.run(rag.remove_by_document_id("doc-a"))

    assert removed == 2, removed
    assert [c["id"] for c in rag.chunks] == [3], rag.chunks
    assert sorted(rag.vector_index.removed) == [1, 2], rag.vector_index.removed
    assert rag.enabled is True


def test_remove_by_document_id_no_match_is_a_no_op():
    rag = _engine_with_chunks([
        {"id": 1, "document_id": "doc-a", "content": "noi dung a1", "filename": "a.pdf"},
    ])

    removed = asyncio.run(rag.remove_by_document_id("doc-does-not-exist"))

    assert removed == 0
    assert len(rag.chunks) == 1
    assert rag.vector_index.removed == []


def test_remove_by_document_id_ignores_chunks_without_document_id():
    """process_document() chunks (folder-watcher pipeline) have no
    document_id at all - .get("document_id") must not match None == None."""
    rag = _engine_with_chunks([
        {"id": 1, "content": "watcher chunk, no document_id", "filename": "watched.txt"},
    ])

    removed = asyncio.run(rag.remove_by_document_id(""))

    assert removed == 0, "an empty/falsy document_id must not sweep up chunks that lack one"
    assert len(rag.chunks) == 1


if __name__ == "__main__":
    test_remove_by_document_id_removes_only_matching_chunks()
    test_remove_by_document_id_no_match_is_a_no_op()
    test_remove_by_document_id_ignores_chunks_without_document_id()
    print("OK: RAGEngine.remove_by_document_id works")
