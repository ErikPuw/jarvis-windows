"""
stream_tts.py — Streaming TTS Server (Port 8082)

Cổng phụ cung cấp true streaming TTS dùng edge-tts backend hoặc vieneu backend.
"""

import os
import logging
import asyncio
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

log = logging.getLogger("jarvis.stream_tts")
logging.getLogger("uvicorn.access").disabled = True

from engine.server.tts_server import generate_voice_bytes, generate_voice_bytes_stream
from engine.server.tts_manager import _resolve_tts_engine
from engine.server.vieneu_tts import (
    default_voice_name,
    is_ready,
    list_voices,
    reload_clones,
    stream_vieneu_wav,
    synthesize_vieneu_wav,
    warm_up,
)

app = FastAPI(
    title="Jarvis Stream TTS",
    description="Streaming TTS server dùng edge-tts hoặc vieneu.",
    version="1.0.0",
)

# Trước đây server này KHÔNG có SecurityFirewallMiddleware và mở CORS "*" —
# nghĩa là bất kỳ thiết bị nào chạm được port 8082 (LAN/Tailscale) đều bỏ qua
# hoàn toàn allowlist IP mà server chính (server.py) đang áp dụng. Áp dụng
# đúng cùng 2 lớp bảo vệ ở đây để không có "cửa sau" nào.
from engine.security.policy import parse_cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(parse_cors_origins(os.getenv("JARVIS_CORS_ORIGINS", ""))),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from engine.security.firewall import SecurityFirewallMiddleware
app.add_middleware(SecurityFirewallMiddleware)


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = None


def _warm_up_safely():
    try:
        warm_up()
    except Exception as exc:
        log.warning("VieNeu warm-up failed (sẽ nạp lại ở request đầu tiên): %s", exc)


@app.on_event("startup")
async def _warm_up_vieneu():
    # Không chặn khởi động: /tts/health vẫn trả lời ngay, request tới sớm sẽ chờ khóa nạp model.
    if _resolve_tts_engine() == "vieneu":
        app.state.warm_up_task = asyncio.create_task(asyncio.to_thread(_warm_up_safely))


@app.get("/tts/health")
async def health():
    engine = _resolve_tts_engine() or "edge"
    return JSONResponse({
        "status": "ok",
        "engine": engine,
        "voice": (
            os.getenv("VIENEU_VOICE_ID", "")
            if engine == "vieneu"
            else os.getenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural")
        ),
        "ready": is_ready() if engine == "vieneu" else True,
        "port": 8082,
    })


def _require_vieneu():
    if _resolve_tts_engine() != "vieneu":
        raise HTTPException(status_code=409, detail="VieNeu engine is not active")


@app.get("/tts/voices")
async def tts_voices():
    """Danh sách giọng preset + clone (chỉ cho VieNeu)."""
    _require_vieneu()
    voices = await asyncio.to_thread(list_voices)
    return {"engine": "vieneu", "default": await asyncio.to_thread(default_voice_name), "voices": voices}


@app.post("/tts/voices/reload")
async def tts_voices_reload():
    """Đăng ký mẫu clone vừa thêm vào model/voices/."""
    _require_vieneu()
    voices = await asyncio.to_thread(reload_clones)
    return {"engine": "vieneu", "default": await asyncio.to_thread(default_voice_name), "voices": voices}


async def _stream_vieneu(req: TTSRequest) -> StreamingResponse:
    """VieNeu v3: WAV stream (header + PCM16) từ infer_stream."""
    gen = stream_vieneu_wav(req.text, voice_id=req.voice)
    try:
        # Lấy chunk đầu trước khi trả response để lỗi sớm vẫn ra 503 (client retry).
        first = await gen.__anext__()
    except Exception as exc:
        log.warning("VieNeu synthesis failed: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"VieNeu synthesis failed: {exc}",
        ) from exc

    async def _body():
        try:
            yield first
            async for chunk in gen:
                yield chunk
        finally:
            await gen.aclose()

    return StreamingResponse(
        _body(),
        media_type="audio/wav",
        headers={
            "X-TTS-Engine": "vieneu",
            # Header HTTP chỉ nhận latin-1; tên giọng tiếng Việt ("Minh Triết") phải mã hóa.
            "X-TTS-Voice": quote(req.voice or os.getenv("VIENEU_VOICE_ID", "")),
        },
    )


async def _stream_edge(req: TTSRequest) -> StreamingResponse:
    """edge-tts: MP3 stream."""
    async def _gen():
        async for chunk in generate_voice_bytes_stream(req.text, voice=req.voice):
            yield chunk

    return StreamingResponse(
        _gen(),
        media_type="audio/mpeg",
        headers={
            "Transfer-Encoding": "chunked",
            "X-TTS-Engine": "edge-tts",
            "X-TTS-Voice": req.voice or os.getenv("TTS_LOCAL_MODEL", "vi-VN-NamMinhNeural"),
        }
    )


@app.post("/tts/stream")
async def tts_stream(req: TTSRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text field is required")

    engine = _resolve_tts_engine() or "edge"
    if engine == "vieneu":
        return await _stream_vieneu(req)
    return await _stream_edge(req)


@app.post("/tts/bytes")
async def tts_bytes(req: TTSRequest):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text field is required")

    engine = _resolve_tts_engine() or "edge"
    if engine == "vieneu":
        audio = await synthesize_vieneu_wav(req.text, voice_id=req.voice)
        media_type = "audio/wav"
    else:
        audio = await generate_voice_bytes(req.text, voice=req.voice)
        media_type = "audio/mpeg"

    if not audio:
        raise HTTPException(status_code=500, detail="TTS generation failed")

    return StreamingResponse(
        iter([audio]),
        media_type=media_type,
        headers={"Content-Length": str(len(audio))},
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8082, log_level="info")
