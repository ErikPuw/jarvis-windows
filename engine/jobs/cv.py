"""Hồ sơ → CV.docx (officecli) → CV.pdf (Word COM) (spec mục 7).
officecli 1.0.152 chưa có plugin xuất PDF; Word trên máy xuất được (đã thử 2026-09-27)."""
import asyncio
import json
import logging
from pathlib import Path

from engine.jobs import store
from engine.tools.office_tools import _run_officecli

log = logging.getLogger("jarvis.jobs.cv")

_WD_FORMAT_PDF = 17


def _p(text: str, **props) -> dict:
    return {"command": "add", "parent": "/body", "type": "paragraph", "props": {"text": text, **props}}


def batch_commands(profile: dict) -> list[dict]:
    cmds = [_p(profile.get("full_name", ""), style="Title")]
    contact = " · ".join(x for x in (profile.get("phone"), profile.get("email"), profile.get("location")) if x)
    if contact:
        cmds.append(_p(contact))
    sections = [
        ("Vị trí ứng tuyển", [", ".join(profile["positions"])] if profile.get("positions") else []),
        ("Kinh nghiệm làm việc", profile.get("experience") or []),
        ("Học vấn", profile.get("education") or []),
        ("Chứng chỉ", profile.get("certificates") or []),
        ("Kỹ năng", profile.get("skills") or []),
        ("Ngoại ngữ", [f"Tiếng Anh: {profile['english']}"] if profile.get("english") else []),
    ]
    for heading, items in sections:
        if not items:
            continue
        cmds.append(_p(heading, style="Heading1"))
        cmds.extend(_p(item, listStyle="bullet") for item in items)
    return cmds


def _to_pdf(docx: Path, pdf: Path) -> None:
    """Word ẩn, riêng một tiến trình (DispatchEx) để không đụng Word ngài đang mở."""
    import pythoncom
    import win32com.client
    pythoncom.CoInitialize()
    try:
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        try:
            doc = word.Documents.Open(str(docx), False, True)
            doc.SaveAs2(str(pdf), _WD_FORMAT_PDF)
            doc.Close(False)
        finally:
            word.Quit()
    finally:
        pythoncom.CoUninitialize()


async def build_cv(profile: dict) -> tuple[Path | None, Path | None, str]:
    """(docx, pdf, lỗi). Word lỗi → giữ docx, pdf=None. Không bao giờ ném."""
    store.DATA_DIR.mkdir(parents=True, exist_ok=True)
    docx, pdf, batch = store.file_path("CV.docx"), store.file_path("CV.pdf"), store.file_path("cv_batch.json")
    for f in (docx, pdf):
        f.unlink(missing_ok=True)
    batch.write_text(json.dumps(batch_commands(profile), ensure_ascii=False), encoding="utf-8")
    steps = (("create", str(docx)), ("batch", str(docx), "--input", str(batch), "--json"), ("close", str(docx)))
    try:
        for args in steps:
            rc, out, err = await _run_officecli(*args)
            if rc != 0:
                return None, None, f"officecli {args[0]} lỗi: {(err or out)[:300]}"
    except Exception as exc:
        return None, None, f"officecli lỗi: {exc}"
    try:
        await asyncio.to_thread(_to_pdf, docx, pdf)
    except Exception as exc:
        log.warning("[JOBS] Word PDF export failed: %s", exc)
        return docx, None, f"Word không xuất được PDF: {exc}"
    return docx, pdf, ""
