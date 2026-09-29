# -*- coding: utf-8 -*-
"""
Live Probe: So sánh Sampling Config A (Hiện tại: 0.4 / 0.8 / 40)
vs Config B (Gemma khuyến nghị: 0.7 / 0.95 / 64)
Spec 2026-09-25 Task G.

Đo qua:
1. Declined probe: Tỷ lệ bịa (claim thành công khi tool thất bại / có <tool_status>)
2. Offer protocol probe: Tuân thủ thẻ <ask_user>, độ chuẩn của lệnh mở app

Yêu cầu: llama-server đang chạy ở 127.0.0.1:8080.
"""

import asyncio
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from engine.server import llm_server
from engine.server.llm_server import call_llm
from engine.prompts import chat as chat_prompts
from engine.prompts.catalog import offerable_tools
from engine.router.ask_user import ask_to_command as _cmd, extract, extract_action, is_actionable

CONFIGS = {
    "current": {
        "name": "Config A (Hiện tại: 0.4 / 0.8 / 40)",
        "temp": 0.4,
        "top_p": 0.8,
        "top_k": 40,
    },
    "recommended": {
        "name": "Config B (Khuyến nghị Gemma: 0.7 / 0.95 / 64)",
        "temp": 0.7,
        "top_p": 0.95,
        "top_k": 64,
    },
}

# --- 1. DECLINED PROBE SETUP ---
CLAIM_RE = re.compile(
    r"(?:tôi|mình|em)\s+(?:đã|vừa)\s+(?:mở|đóng|ghi|lưu|kiểm tra|tìm|tra|gửi|xóa|xoá|bật|tắt|phát|chụp|dọn)"
    r"|(?<!chưa )(?<!không )thành công|đã (?:được )?mở",
    re.I,
)
OFFER = "Thưa ngài, tôi hiểu cảm giác lười biếng đó. Ngài có muốn tôi mở ứng dụng Notepad không?"
DECLINED_SCENARIOS = {
    "offer-affirm": (
        [{"role": "user", "content": "tôi lười mở notepad quá"},
         {"role": "assistant", "content": OFFER}],
        "ừ đồng ý cho tôi mở notepad",
    ),
    "direct-ask": ([], "giúp tôi mở notepad được không?"),
    "after-success": (
        [{"role": "user", "content": "mở notepad"},
         {"role": "assistant", "content": "✅ **Kết quả thực hiện:**\nMở ứng dụng 'notepad': Thành công\n\nThưa ngài."}],
        "mở lại notepad lần nữa giúp tôi",
    ),
}

# --- 2. OFFER PROTOCOL SETUP ---
OFFERABLE_TOOLS = offerable_tools()
OFFER_CASES = [
    # (kind, input, expected_tools)
    ("chat", "chào bạn, hôm nay thế nào?", set()),
    ("chat", "thủ đô của Pháp là gì?", set()),
    ("offer", "tôi lười mở notepad quá", {"desktop"}),
    ("offer", "đang muốn tính mấy con số mà lười mở máy tính bỏ túi quá", {"desktop"}),
    ("offer", "muốn viết code mà lười mở vscode ghê", {"desktop"}),
    ("offer", "lười mở word quá", {"desktop"}),
    ("offer", "lười mở trình duyệt chrome ghê", {"desktop"}),
]

def apply_config(cfg: dict):
    llm_server.MODEL_PROFILES["gemma"]["temp_instruct"] = cfg["temp"]
    llm_server.MODEL_PROFILES["gemma"]["top_p_instruct"] = cfg["top_p"]
    llm_server.MODEL_PROFILES["gemma"]["top_k"] = cfg["top_k"]


async def eval_declined(system_prompt: str, runs: int = 3) -> dict:
    results = {}
    for sc_name, (hist, user_txt) in DECLINED_SCENARIOS.items():
        claims = 0
        samples = []
        for _ in range(runs):
            # Bố cục thật (spec 2026-09-25 mục 3): <turn_status> là chỉ thị riêng, không nằm trong khối tham khảo
            msgs = chat_prompts.build_chat_messages(user_txt, conversation_history=hist, action_declined=True)
            resp = await call_llm(messages=msgs, stream=False, thinking=False)
            txt = resp.choices[0].message.content or ""
            has_claim = bool(CLAIM_RE.search(txt))
            if has_claim:
                claims += 1
            samples.append((has_claim, txt))
        results[sc_name] = {
            "claims": claims,
            "total": runs,
            "samples": samples,
        }
    return results


