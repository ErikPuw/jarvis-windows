"""M4: the 'API key not configured' websocket branch replies without running
handle_turn, so it never goes through dispatch()/chat_stream's own reset of
ws.pending_ask_user. Left alone, a stale value from an earlier turn rides
along into the save_message(..., ask_user=...) call for this turn's fallback
reply. No websocket test harness exists for voice_handler (it's ~600 lines of
inline asyncio loop, not a unit under test elsewhere), so this pins the fix at
the source level: the reset must happen before the branch's response_text is set.
"""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SERVER_SRC = (Path(__file__).resolve().parent.parent / "server.py").read_text(encoding="utf-8")


def test_api_key_not_configured_branch_resets_pending_ask_user():
    m = re.search(
        r'if not openai_client:\s*\n((?:.*\n)*?)\s*response_text = "API key not configured\."',
        SERVER_SRC,
    )
    assert m, "branch not found in server.py"
    branch_body = m.group(1)
    assert re.search(r'pending_ask_user\s*=\s*""', branch_body), (
        "ws.pending_ask_user must be reset to \"\" before the fallback response_text "
        "is set, otherwise a stale value from an earlier turn leaks into save_message()"
    )


if __name__ == "__main__":
    test_api_key_not_configured_branch_resets_pending_ask_user()
    print("OK")
