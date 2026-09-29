import logging
import asyncio
import os
import subprocess
from typing import Any

log = logging.getLogger("jarvis.agent_goose")

GOOSE_PATH = r"C:\Users\erikpuw\AppData\Local\Programs\Goose-windows\Goose.exe"

async def safe_ws_send_json(ws, data: dict) -> bool:
    if not ws:
        return False
    try:
        await ws.send_json(data)
        return True
    except Exception:
        return False

def launch_goose_gui() -> bool:
    """Khởi chạy ứng dụng Goose Desktop độc lập (detached process)."""
    if os.path.exists(GOOSE_PATH):
        try:
            # 0x00000008 = DETACHED_PROCESS trên Windows
            subprocess.Popen([GOOSE_PATH], creationflags=0x00000008, close_fds=True)
            log.info("Goose Desktop GUI launched successfully.")
            return True
        except Exception as e:
            log.error(f"Failed to launch Goose Desktop GUI: {e}")
            return False
    return False

async def run_goose_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs
) -> str:
    if not flow_tracker:
        class NoOpFlowTracker:
            def step(self, label):
                class NoOpStep:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStep()
            async def track(self, *args, **kwargs): pass
        flow_tracker = NoOpFlowTracker()

    log.info(f"Agent Goose activated for query: '{user_text}'")

    # Gửi status cho frontend
    await safe_ws_send_json(ws, {"type": "status", "state": "working"})

    await safe_ws_send_json(ws, {
        "type": "text_chunk",
        "text": "🤖 **[Goose Agent]** Đang tiến hành khởi chạy ứng dụng **Goose Desktop** độc lập cho bạn...\n\n"
    })

    # Chạy ứng dụng Goose
    success = launch_goose_gui()

    if success:
        status_msg = "✅ **[Goose Agent]** Đã mở ứng dụng Goose Desktop thành công, thưa Ngài."
    else:
        status_msg = "❌ **[Goose Agent]** Không thể khởi chạy Goose Desktop. Vui lòng kiểm tra lại đường dẫn `C:\\Users\\erikpuw\\AppData\\Local\\Programs\\Goose-windows\\Goose.exe`."

    await safe_ws_send_json(ws, {
        "type": "text_chunk",
        "text": status_msg
    })
    
    # Kết thúc stream
    await safe_ws_send_json(ws, {"type": "status", "state": "idle"})

    return f"Tác vụ mở Goose Desktop. Thành công: {success}"
