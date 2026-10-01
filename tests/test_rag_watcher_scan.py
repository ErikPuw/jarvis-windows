"""scan_existing của RAGFolderWatcher chỉ được dọn chunk mồ côi TRONG thư mục thả file, không đụng tài liệu lưu qua @rag."""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core import rag_watcher


class _FakeRag:
    def __init__(self, chunks):
        self.chunks = chunks
        self.embed_client = object()
        self.active_seen = None

    async def sync_lifecycle(self, active):
        self.active_seen = {str(Path(p).resolve()) for p in active}
        return 0

    async def process_document(self, file_path):
        return {"success": True, "chunks": 1}


def test_scan_keeps_chunks_from_outside_the_watch_folder(monkeypatch, tmp_path):
    watch, other = tmp_path / "documents", tmp_path / "uploads"
    watch.mkdir(); other.mkdir()
    saved = other / "saved_by_rag.pdf"                # lưu qua '@rag lưu': nằm ngoài thư mục thả file
    gone = watch / "deleted_meanwhile.txt"            # từng thả vào thư mục nhưng đã bị xoá khi server tắt
    fake = _FakeRag([{"file_path": str(saved), "filename": saved.name},
                     {"file_path": str(gone), "filename": gone.name}])
    import engine.core.rag_engine as rag_engine
    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher, "WATCH_DB_PATH", tmp_path / "watch.db")

    asyncio.run(rag_watcher.RAGFolderWatcher(str(watch)).scan_existing())

    assert str(saved.resolve()) in fake.active_seen          # tài liệu @rag được giữ
    assert str(gone.resolve()) not in fake.active_seen       # chunk mồ côi trong thư mục thả file vẫn bị dọn


def test_already_indexed_file_is_not_indexed_again(monkeypatch, tmp_path):
    watch = tmp_path / "documents"; watch.mkdir()
    f = watch / "a.txt"; f.write_text("nội dung", encoding="utf-8")
    fake = _FakeRag([])
    calls = []

    async def counting(file_path):
        calls.append(file_path)
        return {"success": True, "chunks": 1}
    fake.process_document = counting
    import engine.core.rag_engine as rag_engine
    monkeypatch.setattr(rag_engine, "get_rag_engine", lambda: fake)
    monkeypatch.setattr(rag_watcher, "WATCH_DB_PATH", tmp_path / "watch.db")

    async def twice():
        w = rag_watcher.RAGFolderWatcher(str(watch))
        await w.scan_existing()
        await w.scan_existing()
    asyncio.run(twice())
    assert len(calls) == 1
