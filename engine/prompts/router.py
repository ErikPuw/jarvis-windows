"""Quản lý các prompt định tuyến: gate, classifier, offer_context (spec 2026-09-25 mục 2).
Giống từng ký tự bản cũ trong code — tests/golden/ giữ bản chụp."""
import json

from engine.prompts import load


def build_gate_system_prompt(has_attachment: bool = False) -> str:
    att_opt = (
        "- attachment_clarify: có tệp đính kèm đáng tin cậy nhưng chưa rõ người dùng muốn đọc/phân tích hay tạo/sửa nó "
        "(nếu đã rõ thì chọn orchestrator).\n" if has_attachment else ""
    )
    return load("router_gate", attachment_option=att_opt)


def build_classifier_system_prompt(
    attachment_metadata: dict | None = None, extra_context: str = "", offer_context: str = ""
) -> str:
    system = load("classifier").rstrip("\n")
    if attachment_metadata is not None:
        system += " Tệp đính kèm đáng tin cậy: " + json.dumps(attachment_metadata, ensure_ascii=False)
    if extra_context:
        system += " " + extra_context
    if offer_context:
        system += " " + offer_context
    return system


def build_offer_context(ask: str, tool: str = "") -> str:
    """Lời đề nghị đang chờ, đưa cho classifier khi ngài đáp lại nó."""
    if not ask:
        return ""
    return (f"Lượt trước Jarvis đã đề nghị (chưa làm): {ask}"
            + (f" [công cụ: {tool}]" if tool else "")
            + ". Nếu yêu cầu hiện tại là đồng ý hoặc sửa lại đề nghị đó, chọn agent theo đề nghị "
              "và viết query là câu lệnh cụ thể.")
