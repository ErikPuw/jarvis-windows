"""Gửi thư qua Gmail SMTP (spec mục 10). Chỉ review.apply gọi send(), và chỉ từ lệnh duyệt của ngài."""
import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def config() -> tuple[str, str] | None:
    address = os.getenv("GMAIL_ADDRESS", "").strip()
    password = os.getenv("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    return (address, password) if address and password else None


def build_message(sender: str, to: str, subject: str, body: str, reply_to: str,
                  attachment: Path, filename: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(body)
    msg.add_attachment(attachment.read_bytes(), maintype="application", subtype="pdf", filename=filename)
    return msg


def send(to: str, subject: str, body: str, reply_to: str, attachment: Path, filename: str) -> None:
    """Ném lỗi khi thiếu cấu hình hoặc SMTP lỗi; caller báo lỗi cho ngài, không tự thử lại."""
    cfg = config()
    if cfg is None:
        raise RuntimeError("Chưa cấu hình Gmail")
    address, password = cfg
    msg = build_message(address, to, subject, body, reply_to, attachment, filename)
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=30) as smtp:
        smtp.login(address, password)
        smtp.send_message(msg)
