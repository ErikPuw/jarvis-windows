# -*- coding: utf-8 -*-
"""Map routing & POI lookup via Nominatim (OpenStreetMap).

Tách ra khỏi engine/core/actions.py — logic gọi API bản đồ không thuộc về
file điều phối tool, mà nên nằm trong module tool riêng giống
weather_engine.py, shop_engine.py. Hành vi giữ nguyên 100% so với bản gốc.
"""

import logging

import httpx

log = logging.getLogger("jarvis.map_engine")

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
_USER_AGENT = "Jarvis-Agent/3.0"


async def map_route(origin: str, destination: str, ws=None, safe_ws_send_json=None) -> str:
    """Tìm tọa độ 2 điểm qua Nominatim và vẽ đường đi trên bản đồ Frontend."""
    if not origin or not destination:
        return "Lỗi: Thiếu điểm xuất phát hoặc điểm đến."

    async with httpx.AsyncClient(timeout=10.0) as client:
        res_origin = await client.get(
            NOMINATIM_SEARCH_URL,
            params={"format": "json", "q": origin, "limit": 1},
            headers={"User-Agent": _USER_AGENT},
        )
        data_origin = res_origin.json()
        if not data_origin:
            return f"Không tìm thấy tọa độ cho điểm xuất phát: {origin}"

        res_dest = await client.get(
            NOMINATIM_SEARCH_URL,
            params={"format": "json", "q": destination, "limit": 1},
            headers={"User-Agent": _USER_AGENT},
        )
        data_dest = res_dest.json()
        if not data_dest:
            return f"Không tìm thấy tọa độ cho điểm đến: {destination}"

        orig_lat = float(data_origin[0]["lat"])
        orig_lng = float(data_origin[0]["lon"])
        dest_lat = float(data_dest[0]["lat"])
        dest_lng = float(data_dest[0]["lon"])

        if ws and safe_ws_send_json:
            await safe_ws_send_json(ws, {
                "type": "map_route",
                "from_lat": orig_lat,
                "from_lng": orig_lng,
                "to_lat": dest_lat,
                "to_lng": dest_lng,
            })

        return (
            f"Đã vẽ đường đi trên bản đồ từ {origin} ({orig_lat:.4f}, {orig_lng:.4f}) "
            f"đến {destination} ({dest_lat:.4f}, {dest_lng:.4f})."
        )


async def map_pois(category: str, location: str, ws=None, safe_ws_send_json=None) -> str:
    """Tìm các địa điểm (POI) theo category quanh 1 vị trí và ghim lên bản đồ Frontend."""
    if not category or not location:
        return "Lỗi: Thiếu loại địa điểm (category) hoặc vị trí (location)."

    async with httpx.AsyncClient(timeout=10.0) as client:
        query_str = f"{category} in {location}"
        res = await client.get(
            NOMINATIM_SEARCH_URL,
            params={"format": "json", "q": query_str, "limit": 10},
            headers={"User-Agent": _USER_AGENT},
        )
        data = res.json()
        if not data:
            return f"Không tìm thấy {category} nào ở {location}."

        pois = []
        for item in data:
            pois.append({
                "name": item.get("display_name", "").split(",")[0],
                "lat": float(item["lat"]),
                "lng": float(item["lon"]),
                "type": category,
            })

        if ws and safe_ws_send_json:
            await safe_ws_send_json(ws, {
                "type": "map_pois",
                "pois": pois,
            })

        names_str = ", ".join(p["name"] for p in pois[:5])
        return f"Tìm thấy {len(pois)} địa điểm {category} tại {location}. Đã hiển thị trên bản đồ: {names_str}."
