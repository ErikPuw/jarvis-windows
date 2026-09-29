import tempfile
from pathlib import Path

import engine.core.evolution as ev
from engine.core.evolution import _merge_rules

ev._vec = lambda text: None  # tests must not depend on the live embedder

HEAD = '---\nversion: "1.0.0"\n---\n\n# Self Evolution Style Rules\n'
OLD = HEAD + "- a\n- b\n- c\n- d\n"


def test_same_bullets_is_noop():
    assert _merge_rules(HEAD + "- d\n- c\n- b\n- a\n", OLD) is None


def test_partial_block_merges_instead_of_clobbering():
    out = _merge_rules(HEAD + "- new\n", OLD)
    assert out is not None and "- new" in out and "- a" in out and "- d" in out


def test_full_rewrite_replaces():
    new = HEAD + "- x\n- y\n- z\n"
    assert _merge_rules(new, OLD) == new


def test_reworded_rule_is_not_new():
    old = HEAD + "- Chỉ dùng xưng hô thưa ngài ở cuối đoạn hội thoại.\n"
    assert _merge_rules(HEAD + "- Chỉ sử dụng xưng hô thưa ngài ở cuối đoạn hội thoại.\n", old) is None


def test_evolution_log_has_no_dates_and_only_new_rules():
    saved = ev.EVOLUTION_LOG
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ev.EVOLUTION_LOG = Path(tmp) / "Evolution.md"
            ev._write_evolution_log(["- Chỉ dùng xưng hô thưa ngài ở cuối đoạn hội thoại."], ["- Luật hoàn toàn mới về emoji."])
            ev._write_evolution_log(["- Chỉ sử dụng xưng hô thưa ngài ở cuối đoạn hội thoại."], ["- Luật hoàn toàn mới về emoji.", "- Thêm luật khác nữa."])
            text = ev.EVOLUTION_LOG.read_text(encoding="utf-8")
    finally:
        ev.EVOLUTION_LOG = saved
    assert "## Routing" in text and "## Giao tiếp" in text
    assert text.count("thưa ngài") == 1 and text.count("emoji") == 1 and "Thêm luật khác" in text
    assert "20" not in text.split("-->")[1]  # no dates in the body


def _with_vecs(vecs, fn):
    ev._vec = lambda text: vecs.get(text)
    try:
        return fn()
    finally:
        ev._vec = lambda text: None


LESSON = "gọi agent điều khiển bằng control"
VECS = {
    "gọi agent điều khiển bằng control": [1.0, 0.0],
    "dùng control để mở windows update": [0.9, 0.1],
    "gửi email gọi điện nhắn tin agent_email": [0.2, 0.98],
}


def test_embedding_catches_paraphrase_with_no_shared_words():
    v = {"giữ giọng thân thiện": [1.0, 0.0], "duy trì tông vui vẻ": [0.99, 0.1]}
    assert _with_vecs(v, lambda: ev._similar("Giữ giọng thân thiện", "Duy trì tông vui vẻ"))


def test_embedding_low_cosine_or_missing_is_not_similar():
    v = {"luật về tin tức": [1.0, 0.0], "luật về giá cả": [0.6, 0.8]}
    assert not _with_vecs(v, lambda: ev._similar("luật về tin tức", "luật về giá cả"))
    assert not _with_vecs(v, lambda: ev._similar("luật về tin tức", "câu chưa có vector"))


def test_control_before_other_agent_is_rejected_even_if_supported():
    line = "- Tìm giá → `@control agent_search`."
    assert _with_vecs(VECS, lambda: ev._bad_rule(line, [LESSON], True)) == "@control chỉ dành cho agent_control"


def test_control_with_agent_control_is_allowed():
    line = "- Dùng `@control` để gọi `agent_control`."
    vecs = {**VECS, "dùng control để gọi agent_control": [1.0, 0.0]}
    assert _with_vecs(vecs, lambda: ev._bad_rule(line, [LESSON], True)) is None


def test_unknown_agent_is_rejected():
    assert "không tồn tại" in _with_vecs(VECS, lambda: ev._bad_rule("- Gọi `agent_phone` khi cần.", [LESSON], True))


def test_rule_without_supporting_lesson_is_rejected():
    line = "- Gửi email, gọi điện, nhắn tin → `agent_email`."
    assert _with_vecs(VECS, lambda: ev._bad_rule(line, [LESSON], True)) == "không có bài học nào làm căn cứ"


def test_supported_rule_passes_and_embedder_down_refuses():
    line = "- Dùng control để mở Windows Update."
    assert _with_vecs(VECS, lambda: ev._bad_rule(line, [LESSON], True)) is None
    assert "không kiểm chứng được" in ev._bad_rule(line, [LESSON], True)


def test_prepare_rules_keeps_only_grounded_bullets():
    new = HEAD + "- Dùng control để mở Windows Update.\n- Gửi email, gọi điện, nhắn tin → `agent_email`.\n"
    out = _with_vecs(VECS, lambda: ev._prepare_rules(new, HEAD, [LESSON], True))
    assert out is not None and "Windows Update" in out and "gọi điện" not in out


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