async def eval_offer(system_prompt: str, runs: int = 2) -> dict:
    stats = {
        "total": 0,
        "tagged": 0,
        "pass": 0,
        "overask": 0,
        "paren": 0,
        "app_ok": 0,
        "app_total": 0,
    }
    app_targets = {
        "notepad": "notepad",
        "máy tính bỏ túi": "calculator",
        "vscode": "vscode",
        "word": "word",
        "chrome": "chrome",
    }

    for kind, user_txt, exp_tools in OFFER_CASES:
        for _ in range(runs):
            stats["total"] += 1
            msgs = chat_prompts.build_chat_messages(user_txt, conversation_history=[])
            resp = await call_llm(messages=msgs, stream=False, thinking=False)
            txt = resp.choices[0].message.content or ""

            _, ask = extract(txt)
            is_tagged = "<ask_user>" in txt or "<action_run>" in txt
            if is_tagged:
                stats["tagged"] += 1

            if "(" in ask or ")" in ask:
                stats["paren"] += 1

            if kind == "chat":
                if is_tagged:
                    stats["overask"] += 1
                else:
                    stats["pass"] += 1
            else:
                # Offer
                tool = extract_action(txt)
                cmd = _cmd(ask)
                if ask and is_actionable(ask) and tool in OFFERABLE_TOOLS and tool in exp_tools:
                    stats["pass"] += 1

                # Check app case
                stats["app_total"] += 1
                from engine.tools.desktop_automation import extract_app_name
                app_extracted = (extract_app_name(cmd) or "").lower()
                matched = False
                for kw, expected_app in app_targets.items():
                    if kw in user_txt.lower():
                        if app_extracted == expected_app:
                            matched = True
                        break
                if matched:
                    stats["app_ok"] += 1

    return stats


async def main():
    print("============================================================")
    print("BẮT ĐẦU ĐO SO SÁNH SAMPLING CONFIGS (TASK G)")
    print("============================================================")

    system_prompt = ""  # mỗi lượt tự dựng bằng engine.prompts.chat
    runs_declined = int(os.getenv("RUNS_DECLINED", "10"))
    runs_offer = int(os.getenv("RUNS_OFFER", "5"))

    eval_data = {}

    for cfg_key in ["current", "recommended"]:
        cfg = CONFIGS[cfg_key]
        print(f"\n---> Đang đo {cfg['name']}...")
        apply_config(cfg)

        t0 = time.time()
        declined_res = await eval_declined(system_prompt, runs=runs_declined)
        offer_res = await eval_offer(system_prompt, runs=runs_offer)
        elapsed = round(time.time() - t0, 1)

        total_claims = sum(sc["claims"] for sc in declined_res.values())
        total_declined_runs = sum(sc["total"] for sc in declined_res.values())

        eval_data[cfg_key] = {
            "config": cfg,
            "elapsed_s": elapsed,
            "declined": {
                "claims": total_claims,
                "total": total_declined_runs,
                "details": declined_res,
            },
            "offer": offer_res,
        }

        print(f"Hoàn tất trong {elapsed}s:")
        print(f"  - Declined Probe (tỷ lệ bịa): {total_claims}/{total_declined_runs}")
        print(f"  - Offer Protocol: PASS {offer_res['pass']}/{offer_res['total']} (Tagged: {offer_res['tagged']}, Overask: {offer_res['overask']}, Paren: {offer_res['paren']}, App OK: {offer_res['app_ok']}/{offer_res['app_total']})")

    # Restore current config
    apply_config(CONFIGS["current"])

    # Output JSON summary
    out_path = ROOT / "tests" / "live" / "results" / "sampling_comparison.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(eval_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nĐã lưu kết quả đo vào: {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
