"""Live (read-only): planner vòng 1 của chế độ mục tiêu trên model đang nạp (spec 2026-09-26 mục 9).
20 mục tiêu held-out (không có trong prompt nào) × k lần; không gọi web.
Đạt: ≥ 90% số lần chạy có ≥ 1 bước hợp lệ.
Run: PYTHONIOENCODING=utf-8 python tests/live/probes/plan_goal_probe.py [k]
"""
import asyncio
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from engine.plans import planner  # noqa: E402

GOALS = [
    "tôi thèm ăn gì đó mà không biết ăn gì",
    "cuối tuần này nên đi đâu chơi gần Hà Nội",
    "tôi muốn mua laptop tầm 20 triệu để lập trình, nên chọn loại nào",
    "tối nay nên xem phim gì",
    "trời thế này có nên đi chạy bộ buổi chiều không",
    "gợi ý quà sinh nhật cho mẹ tôi",
    "tôi hay mất ngủ, nên làm gì",
    "nên học tiếng Anh theo cách nào hiệu quả",
    "tuần sau đi Đà Lạt cần chuẩn bị gì",
    "hôm nay nên mặc gì ra ngoài",
    "tôi muốn nấu món gì đó cho bữa tối nhanh gọn",
    "có nên mua vàng lúc này không",
    "gợi ý sách hay về quản lý thời gian",
    "tôi muốn tập thể dục tại nhà, bắt đầu thế nào",
    "nên đi du lịch Đà Nẵng hay Nha Trang dịp lễ",
    "mua điện thoại tầm trung nào đáng tiền",
    "cuối tuần mưa thì làm gì cho đỡ chán",
    "gợi ý quán cà phê yên tĩnh để làm việc",
    "tôi muốn nuôi một con thú cưng dễ chăm",
    "trưa nay ăn gì cho nhẹ bụng",
]


async def main(k: int) -> float:
    ok = total = 0
    targets: Counter = Counter()
    rows = []
    for goal in GOALS:
        for _ in range(k):
            t0 = time.time()
            steps = await planner.next_steps(goal, "", [])
            total += 1
            ok += bool(steps)
            targets.update(s["target"] for s in steps)
            rows.append({"goal": goal, "steps": steps, "seconds": round(time.time() - t0, 2)})
    rate = ok / total
    print(f"valid runs: {ok}/{total} = {rate:.0%} (cần ≥ 90%)")
    print("targets:", dict(targets))
    out = ROOT / "tests" / "live" / "results" / f"plan_goal_probe_{time.strftime('%Y%m%d_%H%M')}.json"
    out.write_text(json.dumps({"rate": rate, "targets": targets, "rows": rows}, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print("saved", out)
    return rate


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    sys.exit(0 if asyncio.run(main(runs)) >= 0.9 else 1)
