"""Router: decide (RouteDecision) → dispatch. Điểm vào duy nhất cho WebUI và Telegram."""
import logging

from engine.router.decide import decide
from engine.router import dispatch as _dispatch_module  # giữ engine.router.dispatch là submodule (test_dispatch.py cần DP._run_orchestrator/_chat/run_replay)
from engine.router.types import RouteDecision, TurnContext

log = logging.getLogger("jarvis.router")

__all__ = ["handle_turn", "TurnContext", "RouteDecision"]


async def handle_turn(text: str, ctx: TurnContext) -> str:
    # Tệp nén: trước gate, để gate/bảng chọn thấy tệp thật bên trong (2026-09-28).
    try:
        from engine.router.archive import unpack_archive
        archive_msg = await unpack_archive(ctx)
    except Exception as exc:
        log.warning("[ROUTER] archive unpack failed: %s", exc)
        archive_msg = None
    if archive_msg:
        return await _dispatch_module._say(ctx, archive_msg)
    try:
        async with ctx.flow_tracker.step("Định tuyến ngữ nghĩa...") as step:
            d = await decide(text, ctx)
            step.label = f"Định tuyến → {d.kind}"
    except Exception as exc:
        log.warning("[ROUTER] decide failed, fallback to general chat: %s", exc)
        d = RouteDecision("general", text, "fallback")
    log.info("[ROUTER] decision kind=%s source=%s agent=%s", d.kind, d.source, d.agent)
    try:
        return await _dispatch_module.dispatch(d, text, ctx)
    except Exception as exc:
        # A chat kind's own exceptions propagate — chat_stream already has its own
        # fallbacks (spec §5). Only non-chat kinds (orchestrator/agent/replay/
        # attachment_clarify) get the old server.generate_response_stream behaviour
        # of falling back to a normal chat answer when the route itself blows up.
        if d.kind in ("general", "general_knowledge"):
            raise
        log.warning("[ROUTER] dispatch failed for kind=%s, fallback to general chat: %s", d.kind, exc)
        ctx.action_declined = True
        return await _dispatch_module._chat("general", text, ctx)
