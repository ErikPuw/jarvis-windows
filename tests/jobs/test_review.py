"""Duyệt: chỉ gửi đúng số đã duyệt, hết hạn, giới hạn/ngày, sửa, bỏ (spec mục 10). SMTP giả lập."""
import asyncio

from engine.jobs import mailer, review, store

NOW = 1_800_000_000.0
PROFILE = {"full_name": "A", "email": "a@gmail.com", "phone": "0901234567"}


def _item(n):
    return {"n": n, "title": f"Việc {n}", "company": "X", "email": f"hr{n}@x.vn", "url": f"https://x.vn/{n}",
            "score": 8, "flag": "", "reason": "hợp", "post": "tin", "body": f"thư {n}"}


def _setup(monkeypatch, jobs_data_dir, n_items=3, created=NOW, sent=None):
    store.save("pending.json", {"created_at": created, "items": [_item(i) for i in range(1, n_items + 1)]})
    store.save("profile.json", PROFILE)
    store.save("log.json", {"sent": sent or []})
    store.file_path("CV.pdf").write_bytes(b"%PDF")
    monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    calls = []
    monkeypatch.setattr(mailer, "send", lambda *a: calls.append(a))
    return calls


async def _nosleep(s):
    return None


def _apply(text, now=NOW):
    return asyncio.run(review.apply(review.parse(text), now, sleep=_nosleep))


def test_parse():
    assert review.parse("gửi 1, 3") == ("send", [1, 3], "")
    assert review.parse("Gửi 3,1,3.") == ("send", [1, 3], "")
    assert review.parse("bỏ 2") == ("drop", [2], "")
    assert review.parse("sửa thư 1: ngắn hơn") == ("edit", [1], "ngắn hơn")
    assert review.parse("gửi mail cho sếp") is None
    assert review.parse("mở nhạc") is None


def test_pending_open():
    assert review.pending_open({"created_at": NOW, "items": [1]}, NOW + review.PENDING_TTL_S)
    assert not review.pending_open({"created_at": NOW, "items": [1]}, NOW + review.PENDING_TTL_S + 1)
    assert not review.pending_open({"created_at": NOW, "items": []}, NOW)


def test_send_only_approved(monkeypatch, jobs_data_dir):
    calls = _setup(monkeypatch, jobs_data_dir)
    out = _apply("gửi 1, 3")
    assert [c[0] for c in calls] == ["hr1@x.vn", "hr3@x.vn"]
    assert calls[0][1] == "Ứng tuyển Việc 1 – A" and calls[0][3] == "a@gmail.com"
    assert calls[0][4] == store.file_path("CV.pdf") and calls[0][5] == "CV_A.pdf"
    assert out.startswith("Đã gửi 2/2.")
    assert [i["n"] for i in store.load("pending.json", {})["items"]] == [2]
    assert [s["email"] for s in store.load("log.json", {})["sent"]] == ["hr1@x.vn", "hr3@x.vn"]


def test_unknown_number_sends_nothing(monkeypatch, jobs_data_dir):
    calls = _setup(monkeypatch, jobs_data_dir)
    assert _apply("gửi 1, 7") == "Không có số 7 trong danh sách. Không làm gì cả."
    assert calls == []


def test_expired_pending_refused(monkeypatch, jobs_data_dir):
    calls = _setup(monkeypatch, jobs_data_dir, created=NOW - review.PENDING_TTL_S - 1)
    assert "hết hạn" in _apply("gửi 1") and calls == []


def test_daily_limit(monkeypatch, jobs_data_dir):
    sent = [{"at": NOW, "email": f"o{i}@y.vn", "title": "t"} for i in range(9)]
    calls = _setup(monkeypatch, jobs_data_dir, sent=sent)
    out = _apply("gửi 1, 2")
    assert len(calls) == 1 and "Còn 1 thư chưa gửi" in out
    calls.clear()
    assert _apply("gửi 2") == "Đã gửi đủ 10 thư hôm nay. Gửi tiếp vào ngày mai." and calls == []


def test_missing_config_or_pdf(monkeypatch, jobs_data_dir):
    calls = _setup(monkeypatch, jobs_data_dir)
    monkeypatch.delenv("GMAIL_APP_PASSWORD")
    assert _apply("gửi 1").startswith("Chưa cấu hình Gmail") and calls == []
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    store.file_path("CV.pdf").unlink()
    assert _apply("gửi 1").startswith("Chưa có CV.pdf") and calls == []


def test_smtp_error_stops(monkeypatch, jobs_data_dir):
    _setup(monkeypatch, jobs_data_dir)

    def boom(*a):
        raise OSError("mất mạng")
    monkeypatch.setattr(mailer, "send", boom)
    out = _apply("gửi 1, 2")
    assert out.startswith("Đã gửi 0/2.") and "Thư 1 lỗi: mất mạng" in out
    assert len(store.load("pending.json", {})["items"]) == 3


def test_drop_and_edit(monkeypatch, jobs_data_dir):
    _setup(monkeypatch, jobs_data_dir)
    assert _apply("bỏ 2") == "Đã bỏ 2."

    async def fake_write(profile, item, wish=""):
        return f"thư mới ({wish})"
    from engine.jobs import letter
    monkeypatch.setattr(letter, "write", fake_write)
    out = _apply("sửa thư 1: ngắn hơn")
    assert "thư mới (ngắn hơn)" in out
    assert store.load("pending.json", {})["items"][0]["body"] == "thư mới (ngắn hơn)"


def test_render():
    text = review.render([dict(_item(1), flag="⚠️ ưu tiên tiếng Anh")])
    assert text.startswith("Tìm được 1 việc phù hợp:")
    assert "1. Việc 1 – X (8/10) ⚠️ ưu tiên tiếng Anh" in text and "→ hr1@x.vn · https://x.vn/1" in text
    assert text.endswith('Trả lời "gửi 1, 3", "bỏ 2" hoặc "sửa thư 1: <ý muốn>".')
    assert review.render([]) == "Chưa có tin phù hợp."
