import logging
import json
import asyncio
import base64
from typing import Any

log = logging.getLogger("jarvis.agent_search")

_ALL_TOOLS = ["get_market_data", "search_products", "search_news", "weather_search", "map_route", "map_pois", "get_vannien_data","get_zodiac_data","get_cgv_movies","get_epic_free_games", "vietnam_data_lookup", "web_research"]

_WEATHER_KW = ["thời tiết", "nhiệt độ", "dự báo", "độ ẩm", "mưa", "gió", "nóng", "lạnh"]
_NEWS_KW = ["tin tức", "tin nóng", "tin mới", "bản tin", "thời sự", "sự kiện", "đọc báo", "báo chí", "news"]
_MARKET_KW = ["Vàng", "Xăng", "Dầu", "USD", "Gas", "giá", "báo cáo giá", "tổng hợp giá", "tỷ giá"]
_PRODUCT_KW = ["sản phẩm", "iphone", "ipad", "macbook", "laptop", "ram", "ddr", "ssd", "điện thoại", "máy tính", "shopee", "cellphones", "fpt shop", "bách hóa xanh", "aeon", "lotte"]
_MAP_KW = ["bản đồ", "đường đến", "gần đây", "chỉ đường", "khoảng cách", "lộ trình", "địa điểm", "poi"]
_ZODIAC_KW = ["hoàng đạo", "bạch dương", "kim ngưu", "song tử","cự giải", "sư tử", "xử nữ", "thiên bình", "hổ cáp", "nhân mã", "ma kết", "bảo bình", "song ngư"]
_VANNIEN_KW = ["vạn niên", "lịch âm"]
_CGV_KW = ["phim đang chiếu", "phim sắp chiếu", "cgv", "lịch phim", "lịch chiếu phim", "rạp phim", "rạp chiếu phim", "suất chiếu", "vé xem phim"]
_EPIC_KW = ["game miễn phí", "trò chơi tuần epic"]
_DATA_KW = ["hành chính", "tỉnh", "phường", "xã", "mã hành chính", "ranh giới"]

def _select_tools(text: str, ws: Any = None) -> list[str]:
    tl = text.lower()
    selected = []

# Yêu cầu tin tức được ưu tiên hơn sản phẩm: "tìm tin tức về RAM DDR5..."
    # PHẢI dùng search_news, kể cả khi nội dung chứa từ khóa sản phẩm (ram/ddr/laptop).
    has_news = any(kw in tl for kw in _NEWS_KW)
    has_product = any(kw in tl for kw in _PRODUCT_KW)
    if has_product and not has_news:
        return ["search_products"]
    if any(kw in tl for kw in _DATA_KW):
        selected.append("vietnam_data_lookup")
    if any(kw in tl for kw in _WEATHER_KW):
        selected.append("weather_search")
    if has_news:
        selected.append("search_news")
    if any(kw in tl for kw in _MARKET_KW):
        selected.append("get_market_data")
    if any(kw in tl for kw in _ZODIAC_KW):
        selected.append("get_zodiac_data")
    if any(kw in tl for kw in _VANNIEN_KW):
        selected.append("get_vannien_data")
    if any(kw in tl for kw in _CGV_KW):
        selected.append("get_cgv_movies")
    if any(kw in tl for kw in _EPIC_KW):
        selected.append("get_epic_free_games")
    if any(kw in tl for kw in _MAP_KW):
        if "đường" in tl or "đến" in tl or "từ" in tl:
            selected.append("map_route")
        else:
            selected.append("map_pois")
            
    if selected:
        return selected

    # Chỉ fallback về công cụ tìm kiếm tin tức tối thiểu thay vì chạy toàn bộ 8 tools
    return ["search_news"]

async def run_search_agent(
    user_text: str,
    conversation_history: list,
    ws: Any,
    flow_tracker=None,
    flow_agents=None,
    **kwargs
) -> str:
    from engine.core.actions import handle_user_intent_with_tools, get_agent_context_and_tools
    if not flow_tracker:
        class NoOpFlowTracker:
            def step(self, label):
                class NoOpStep:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStep()
            async def track(self, *args, **kwargs): pass
        flow_tracker = NoOpFlowTracker()

    if not flow_agents:
        class NoOpFlowAgents:
            def step(self, label, emoji=None, agent_name=None):
                class NoOpStep:
                    async def __aenter__(self): return self
                    async def __aexit__(self, *args): pass
                return NoOpStep()
            async def track(self, *args, **kwargs): pass
        flow_agents = NoOpFlowAgents()

    log.info(f"Agent Search activated for query: '{user_text}'")

    # Chế độ mục tiêu (engine/plans) chọn tool tường minh qua kwargs "tools" (đích "web" → web_research);
    # chỉ nhận tool thuộc agent này. Không có → chọn theo từ khoá như cũ.
    forced = [t for t in (kwargs.get("tools") or []) if t in _ALL_TOOLS]
    tool_names = forced or _select_tools(user_text)
    if ws:
        ws.last_tools = tool_names
    log.info(f"Selected tools: {tool_names}")
    search_tools = get_agent_context_and_tools(tool_names)
    _TOOL_VI = {
        "get_market_data": f"Thực thi: {user_text}" ,
        "search_products": f"Thực thi: {user_text}",
        "search_news": f"Thực thi: {user_text}",
        "weather_search": f"Thực thi: {user_text}",
        "map_route": f"Thực thi: {user_text}",
        "map_pois": f"Thực thi: {user_text}",
        "get_vannien_data": f"Thực thi: {user_text}",
        "get_zodiac_data": f"Thực thi: {user_text}",
        "get_cgv_movies": f"Thực thi: {user_text}",
        "vietnam_data_lookup": f"Thực thi: {user_text}",
        "get_epic_free_games": f"Thực thi: {user_text}",
        "web_research": f"Thực thi: {user_text}",
    }
    friendly = " / ".join(_TOOL_VI.get(t, t) for t in tool_names)
    try:
        async with flow_tracker.step("Agent Search"):
            async with flow_agents.step(friendly, emoji="🔍", agent_name="Agent Search"):
                response_text = await handle_user_intent_with_tools(
                    user_text=user_text,
                    add_tools=search_tools,
                    conversation_history=conversation_history,
                    ws=ws,
                    agent_name="Agent Search",
                    flow_tracker=flow_tracker,
                    flow_agents=flow_agents,
                    silent=kwargs.get("silent", False),
                )
            return response_text

    except Exception as e:
        log.error(f"Error in Agent Search execution: {e}", exc_info=True)
        
        fallback_err = f"Lỗi thực thi Agent Search: {e}"
        return fallback_err
