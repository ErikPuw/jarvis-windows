"""Combines dispatch_tasks results into one answer. combine() never touches
ws — it only decides the text and whether another round is needed, so it is
safe to call on every round of the bounded loop in __init__.py. deliver() is
the single place that streams the final answer + TTS + stream_end to the
user, called exactly once per turn.

# ponytail: needs_more is decided from a trailing "[NEEDS_MORE]" marker on a
# non-streamed LLM call rather than true token-by-token streaming, because the
# marker can only be seen after the full response — upgrade to speculative
# streaming-with-rollback if the extra latency on multi-agent turns matters.
"""

import logging

log = logging.getLogger("jarvis.orchestrator.synthesizer")

_REPORT_CHARS = 2500  # prose per agent report; a 4B model must not drown in N long reports


def _split_tables(result) -> tuple[str, list[str]]:
    """(prose, tables): tables are contiguous runs of 2+ lines starting with `|`."""
    prose, tables, run = [], [], []
    for line in str(result or "").splitlines() + [""]:
        if line.strip().startswith("|"):
            run.append(line.rstrip())
            continue
        (tables.append("\n".join(run)) if len(run) >= 2 else prose.extend(run))
        run = []
        prose.append(line)
    return "\n".join(prose).strip(), tables


def _tables(result) -> list[str]:
    return _split_tables(result)[1]


def _digest(results: list[dict]) -> str:
    """What the synthesis LLM reads: one block per agent report. Prose is deduplicated
    across reports and capped; tables are kept verbatim (numbers must survive); a failed
    report is labelled so it can never be presented as done."""
    seen, blocks = set(), []
    for r in results:
        prose, tables = _split_tables(r.get("result"))
        lines = []
        for line in prose.splitlines():
            key = line.strip()
            if key and key in seen:
                continue
            seen.add(key)
            lines.append(line)
        body = "\n".join(lines).strip()
        if len(body) > _REPORT_CHARS:
            body = (body[:_REPORT_CHARS].rsplit("\n", 1)[0] or body[:_REPORT_CHARS]).rstrip() + "\n…(đã rút gọn)"
        failed = r.get("status") == "failed" or str(r.get("result") or "").startswith("Lỗi")
        head = f"Kết quả từ agent {r['agent']} (yêu cầu con: {r['query']})" + (" — THẤT BẠI" if failed else "") + ":"
        blocks.append("\n".join(p for p in (head, body, *tables) if p))
    return "\n\n".join(blocks)


def _restore_tables(text: str, results: list[dict]) -> str:
    """Small models (Qwen 4B) summarise a price table into prose despite the prompt.
    Any agent table not present verbatim in the answer is appended, so data is never lost."""
    squash = lambda t: "".join(t.split())
    flat = squash(text)
    missing = [t for r in results for t in _tables(r.get("result")) if squash(t) not in flat]
    if not missing:
        return text
    return text.rstrip() + "\n\n### 📋 Bảng dữ liệu gốc\n" + "\n\n".join(missing)


async def combine(user_text: str, results: list[dict]) -> tuple[str, bool]:
    """Return (text, needs_more). A single result is returned as-is (that
    agent already streamed its own answer, or will if this is the fast
    single-agent path) — no LLM call, no needs_more evaluation."""
    if len(results) == 1:
        return results[0]["result"], False

    from engine.prompts.results import build_synthesis_prompt
    from engine.server.llm_server import call_llm

    results_block = _digest(results)
    messages = [
        {"role": "system", "content": build_synthesis_prompt()},
        {"role": "user", "content": f"Yêu cầu gốc: {user_text}\n\n{results_block}"},
    ]
    response = await call_llm(messages=messages, temperature=0.3, thinking=False, stream=False)
    text = ""
    if response and hasattr(response, "choices") and response.choices:
        text = response.choices[0].message.content or ""

    text = _restore_tables(text, results)
    needs_more = text.rstrip().endswith("[NEEDS_MORE]")
    if needs_more:
        text = text.rsplit("[NEEDS_MORE]", 1)[0].rstrip()
    # Defensive: never let the raw marker leak to the user even if the LLM
    # emitted it somewhere other than the exact trailing position.
    text = text.replace("[NEEDS_MORE]", "").strip()
    if not text.strip():
        text = "Đã thực hiện xong."
    return text, needs_more


async def deliver(ws, text: str) -> str:
    """Stream the final text to the user exactly once, then send stream_end."""
    from server import safe_ws_send_json
    from engine.server.voice_streamer import VoiceStreamer
    from engine.server.text_streamer import stream_text_smoothly, clean_latex_math

    text = clean_latex_math(text)
    await stream_text_smoothly(ws, safe_ws_send_json, text, word_delay=0.02)
    streamer = VoiceStreamer(ws)
    streamer.start()
    await streamer.put(text)
    await streamer.stop()
    await safe_ws_send_json(ws, {"type": "stream_end"})
    return text
