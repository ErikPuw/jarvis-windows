"""CV: batch officecli, tạo .docx thật, Word giả lập (spec mục 7)."""
import asyncio
import shutil
import subprocess

import pytest

from engine.jobs import cv

PROFILE = {
    "full_name": "Nguyễn Văn A", "phone": "0901234567", "email": "a@gmail.com", "location": "Hà Nội",
    "positions": ["kế toán"], "experience": ["Công ty X, kế toán, 2020-2023"], "education": [],
    "certificates": [], "skills": ["Excel", "MISA"], "english": "cơ bản", "expectations": "", "dealbreakers": [],
}


def test_batch_commands_title_contact_and_skip_empty_sections():
    cmds = cv.batch_commands(PROFILE)
    assert cmds[0] == {"command": "add", "parent": "/body", "type": "paragraph",
                       "props": {"text": "Nguyễn Văn A", "style": "Title"}}
    assert cmds[1]["props"] == {"text": "0901234567 · a@gmail.com · Hà Nội"}
    headings = [c["props"]["text"] for c in cmds if c["props"].get("style") == "Heading1"]
    assert headings == ["Vị trí ứng tuyển", "Kinh nghiệm làm việc", "Kỹ năng", "Ngoại ngữ"]
    bullets = [c["props"]["text"] for c in cmds if c["props"].get("listStyle") == "bullet"]
    assert bullets == ["kế toán", "Công ty X, kế toán, 2020-2023", "Excel", "MISA", "Tiếng Anh: cơ bản"]


@pytest.mark.skipif(shutil.which("officecli") is None, reason="officecli chưa cài")
def test_build_cv_real_docx_and_fake_word(monkeypatch, jobs_data_dir):
    def fake_pdf(docx, pdf):
        pdf.write_bytes(b"%PDF-1.4 fake")
    monkeypatch.setattr(cv, "_to_pdf", fake_pdf)
    docx, pdf, err = asyncio.run(cv.build_cv(PROFILE))
    assert err == "" and docx.exists() and pdf.read_bytes().startswith(b"%PDF")
    text = subprocess.run(["officecli", "view", str(docx), "text"], capture_output=True, text=True,
                          encoding="utf-8").stdout
    assert "Nguyễn Văn A" in text and "Kỹ năng" in text


@pytest.mark.skipif(shutil.which("officecli") is None, reason="officecli chưa cài")
def test_word_failure_keeps_docx_without_pdf(monkeypatch, jobs_data_dir):
    def broken(docx, pdf):
        raise RuntimeError("Word không mở được")
    monkeypatch.setattr(cv, "_to_pdf", broken)
    docx, pdf, err = asyncio.run(cv.build_cv(PROFILE))
    assert docx.exists() and pdf is None and "Word không xuất được PDF" in err


def test_officecli_error_is_reported(monkeypatch, jobs_data_dir):
    async def fail(*args, timeout=120):
        return 1, "", "boom"
    monkeypatch.setattr(cv, "_run_officecli", fail)
    assert asyncio.run(cv.build_cv(PROFILE)) == (None, None, "officecli create lỗi: boom")
