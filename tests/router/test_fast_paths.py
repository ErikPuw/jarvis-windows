import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.router import fast_paths
from engine.router.fast_paths import VOICE_CONTROL, is_routing_complaint, resolve_mention


def test_supercontext_is_gone():
    """SuperContext gọi search_wiki_memories không còn tồn tại: code chết, đã gỡ (2026-09-25)."""
    assert not hasattr(fast_paths, "strip_prepared_context")
    server_src = (Path(__file__).resolve().parents[2] / "server.py").read_text(encoding="utf-8")
    assert "SuperContext" not in server_src and "PREPARED CONTEXT" not in server_src


def test_mention_resolves_registry_names_and_aliases():
    assert resolve_mention("@email xem thư mới") == ("email", "xem thư mới")
    assert resolve_mention("@agent_email xem") == ("email", "xem")
    assert resolve_mention("@mail xem") == ("email", "xem")
    assert resolve_mention("@calendar tuần này") == ("email", "tuần này")
    assert resolve_mention("@officecli sửa file") == ("office", "sửa file")
    assert resolve_mention("@control mở edge") == ("win_control", "mở edge")
    assert resolve_mention("@agent_control mở edge") == ("win_control", "mở edge")
    assert resolve_mention("@upscale ảnh") == ("image", "ảnh")
    assert resolve_mention("@media nhạc lofi") == ("media", "nhạc lofi")  # có trong registry
    assert resolve_mention("@email") == ("email", "")


def test_unknown_mention_is_stripped_and_not_an_agent():
    assert resolve_mention("@xyz mở notepad") == (None, "mở notepad")
    assert resolve_mention("mở notepad") == (None, "mở notepad")


def test_voice_control_and_complaint_regexes_unchanged():
    assert VOICE_CONTROL.match("jarvis, điều khiển máy")
    assert VOICE_CONTROL.match("thu nhỏ cửa sổ")
    assert not VOICE_CONTROL.match("mở email")
    assert is_routing_complaint("sao lại gọi agent vậy")
    assert is_routing_complaint("chứ tôi đang hỏi bạn mà sao lại chạy")
    assert not is_routing_complaint("kiểm tra bảo mật")


if __name__ == "__main__":
    for f in list(globals().values()):
        if callable(f) and getattr(f, "__name__", "").startswith("test_"):
            f()
    print("OK")
