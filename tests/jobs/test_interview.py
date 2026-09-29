"""Phỏng vấn: hỏi lần lượt, ngắt/tiếp tục, bỏ qua, sửa câu, hết giờ, xác nhận (spec mục 6)."""
from engine.jobs import interview as iv

T0 = 1_000_000.0


def _walk(state, replies, now=T0):
    out = None
    for r in replies:
        state, out, done = iv.answer(state, r, now)
    return state, out


def test_start_asks_first_question_with_prefix():
    state, reply = iv.resume({}, T0)
    assert state["status"] == "active" and state["index"] == 0
    assert reply.startswith("[Phỏng vấn 1/12]")


def test_answers_are_stored_and_advance():
    state, _ = iv.resume({}, T0)
    state, reply, done = iv.answer(state, "Nguyễn Văn A", T0)
    assert state["answers"]["full_name"] == "Nguyễn Văn A"
    assert state["index"] == 1 and reply.startswith("[Phỏng vấn 2/12]") and not done


def test_experience_loops_until_het():
    state, _ = iv.resume({}, T0)
    state, _ = _walk(state, ["A", "0901234567", "a@x.vn", "Hà Nội", "kế toán"])
    assert state["index"] == 5
    state, reply, _ = iv.answer(state, "Công ty X, kế toán, 2020-2023, sổ sách", T0)
    assert state["index"] == 5 and "hết" in reply
    state, reply, _ = iv.answer(state, "Công ty Y, kế toán trưởng, 2023-nay", T0)
    state, reply, _ = iv.answer(state, "hết", T0)
    assert state["answers"]["experience"] == ["Công ty X, kế toán, 2020-2023, sổ sách",
                                              "Công ty Y, kế toán trưởng, 2023-nay"]
    assert state["index"] == 6 and reply.startswith("[Phỏng vấn 7/12]")


def test_skip_and_english_validation():
    state = dict(iv.new_state(T0), index=9)
    state, reply, _ = iv.answer(state, "khá tốt", T0)
    assert state["index"] == 9 and reply.startswith("Chỉ nhận:")
    state, _, _ = iv.answer(state, "Giao tiếp", T0)
    assert state["answers"]["english"] == "giao tiếp" and state["index"] == 10
    state, _, _ = iv.answer(state, "bỏ qua", T0)
    assert state["answers"]["expectations"] == ""


def test_last_answer_goes_to_confirm_then_dung_finishes():
    state = dict(iv.new_state(T0), index=11)
    state, reply, done = iv.answer(state, "ca đêm", T0)
    assert state["status"] == "confirm" and "Hồ sơ của ngài" in reply and not done
    state, reply, done = iv.answer(state, "ừ", T0)
    assert state["status"] == "confirm" and not done
    state, reply, done = iv.answer(state, "Đúng.", T0)
    assert state["status"] == "done" and done


def test_edit_question_returns_to_confirm():
    state = dict(iv.new_state(T0), status="confirm", index=12, answers={"phone": "1"})
    state, reply, _ = iv.answer(state, "sửa câu 2", T0)
    assert state["index"] == 1 and reply.startswith("[Phỏng vấn 2/12]")
    state, reply, _ = iv.answer(state, "0909999999", T0)
    assert state["status"] == "confirm" and state["answers"]["phone"] == "0909999999"
    assert "editing" not in state
    _, reply, _ = iv.answer(state, "sửa câu 13", T0)
    assert reply == "Chỉ có câu 1 đến 12."


def test_pause_resume_and_idle_timeout():
    state, _ = iv.resume({}, T0)
    state, _, _ = iv.answer(state, "A", T0)
    paused, reply, _ = iv.answer(state, "tạm dừng", T0)
    assert paused["status"] == "paused" and "@jobs tiếp tục" in reply
    assert not iv.is_open(paused, T0)
    again, reply = iv.resume(paused, T0 + 10)
    assert again["status"] == "active" and reply.startswith("[Phỏng vấn 2/12]")
    assert iv.is_open(again, T0 + 10 + iv.SESSION_IDLE_S)
    assert not iv.is_open(again, T0 + 11 + iv.SESSION_IDLE_S)


def test_reopen_goes_to_confirm_with_old_answers():
    done = dict(iv.new_state(T0), status="done", index=12, answers={"full_name": "A"})
    state, reply = iv.reopen(done, T0)
    assert state["status"] == "confirm" and "A" in reply
    fresh, reply = iv.reopen({}, T0)
    assert fresh["status"] == "active" and reply.startswith("[Phỏng vấn 1/12]")
