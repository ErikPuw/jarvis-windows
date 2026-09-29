"""Stream câu trả lời chat: LLM → lọc LaTeX/cue → text_chunk + VoiceStreamer (TTS) → stream_end."""
import logging
import time

log = logging.getLogger("jarvis.router.chat_stream")


async def stream_chat(messages: list[dict], text: str, ctx) -> str:
    flow_tracker = ctx.flow_tracker
    ws = ctx.ws
    safe_ws_send_json = ctx.send_json

    from engine.server.llm_server import call_llm
    streamer = None
    try:
        async with flow_tracker.step("Đang gọi LLM..."):
            # Gọi LLM với stream=True (luồng chat thường general không sử dụng tools)
            stream = await call_llm(
                messages=messages,
                stream=True,
                thinking=False
            )

            from engine.server.text_streamer import SentenceSplitter, StreamCueFilter, StreamLatexFilter
            from engine.router.ask_user import StreamTagFilter, extract, extract_action
            latex_filter = StreamLatexFilter()
            cue_filter = StreamCueFilter()  # ẩn [cười]... khỏi chữ hiển thị, TTS vẫn nhận đủ
            tag_filter = StreamTagFilter()  # ẩn <ask_user>...</ask_user> khỏi chữ hiển thị
            full_content = ""
            splitter = SentenceSplitter()

            from engine.server.voice_streamer import VoiceStreamer
            streamer = VoiceStreamer(ws)
            worker_task = streamer.start()
            if ctx.background_tasks is not None:
                ctx.background_tasks.add(worker_task)
                worker_task.add_done_callback(ctx.background_tasks.discard)

            async for chunk in stream:
                if getattr(ws, "cancel_requested", False):
                    log.info("Response generation cancelled by client request")
                    break
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content or ""
                if delta:
                    full_content += delta

                    # Lọc LaTeX thời gian thực thông qua bộ lọc tích lũy
                    clean_delta = tag_filter.filter_chunk(cue_filter.filter_chunk(latex_filter.filter_chunk(delta)))
                    if clean_delta:
                        await safe_ws_send_json(ws, {"type": "text_chunk", "text": clean_delta})

                    cancelled_mid_split = False
                    for sentence in splitter.push(delta):
                        if getattr(ws, "cancel_requested", False):
                            cancelled_mid_split = True
                            break
                        await streamer.put(sentence)
                    if cancelled_mid_split:
                        break

            # Flush nốt phần text LaTeX còn sót trong buffer nếu có
            rest = tag_filter.filter_chunk(cue_filter.filter_chunk(latex_filter.flush()) + cue_filter.flush()) + tag_filter.flush()
            if rest:
                await safe_ws_send_json(ws, {"type": "text_chunk", "text": rest})

            if getattr(ws, "cancel_requested", False):
                await streamer.stop(clear_queue=True)

            else:
                for sentence in splitter.flush():
                    await streamer.put(sentence)

            if not full_content.strip() and not getattr(ws, "cancel_requested", False):
                log.warning("LLM returned empty response")
                await streamer.stop(clear_queue=True)
                fallback = "Yes, sir?"
                setattr(ws, "pending_ask_user", "")
                setattr(ws, "pending_action_run", "")
                await safe_ws_send_json(ws, {"type": "text_chunk", "text": fallback})
                await safe_ws_send_json(ws, {"type": "stream_end"})
                return fallback

        async with flow_tracker.step("TTS & stream_end"):
            tts_finalize_started = time.monotonic()
            log.info(
                "Response finalization started: transport=websocket tts_disabled=%s cancel_requested=%s",
                getattr(ws, "tts_disabled", False),
                getattr(ws, "cancel_requested", False),
            )
            await streamer.stop()  # Chờ toàn bộ tiến trình TTS chạy xong trước khi đóng luồng
            log.info(
                "Response finalization: VoiceStreamer.stop elapsed=%.3fs",
                time.monotonic() - tts_finalize_started,
            )

        if not getattr(ws, "cancel_requested", False):
            await safe_ws_send_json(ws, {"type": "stream_end"})

        clean, ask = extract(full_content)
        setattr(ctx.ws, "pending_ask_user", ask)
        setattr(ctx.ws, "pending_action_run", extract_action(full_content) if ask else "")
        if ask:
            # Dòng "JARVIS:" trong log là bản sạch, không thấy thẻ: ghi lời đề nghị + tên tool gốc (kể cả tên bịa).
            from engine.router.ask_user import ACTION_RE
            m = ACTION_RE.search(full_content)
            raw_tool = m.group(1).strip().strip("`'\" ") if m else ""
            log.info("[OFFER] ask=%r action_run=%r valid=%s", ask, raw_tool, bool(getattr(ctx.ws, "pending_action_run", "")))

        # Bắn hook ON_RESPONSE_GENERATE
        try:
            from engine.tools.load_hook import HookRegistry, HOOKS
            await HookRegistry.get_instance().fire_async(
                HOOKS.ON_RESPONSE_GENERATE,
                user_text=text,
                response_text=clean
            )
        except Exception as e:
            log.warning(f"Hook fire ON_RESPONSE_GENERATE failed: {e}")

        from engine.server.text_streamer import clean_latex_math, strip_voice_cues
        return strip_voice_cues(clean_latex_math(clean))

    except Exception as e:
        log.error(f"LLM streaming error: {e}")
        # Stream LLM đứt giữa chừng: phải dừng VoiceStreamer, nếu không 2 worker TTS
        # treo mãi ở queue.get() và UI kẹt ở trạng thái "speaking" (status idle không bao giờ gửi).
        if streamer is not None:
            try:
                await streamer.stop(clear_queue=True)
            except Exception as stop_err:
                log.warning(f"VoiceStreamer stop after LLM error failed: {stop_err}")
        fallback = "Xin lỗi tôi đang gặp lỗi kết nối với hệ thống ngôn ngữ LLM."
        setattr(ws, "pending_ask_user", "")
        setattr(ws, "pending_action_run", "")
        await safe_ws_send_json(ws, {"type": "text_chunk", "text": fallback})
        await safe_ws_send_json(ws, {"type": "stream_end"})
        return fallback
