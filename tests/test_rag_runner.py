"""@rag runner: lệnh con cố định, "lưu" chỉ là lệnh khi có tệp đính kèm."""
import asyncio
from types import SimpleNamespace

import engine.core.rag_engine as rag_engine_mod
import engine.rag.runner as runner
from engine.rag.runner import parse
from engine.router.types import RouteDecision, TurnContext


def test_parse_subcommands():
    assert parse("", False) == ("help", "")
    assert parse("danh sách", False) == ("list", "")
    assert parse("xóa abc123", False) == ("delete", "abc123")
    assert parse("xoá abc123", False) == ("delete", "abc123")
    assert parse("lưu", True) == ("save", "")


def test_luu_without_attachment_is_a_question():
    assert parse("lưu trữ hồ sơ thế nào", False) == ("ask", "lưu trữ hồ sơ thế nào")
    assert parse("lưu", False) == ("ask", "lưu")


def test_xoa_with_multi_word_argument_is_a_question():
    assert parse("xóa nợ là gì", False) == ("ask", "xóa nợ là gì")


def test_other_text_is_a_question():
    assert parse("điều khoản phạt hợp đồng", False) == ("ask", "điều khoản phạt hợp đồng")


class FakeRAG:
    def __init__(self, chunks=None, results=None):
        self.chunks = chunks or []
        self.results = results or []
        self.embed_client = object()
        self.retrieve_kwargs = None
        self.removed_ids = []

    async def try_self_heal(self, embed_client=None):
        pass

    async def retrieve(self, query, **kwargs):
        self.retrieve_kwargs = kwargs
        return self.results

    async def remove_by_document_id(self, document_id):
        self.removed_ids.append(document_id)
        return 2 if document_id == "doc1" else 0

    async def remove_document(self, file_path):
        return 0


def _run(query, rag, monkeypatch, attachment=None):
    monkeypatch.setattr(rag_engine_mod, "get_rag_engine", lambda: rag)
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    ctx = TurnContext(ws=SimpleNamespace(), send_json=send, attachment_context=attachment)
    return asyncio.run(runner.handle(RouteDecision("rag", query, "mention"), ctx))


def test_ask_on_empty_store_says_so_without_llm(monkeypatch):
    out = _run("điều khoản phạt", FakeRAG(), monkeypatch)
    assert out == runner.EMPTY


def test_ask_with_no_relevant_chunks_does_not_call_llm(monkeypatch):
    rag = FakeRAG(chunks=[{"id": 0}], results=[])
    out = _run("điều khoản phạt", rag, monkeypatch)
    assert out == runner.NO_MATCH
    assert rag.retrieve_kwargs["min_score"] == runner.MIN_SCORE


def test_ask_answers_from_evidence_with_sources(monkeypatch):
    chunk = {"id": 7, "content": "Phạt 10% giá trị hợp đồng.", "filename": "hd.pdf", "page_number": 3}
    rag = FakeRAG(chunks=[chunk], results=[chunk])
    seen = {}

    async def fake_llm(messages, **kwargs):
        seen["user"] = messages[-1]["content"]
        msg = SimpleNamespace(content="Phạt 10%.")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])
    import engine.server.llm_server as llm_server
    monkeypatch.setattr(llm_server, "call_llm", fake_llm)

    out = _run("điều khoản phạt", rag, monkeypatch)
    assert "Phạt 10% giá trị hợp đồng." in seen["user"]
    assert out.startswith("Phạt 10%.") and "hd.pdf (trang 3)" in out


def test_list_groups_chunks_by_document(monkeypatch):
    rag = FakeRAG(chunks=[
        {"id": 0, "document_id": "doc1", "filename": "hd.pdf"},
        {"id": 1, "document_id": "doc1", "filename": "hd.pdf"},
        {"id": 2, "filename": "note.txt"},
    ])
    out = _run("danh sách", rag, monkeypatch)
    assert "hd.pdf" in out and "doc1" in out and "2 đoạn" in out
    assert "note.txt" in out


def test_delete_by_document_id(monkeypatch):
    rag = FakeRAG(chunks=[{"id": 0, "document_id": "doc1"}])
    out = _run("xóa doc1", rag, monkeypatch)
    assert rag.removed_ids == ["doc1"] and "2 đoạn" in out


def test_delete_unknown_id_reports_not_found(monkeypatch):
    out = _run("xóa khongco", FakeRAG(), monkeypatch)
    assert "Không tìm thấy" in out
