"""Runner: lệnh @jobs, phỏng vấn tới lúc tạo CV, tìm việc tạo danh sách chờ (spec mục 5, 6, 10)."""
import asyncio
import time
from pathlib import Path

from engine.jobs import runner, store
from engine.router.types import RouteDecision, TurnContext

PROFILE = {"full_name": "A", "phone": "0901234567", "email": "a@gmail.com", "location": "Hà Nội",
           "positions": ["kế toán"], "experience": [], "education": [], "certificates": [], "skills": [],
           "english": "không", "expectations": "", "dealbreakers": []}


def _handle(query, source="mention"):
    sent = []

    async def send(ws, data):
        sent.append(data)
        return True
    ctx = TurnContext(ws=object(), send_json=send)
    out = asyncio.run(runner.handle(RouteDecision("jobs", query, source), ctx))
    assert sent[-1] == {"type": "stream_end"} and sent[0] == {"type": "text_chunk", "text": out}
    return out


def test_help_and_no_profile():
    assert _handle("").startswith("Lệnh tìm việc:")
    assert _handle("tìm") == runner.NO_PROFILE


def test_interview_to_cv(monkeypatch):
    monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")

    async def fake_cv(profile):
        return Path("CV.docx"), Path("CV.pdf"), ""
    from engine.jobs import cv
    monkeypatch.setattr(cv, "build_cv", fake_cv)
    assert _handle("phỏng vấn").startswith("[Phỏng vấn 1/12]")
    for reply in ["Nguyễn Văn A", "0901234567", "bỏ qua", "Hà Nội", "kế toán", "hết",
                  "ĐH X", "", "Excel", "không", "10 triệu", "ca đêm"]:
        _handle(reply or "bỏ qua", source="session")
    out = _handle("đúng", source="session")
    assert out.startswith("Đã lưu hồ sơ.") and "Đã tạo CV" in out
    prof = store.load("profile.json", {})
    assert prof["full_name"] == "Nguyễn Văn A" and prof["email"] == "a@gmail.com"
    assert store.load("interview.json", {})["status"] == "done"


def test_run_search_makes_pending_and_appends(monkeypatch):
    store.save("profile.json", PROFILE)
    from engine.jobs import letter, search

    async def fake_find(profile, log_data):
        log_data.setdefault("seen", []).append("https://x.vn/1")
        return [{"title": "Kế toán", "company": "X", "email": "hr@x.vn", "url": "https://x.vn/1",
                 "score": 8, "flag": "", "reason": "hợp", "post": "tin"}]

    async def fake_write(profile, item, wish=""):
        return "thư"
    monkeypatch.setattr(search, "find_jobs", fake_find)
    monkeypatch.setattr(letter, "write", fake_write)
    out = asyncio.run(runner.run_search())
    assert out.startswith("Tìm được 1 việc phù hợp:")
    assert [i["n"] for i in store.load("pending.json", {})["items"]] == [1]
    assert store.load("log.json", {})["seen"] == ["https://x.vn/1"]
    asyncio.run(runner.run_search())
    assert [i["n"] for i in store.load("pending.json", {})["items"]] == [1, 2]


def test_one_post_text(monkeypatch):
    store.save("profile.json", PROFILE)
    from engine.jobs import letter, search
    seen = {}

    async def fake_eval(profile, log_data, text, url=""):
        seen["args"] = (text, url)
        return None
    monkeypatch.setattr(search, "evaluate", fake_eval)
    out = _handle("tin Tuyển kế toán, gửi CV về hr@x.vn")
    assert seen["args"] == ("Tuyển kế toán, gửi CV về hr@x.vn", "") and out.startswith("Tin này bị loại")
    assert _handle("tin").startswith("Gửi kèm nội dung tin hoặc link")


def test_review_source_goes_to_review(monkeypatch):
    from engine.jobs import review
    seen = {}

    async def fake_apply(cmd, now=None, sleep=None):
        seen["cmd"] = cmd
        return "đã xử lý"
    monkeypatch.setattr(review, "apply", fake_apply)
    assert _handle("gửi 2", source="review") == "đã xử lý" and seen["cmd"] == ("send", [2], "")


def test_status():
    out = _handle("trạng thái")
    assert "Phỏng vấn: chưa bắt đầu" in out and "Đã gửi hôm nay: 0/10" in out
