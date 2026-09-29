"""
FlowAgents — Điều phối gửi trạng thái hoạt động của các Agents qua Interactive Card.
"""

import logging
import time
import uuid

log = logging.getLogger("jarvis.flow_agents")


def _new_turn_id() -> str:
    """Unique per turn. Wall-clock seconds alone collided whenever two turns
    landed in the same second (barge-in, quick re-ask), so turn 2's cards
    overwrote turn 1's in the UI."""
    return f"{int(time.time())}_{uuid.uuid4().hex[:6]}"

# Ánh xạ Agent sang Emoji tương ứng (phục vụ fallback tương thích ngược)
AGENT_EMOJIS = {
    "search": "🔍",
    "webcam": "📷",
    "vision": "👁️",
    "media": "🎵",
    "history": "📜",
    "desktop": "💻",
    "co-ordinator": "🤖"
}

def get_emoji_and_title(label: str) -> tuple[str, str]:
    label_lower = label.lower()
    for key, emoji in AGENT_EMOJIS.items():
        if key in label_lower:
            return emoji, f"Agent {key.capitalize()}"
    if "lịch sử" in label_lower:
        return "📜", "Agent History"
    return "🤖", "Agent Co-ordinator"

class AgentStepContext:
    def __init__(self, tracker, label: str, emoji: str = None, agent_name: str = None):
        self.tracker = tracker
        self.label = label
        self.emoji = emoji
        self.agent_name = agent_name
        self._call_id = tracker._next_call_id()

    async def __aenter__(self):
        await self.tracker.track(self.label, "active", self.emoji, self.agent_name, call_id=self._call_id)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            await self.tracker.track(self.label, "failed", self.emoji, self.agent_name, call_id=self._call_id)
        else:
            await self.tracker.track(self.label, "completed", self.emoji, self.agent_name, call_id=self._call_id)


class FlowAgents:
    def __init__(self, ws, safe_send):
        self._ws = ws
        self._send = safe_send
        self._seq = 0
        self._steps: list[dict] = []
        self._turn_id = _new_turn_id()
        self._active_cards = {}  # card_id -> (label, emoji, agent_name, call_id)
        self._call_seq = 0

    def reset(self):
        self._seq = 0
        self._steps.clear()
        self._turn_id = _new_turn_id()
        self._active_cards.clear()
        self._call_seq = 0

    def _next_call_id(self) -> int:
        self._call_seq += 1
        return self._call_seq

    def step(self, label: str, emoji: str = None, agent_name: str = None):
        """Trả về AgentStepContext để dùng với cú pháp 'async with flow_agents.step(label)'."""
        return AgentStepContext(self, label, emoji, agent_name)

    async def track(self, label: str, status: str = "completed", emoji: str = None, agent_name: str = None, call_id: int = None):
        # Nếu thiếu emoji hoặc agent_name, tự động suy luận (fallback tương thích ngược)
        if not emoji or not agent_name:
            emoji_fallback, agent_name_fallback = get_emoji_and_title(label)
            emoji = emoji or emoji_fallback
            agent_name = agent_name or agent_name_fallback

        card_id = f"agent_tracker_{agent_name.replace(' ', '_').lower()}_{self._turn_id}"
        if call_id is not None:
            card_id = f"{card_id}_{call_id}"

        # Ghi nhận trạng thái hoạt động của card
        if status == "active":
            self._active_cards[card_id] = (label, emoji, agent_name, call_id)
        elif status in ("completed", "failed"):
            if card_id not in self._active_cards:
                log.debug("Ignoring duplicate agent tracker terminal status: %s | status=%s", card_id, status)
                return
            self._active_cards.pop(card_id, None)
        
        # Gửi sự kiện interactive card loại tracker về Frontend
        card_data = {
            "id": card_id,
            "type": "tracker",
            "title": f"{emoji} {agent_name}",
            "status": status,
            "label": label
        }
        
        log.info(f"Sending agent tracker card: {card_id} | status={status}")
        await self._send(self._ws, {
            "type": "interactive",
            "card": card_data
        })

    async def fail_all_active(self):
        """Đóng tất cả các card đang hoạt động dưới trạng thái failed để tránh treo UI."""
        for card_id, (label, emoji, agent_name, call_id) in list(self._active_cards.items()):
            await self.track(label, "failed", emoji, agent_name, call_id=call_id)
        self._active_cards.clear()

    async def complete_all_active(self):
        """Đóng tất cả các card đang hoạt động dưới trạng thái completed khi kết thúc thành công."""
        for card_id, (label, emoji, agent_name, call_id) in list(self._active_cards.items()):
            await self.track(label, "completed", emoji, agent_name, call_id=call_id)
        self._active_cards.clear()
