"""Gmail SMTP — luôn giả lập, không gửi thật (spec mục 10)."""
import pytest

from engine.jobs import mailer


def test_config_requires_both(monkeypatch):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    assert mailer.config() is None
    monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
    assert mailer.config() == ("a@gmail.com", "abcdefghijklmnop")


def test_build_message_has_pdf_attachment(tmp_path):
    pdf = tmp_path / "CV.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    msg = mailer.build_message("a@gmail.com", "hr@x.vn", "Ứng tuyển Kế toán – A", "Nội dung", "a@gmail.com", pdf, "CV_A.pdf")
    assert msg["To"] == "hr@x.vn" and msg["Reply-To"] == "a@gmail.com"
    att = [p for p in msg.iter_attachments()]
    assert att[0].get_filename() == "CV_A.pdf" and att[0].get_content_type() == "application/pdf"


def test_send_uses_ssl_login_and_send(monkeypatch, tmp_path):
    pdf = tmp_path / "CV.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    monkeypatch.setenv("GMAIL_ADDRESS", "a@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            seen["host"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def login(self, user, password):
            seen["login"] = (user, password)

        def send_message(self, msg):
            seen["to"] = msg["To"]

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    mailer.send("hr@x.vn", "S", "B", "a@gmail.com", pdf, "CV_A.pdf")
    assert seen == {"host": ("smtp.gmail.com", 465), "login": ("a@gmail.com", "pw"), "to": "hr@x.vn"}


def test_send_without_config_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_ADDRESS", raising=False)
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    with pytest.raises(RuntimeError, match="Chưa cấu hình Gmail"):
        mailer.send("hr@x.vn", "S", "B", "", tmp_path / "CV.pdf", "CV.pdf")
