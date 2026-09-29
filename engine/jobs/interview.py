"""Phỏng vấn tạo hồ sơ: câu hỏi cố định, trạng thái lưu file (spec mục 6).
Hàm thuần: nhận state, trả state mới; runner lo đọc/ghi file."""
import re

from engine.jobs import ENGLISH_LEVELS, SESSION_IDLE_S

QUESTIONS = [
    ("full_name", "Họ tên đầy đủ của ngài là gì?"),
    ("phone", "Số điện thoại liên hệ?"),
    ("email", 'Email liên hệ? (nói "bỏ qua" để dùng địa chỉ Gmail đang cấu hình)'),
    ("location", "Ngài đang sống ở tỉnh/thành nào?"),
    ("positions", "Ngài muốn ứng tuyển vị trí gì? (tối đa 3, cách nhau dấu phẩy)"),
    ("experience", 'Kể một kinh nghiệm làm việc: công ty, chức danh, thời gian, việc đã làm. Nói "hết" khi đã kể xong.'),
    ("education", "Học vấn của ngài? (trường, ngành, năm; mỗi bằng một dòng)"),
    ("certificates", "Chứng chỉ ngài có? (cách nhau dấu phẩy)"),
    ("skills", "Kỹ năng của ngài? (cách nhau dấu phẩy)"),
    ("english", "Trình độ tiếng Anh: không / cơ bản / giao tiếp / thành thạo?"),
    ("expectations", "Mức lương mong muốn, khu vực làm việc, làm từ xa hay tại văn phòng?"),
    ("dealbreakers", "Điều kiện ngài không chấp nhận? (cách nhau dấu phẩy)"),
]
N = len(QUESTIONS)
CONFIRM_HINT = 'Nói "đúng" để lưu, hoặc "sửa câu N" để sửa.'
PAUSED = 'Đã tạm dừng phỏng vấn. Nói "@jobs tiếp tục" để làm tiếp.'
_EDIT = re.compile(r"^sửa câu\s+(\d+)$")


def _norm(text) -> str:
    return " ".join(str(text or "").lower().split()).strip(" .!?")


def prompt(index: int) -> str:
    return f"[Phỏng vấn {index + 1}/{N}] {QUESTIONS[index][1]}"


def summary(state: dict) -> str:
    answers = state.get("answers", {})
    lines = []
    for i, (key, text) in enumerate(QUESTIONS, 1):
        value = answers.get(key, "")
        if isinstance(value, list):
            value = "; ".join(value)
        lines.append(f"{i}. {text} → {value or '(trống)'}")
    return "Hồ sơ của ngài:\n" + "\n".join(lines) + "\n" + CONFIRM_HINT


def new_state(now: float) -> dict:
    return {"status": "active", "index": 0, "answers": {}, "updated_at": now}


def is_open(state, now: float) -> bool:
    """Phiên đang hỏi hoặc đang chờ xác nhận, và chưa im lặng quá SESSION_IDLE_S."""
    return (isinstance(state, dict) and state.get("status") in ("active", "confirm")
            and now - float(state.get("updated_at", 0)) <= SESSION_IDLE_S)


def resume(state, now: float) -> tuple[dict, str]:
    """`@jobs phỏng vấn` / `@jobs tiếp tục`: mở lại phiên dở; chưa có hoặc đã xong thì bắt đầu mới."""
    if not isinstance(state, dict) or state.get("status") in (None, "done"):
        return new_state(now), prompt(0)
    state = dict(state, updated_at=now)
    if state.get("status") == "confirm" or int(state.get("index", 0)) >= N:
        state["status"] = "confirm"
        return state, summary(state)
    state["status"] = "active"
    return state, prompt(int(state["index"]))


def reopen(state, now: float) -> tuple[dict, str]:
    """`@jobs sửa hồ sơ`: về bước xác nhận với câu trả lời cũ."""
    if not isinstance(state, dict) or not state.get("answers"):
        return new_state(now), prompt(0)
    state = dict(state, status="confirm", index=N, updated_at=now)
    return state, summary(state)


def _advance(state: dict) -> tuple[dict, str, bool]:
    state["index"] = int(state.get("index", 0)) + 1
    if state.pop("editing", False) or state["index"] >= N:
        state.update(status="confirm", index=N)
        return state, summary(state), False
    return state, prompt(state["index"]), False


def answer(state, text: str, now: float) -> tuple[dict, str, bool]:
    state = dict(state or {})
    state["answers"] = dict(state.get("answers", {}))
    state["updated_at"] = now
    raw = str(text or "").strip()
    t = _norm(raw)
    if t in ("tạm dừng", "thoát"):
        state["status"] = "paused"
        return state, PAUSED, False
    m = _EDIT.match(t)
    if m:
        n = int(m.group(1))
        if not 1 <= n <= N:
            return state, f"Chỉ có câu 1 đến {N}.", False
        state.update(status="active", index=n - 1, editing=True)
        if QUESTIONS[n - 1][0] == "experience":
            state["answers"]["experience"] = []
        return state, prompt(n - 1), False
    if state.get("status") == "confirm":
        if t == "đúng":
            state["status"] = "done"
            return state, "", True
        return state, CONFIRM_HINT, False
    key = QUESTIONS[int(state.get("index", 0))][0]
    if key == "experience":
        if t == "hết":
            return _advance(state)
        if t == "bỏ qua":
            state["answers"]["experience"] = []
            return _advance(state)
        state["answers"]["experience"] = list(state["answers"].get("experience", [])) + [raw]
        return state, 'Đã ghi. Kể thêm kinh nghiệm khác, hoặc nói "hết".', False
    if t == "bỏ qua":
        state["answers"][key] = ""
        return _advance(state)
    if key == "english":
        if t not in ENGLISH_LEVELS:
            return state, "Chỉ nhận: " + " / ".join(ENGLISH_LEVELS) + ".", False
        raw = t
    state["answers"][key] = raw
    return _advance(state)
