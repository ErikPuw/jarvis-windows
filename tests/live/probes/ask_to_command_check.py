"""Does the classifier fail because it receives a QUESTION ("Ngài có muốn tôi X không?") instead of a COMMAND ("X")?
Same asks (taken verbatim from prompt_ablation output), classified raw vs with the offer wrapper stripped by code.
Run: PYTHONIOENCODING=utf-8 python .../ask_to_command_check.py [--gemma]
"""
import asyncio, os, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
if "--gemma" in sys.argv:
    os.environ["CHANG_MODEL"] = "true"

_WRAP = re.compile(
    r"^(?:thưa ngài,?\s*)?(?:ngài\s+)?(?:có\s+)?(?:muốn|cần|cho phép)\s+tôi\s+|^(?:tôi\s+)?(?:có\s+)?nên\s+|^cho\s+(?:tôi\s+)?phép\s+(?:tôi\s+)?",
    re.I)
_TAIL = re.compile(r"\s*(?:cho ngài)?\s*(?:ngay)?\s*(?:không|nhé|chứ|nha|được không)?\s*(?:ạ|thưa ngài)?\s*\?\s*$", re.I)


def ask_to_command(ask: str) -> str:
    """'Ngài có muốn tôi xem hộp thư Outlook của ngài không ạ?' -> 'xem hộp thư Outlook của ngài'"""
    return _TAIL.sub("", _WRAP.sub("", ask.strip())).strip(" ,.")


ASKS = [  # (ask as the model wrote it, expected agents)
    ("Ngài có muốn tôi xem hộp thư Outlook của ngài không ạ?", {"email"}),
    ("Ngài có muốn tôi xem email trong Outlook để kiểm tra tình trạng và đề xuất cách giải quyết không?", {"email"}),
    ("Ngài có muốn tôi tra tin tức chung mới nhất cho ngài không?", {"search"}),
    ("Ngài có muốn tôi kiểm tra lịch Outlook của ngài cho tuần này không ạ?", {"email"}),
    ("Tôi có nên mở Notepad cho ngài không?", {"desktop"}),
    ("Ngài có muốn tôi tra giá vàng hôm nay không?", {"search"}),
    ("Cho tôi phép tra giá vàng nhé?", {"search"}),
    ("Ngài có muốn tôi mở ứng dụng Notepad ngay bây giờ để ngài gõ tiếp không?", {"desktop"}),
    ("Ngài có muốn tôi kiểm tra và lọc các email khẩn cấp ngay bây giờ không?", {"email"}),
    ("Ngài có muốn tôi tra cứu tin tức thời sự mới nhất hôm nay không?", {"search"}),
]


async def main():
    from engine.orchestrator.classifier import classify_tasks
    from engine.server.llm_server import active_model_key
    print("profile:", active_model_key())
    ok_raw = ok_cmd = 0
    for ask, exp in ASKS:
        cmd = ask_to_command(ask)
        raw = [(t["agent"], t["query"]) for t in await classify_tasks(ask, conversation_history=[])]
        clean = [(t["agent"], t["query"]) for t in await classify_tasks(cmd, conversation_history=[])]
        r, c = bool({a for a, _ in raw} & exp), bool({a for a, _ in clean} & exp)
        ok_raw += r; ok_cmd += c
        print(f"{'OK ' if r else 'BAD'} raw  {ask[:70]!r:74} -> {raw}")
        print(f"{'OK ' if c else 'BAD'} cmd  {cmd[:70]!r:74} -> {clean}")
    print(f"\nraw question: {ok_raw}/{len(ASKS)}   stripped command: {ok_cmd}/{len(ASKS)}")

if __name__ == "__main__":
    assert ask_to_command("Ngài có muốn tôi xem hộp thư Outlook của ngài không ạ?") == "xem hộp thư Outlook của ngài"
    assert ask_to_command("Tôi có nên mở Notepad cho ngài không?") == "mở Notepad"
    assert ask_to_command("Cho tôi phép tra giá vàng nhé?") == "tra giá vàng"
    asyncio.run(main())
