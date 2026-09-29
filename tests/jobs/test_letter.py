"""Thư xin việc: kiểm tra bằng code, soạn lại 1 lần (spec mục 9)."""
import asyncio
from types import SimpleNamespace

from engine.jobs import letter

PROFILE = {"full_name": "Nguyễn Văn A", "phone": "0901 234 567", "email": "a@gmail.com",
           "positions": ["kế toán"], "experience": [], "skills": []}
ITEM = {"title": "Kế toán viên", "company": "Công ty X", "post": "Tuyển kế toán, gửi CV về hr@x.vn"}
GOOD = ("Kính gửi Anh/Chị phụ trách tuyển dụng, tôi ứng tuyển vị trí Kế toán viên. CV đính kèm. "
        "Trân trọng, Nguyễn Văn A, 0901234567, a@gmail.com")


def test_letter_ok_rules():
    assert letter.letter_ok(GOOD, PROFILE)
    assert not letter.letter_ok("", PROFILE)
    assert not letter.letter_ok(GOOD + " Xem thêm https://evil.vn", PROFILE)
    assert not letter.letter_ok(GOOD + " Liên hệ khác: boss@evil.vn", PROFILE)
    assert not letter.letter_ok(GOOD + " Gọi 0988 777 666", PROFILE)
    assert not letter.letter_ok("chữ " * 401, PROFILE)


def test_subject():
    assert letter.subject(ITEM, PROFILE) == "Ứng tuyển Kế toán viên – Nguyễn Văn A"


def _fake(monkeypatch, outputs, calls):
    async def fake(**kw):
        calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=outputs.pop(0)))])
    monkeypatch.setattr(letter.llm_server, "call_llm", fake)


def test_write_retries_once_then_gives_up(monkeypatch):
    calls = []
    _fake(monkeypatch, ["Gửi https://x.vn", GOOD], calls)
    assert asyncio.run(letter.write(PROFILE, ITEM)) == GOOD and len(calls) == 2
    calls = []
    _fake(monkeypatch, ["Gửi https://x.vn", "cũng www.x.vn"], calls)
    assert asyncio.run(letter.write(PROFILE, ITEM)) is None and len(calls) == 2


def test_write_frames_post_and_passes_wish(monkeypatch):
    calls = []
    _fake(monkeypatch, [GOOD], calls)
    asyncio.run(letter.write(PROFILE, ITEM, wish="ngắn hơn"))
    user = calls[0]["messages"][1]["content"]
    assert '<du_lieu nguon="tin_tuyen_dung">' in user and "Yêu cầu chỉnh sửa của ứng viên: ngắn hơn" in user
