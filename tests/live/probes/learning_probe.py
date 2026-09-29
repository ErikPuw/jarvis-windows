"""Live probe: Đo learning tự phản tư (propose + critique) trên 20 hội thoại mẫu.
Yêu cầu spec 2026-09-25 §4:
- 10 hội thoại NÊN học: đạt >= 7/10
- 10 hội thoại KHÔNG NÊN học: 0/10 lưu nhầm (100% sạch)
Run: python -X utf8 tests/live/probes/learning_probe.py
Requires: llama-server 127.0.0.1:8080 (read-only / test engine).
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from engine.core.learning import LearningEngine

SHOULD_LEARN_CASES = [
    ("từ giờ gọi tôi là Erik nhé", "Vâng thưa ngài, tôi sẽ gọi ngài là Erik."),
    ("tôi không thích bạn xưng em, hãy xưng tôi", "Dạ tôi đã hiểu, tôi sẽ xưng tôi với ngài."),
    ("dự án của tôi viết bằng Python 3.13 và FastAPI", "Tôi đã ghi nhận thông tin dự án của ngài."),
    ("khi tóm tắt tin tức nhớ chừa nguồn lại giúp tôi", "Vâng, tôi sẽ luôn trích dẫn nguồn khi tóm tắt tin tức."),
    ("tôi làm việc ở múi giờ GMT+7 TP.HCM", "Tôi đã ghi nhận múi giờ làm việc của ngài."),
    ("trả lời ngắn gọn thôi, đừng dài dòng giải thích nhiều", "Vâng thưa ngài, tôi sẽ trả lời cô đọng và đi thẳng vào vấn đề."),
    ("tôi hay nghe nhạc lofi lúc làm việc", "Tôi đã ghi nhớ sở thích nghe nhạc lofi của ngài."),
    ("tôi là kỹ sư AI làm việc ở Jarvis", "Rất vinh hạnh được hỗ trợ kỹ sư AI của dự án."),
    ("sau này bạn thêm emoji vào câu trả lời cho sinh động nhé", "Dạ vâng, tôi sẽ thêm emoji phù hợp vào câu trả lời."),
    ("nhớ rằng tôi bị dị ứng hải sản", "Tôi đã ghi nhận thông tin ngài bị dị ứng hải sản."),
]

SHOULD_NOT_LEARN_CASES = [
    ("tôi lười mở notepad quá", "Ngài có muốn tôi mở Notepad giúp ngài không?"),
    ("hôm nay tôi mệt mỏi và buồn ngủ quá", "Ngài nên nghỉ ngơi một chút để hồi phục sức khỏe nhé."),
    ("giá vàng SJC hôm nay là 85 triệu đồng một lượng", "Dạ vâng, đó là giá cập nhật từ thị trường hôm nay."),
    ("thời tiết Hà Nội đang mưa 25 độ C", "Ngài nhớ mang theo ô khi ra ngoài nhé."),
    ("chào bạn, buổi sáng tốt lành", "Chào ngài! Chúc ngài một ngày làm việc hiệu quả."),
    ("cảm ơn bạn nhiều nhé, tạm biệt", "Không có chi thưa ngài, hẹn gặp lại ngài."),
    ("mở giúp tôi ứng dụng calculator", "Tôi đang mở máy tính cho ngài."),
    ("kiểm tra email xem có thư mới không", "Hộp thư của ngài hiện không có email mới."),
    ("bây giờ là mấy giờ rồi nhỉ", "Bây giờ là 14:00 thưa ngài."),
    ("đang bận tay một chút, lát nữa nói tiếp nhé", "Vâng thưa ngài, tôi luôn ở đây khi ngài cần."),
]


async def run_probe():
    engine = LearningEngine()
    print("=" * 60)
    print("BẮT ĐẦU CHẠY LEARNING PROBE (20 ca thử nghiệm)")
    print("=" * 60)

    # Dọn sạch các dữ liệu test mẫu trước khi đo để kiểm tra khả năng học mới
    conn = engine._get_learning_db()
    test_keywords = ["Erik", "xưng", "FastAPI", "tin tức", "múi giờ", "ngắn gọn", "lofi", "kỹ sư AI", "emoji", "hải sản"]
    for kw in test_keywords:
        conn.execute("DELETE FROM learnings WHERE content LIKE ?", (f"%{kw}%",))
    conn.commit()
    conn.close()

    # 1. Đo SHOULD_LEARN
    should_learn_score = 0
    print("\n--- 1. Kiểm tra 10 ca NÊN học (Mục tiêu >= 7/10) ---")
    for i, (u, a) in enumerate(SHOULD_LEARN_CASES, 1):
        res = await engine.process_conversation_learning(u, a)
        items = res.get("items", [])
        stored = res.get("stored", 0)
        has_learned = len(items) > 0 or stored > 0
        if has_learned:
            should_learn_score += 1
            learned_repr = items[0].get("content") if items else "stored"
            print(f"[{i:02d}] PASS: '{u}' -> Đã học: '{learned_repr}'")
        else:
            print(f"[{i:02d}] MISS: '{u}' -> Bỏ qua (không học)")

    # 2. Đo SHOULD_NOT_LEARN
    should_not_learn_clean = 0
    print("\n--- 2. Kiểm tra 10 ca KHÔNG NÊN học (Mục tiêu 0/10 lưu nhầm, 100% sạch) ---")
    for i, (u, a) in enumerate(SHOULD_NOT_LEARN_CASES, 1):
        res = await engine.process_conversation_learning(u, a)
        items = res.get("items", [])
        stored = res.get("stored", 0)
        has_learned = len(items) > 0 or stored > 0
        if not has_learned:
            should_not_learn_clean += 1
            print(f"[{i:02d}] PASS (SẠCH): '{u}' -> Đúng đắn bỏ qua")
        else:
            learned_repr = items[0].get("content") if items else "stored"
            print(f"[{i:02d}] FAIL (LƯU NHẦM): '{u}' -> Lưu nhầm: '{learned_repr}'")

    print("\n" + "=" * 60)
    print(f"KẾT QUẢ LEARNING PROBE:")
    print(f"- Nên học: {should_learn_score}/10 (Yêu cầu >= 7/10)")
    print(f"- Không nên học (sạch): {should_not_learn_clean}/10 (Yêu cầu 10/10, tức 0/10 lưu nhầm)")
    print("=" * 60)

    # Dọn dẹp sau khi đo xong
    conn = engine._get_learning_db()
    for kw in test_keywords:
        conn.execute("DELETE FROM learnings WHERE content LIKE ?", (f"%{kw}%",))
    conn.commit()
    conn.close()

    passed = should_learn_score >= 7 and should_not_learn_clean == 10
    if passed:
        print("ĐÁNH GIÁ: ĐẠT YÊU CẦU SPEC.")
    else:
        print("ĐÁNH GIÁ: CHƯA ĐẠT.")
    return passed


if __name__ == "__main__":
    success = asyncio.run(run_probe())
    sys.exit(0 if success else 1)
