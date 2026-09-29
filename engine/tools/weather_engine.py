import time
import logging
import httpx
import threading
import re
from typing import Optional

log = logging.getLogger("jarvis.weather")

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "weather_search": (
        "QUY TẮC ĐỊNH DẠNG THỜI TIẾT BẮT BUỘC:\n"
        "- Tóm tắt nhiệt độ, độ ẩm, sức gió và trạng thái thời tiết ngắn gọn.\n"
        "- Đưa ra lời khuyên thiết thực (mang ô, mặc ấm, hoạt động ngoài trời...) phù hợp với ngài erikpuw."
    ),
}

# Weather State (for greeting background thread)
_cached_weather: Optional[str] = None
_last_weather_fetch_time: float = 0.0
_ctx_cache = {"weather": "Weather data unavailable."}

import asyncio

_open_meteo_lock = threading.Lock()
_last_open_meteo_call = 0.0

def _throttle_open_meteo_sync(delay_sec: float = 2.0):
    global _last_open_meteo_call
    with _open_meteo_lock:
        now = time.time()
        elapsed = now - _last_open_meteo_call
        if elapsed < delay_sec:
            sleep_time = delay_sec - elapsed
            log.info(f"Throttling Open-Meteo (sync): sleeping for {sleep_time:.2f}s")
            time.sleep(sleep_time)
        _last_open_meteo_call = time.time()

async def _throttle_open_meteo_async(delay_sec: float = 2.0):
    global _last_open_meteo_call
    sleep_time = 0.0
    with _open_meteo_lock:
        now = time.time()
        elapsed = now - _last_open_meteo_call
        if elapsed < delay_sec:
            sleep_time = delay_sec - elapsed
        else:
            _last_open_meteo_call = now
    
    if sleep_time > 0.0:
        log.info(f"Throttling Open-Meteo (async): sleeping for {sleep_time:.2f}s")
        await asyncio.sleep(sleep_time)
        with _open_meteo_lock:
            _last_open_meteo_call = time.time()

# WMO weather codes → Vietnamese
WMO_CODES = {
    0: "Trời quang đãng",
    1: "Trời trong xanh",
    2: "Trời có mây rải rác",
    3: "Trời u ám",
    45: "Sương mù",
    48: "Sương muối",
    51: "Mưa phùn nhẹ",
    53: "Mưa phùn vừa",
    55: "Mưa phùn dày",
    56: "Mưa phùn băng giá nhẹ",
    57: "Mưa phùn băng giá dày",
    61: "Mưa nhẹ",
    63: "Mưa vừa",
    65: "Mưa lớn",
    66: "Mưa băng giá nhẹ",
    67: "Mưa băng giá nặng",
    71: "Tuyết rơi nhẹ",
    73: "Tuyết rơi vừa",
    75: "Tuyết rơi dày",
    77: "Mưa đá nhỏ",
    80: "Mưa rào nhẹ",
    81: "Mưa rào vừa",
    82: "Mưa rào nặng hạt",
    85: "Tuyết rào nhẹ",
    86: "Tuyết rào nặng",
    95: "Giông bão",
    96: "Giông kèm mưa đá nhẹ",
    99: "Giông kèm mưa đá nặng",
}

WIND_DIR = ["Bắc", "Bắc Đông", "Đông", "Nam Đông", "Nam", "Nam Tây", "Tây", "Bắc Tây"]

def _wind_dir_text(deg: float) -> str:
    idx = round(deg / 45) % 8
    return WIND_DIR[idx]

def _wmo_text(code: int) -> str:
    return WMO_CODES.get(code, f"Mã thời tiết {code}")


def _clean_location(location: str) -> str:
    """Loại bỏ các từ khóa nhiễu và chuẩn hóa viết tắt địa điểm."""
    loc = location.lower().strip()
    loc = re.sub(r"\b(tp\.?\s*hcm|tphcm|hcm)\b", "hồ chí minh", loc)
    noise_patterns = [
        r"\bdự báo thời tiết\b",
        r"\bthời tiết\b",
        r"\bdự báo\b",
        r"\btại\b",
        r"\bở\b",
        r"\bcủa\b",
        r"\btỉnh\b",
        r"\bhôm nay\b",
        r"\bngày mai\b",
        r"\bngày kia\b",
        r"\btuần này\b",
        r"\bra sao\b",
        r"\bthế nào\b",
        r"\bnhư thế nào\b",
    ]
    for pattern in noise_patterns:
        loc = re.sub(pattern, "", loc)
    loc = re.sub(r"\s+", " ", loc).strip()
    if not loc:
        return "Hồ Chí Minh"
    return loc


# ── Public API: weather_search (dùng cho tool) ──

async def weather_search(location: str) -> str:
    """Tra cứu thời tiết đầy đủ cho một địa điểm bằng Open-Meteo, tự động dự phòng sang fetch_weather()."""
    location = _clean_location(location)

    try:
        lat, lon, resolved = await _geocode(location)
        data = await _fetch_open_meteo(lat, lon)
        return _format_response(resolved, data)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            log.warning(f"Open-Meteo rate limit hit (429): {e}. Falling back to fetch_weather()")
            _mark_open_meteo_limited()
            return await fetch_weather()
        log.warning(f"Geocode failed for {location}: {e}")
        return f"Không tìm thấy địa điểm '{location}'."
    except Exception as e:
        err_msg = str(e)
        if "limit exceeded" in err_msg.lower() or "429" in err_msg or "too many requests" in err_msg.lower():
            log.warning(f"Open-Meteo rate limit hit: {e}. Falling back to fetch_weather()")
            _mark_open_meteo_limited()
            return await fetch_weather()
        log.warning(f"Weather search failed for {location}: {e}")
        return f"Không thể lấy dữ liệu thời tiết cho {location} lúc này."

    return _format_response(resolved, data)


async def _geocode(query: str) -> tuple[float, float, str]:
    """Open-Meteo Geocoding: tên → (lat, lon, resolved_name)."""
    await _throttle_open_meteo_async(2.0)
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "vi", "format": "json"},
        )
        r.raise_for_status()
        body = r.json()
    results = body.get("results")
    if not results:
        raise ValueError(f"Location '{query}' not found")
    r0 = results[0]
    return r0["latitude"], r0["longitude"], r0.get("name", query)


async def _fetch_open_meteo(lat: float, lon: float) -> dict:
    """Open-Meteo forecast: lấy current weather chi tiết."""
    await _throttle_open_meteo_async(2.0)
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "precipitation",
            "weathercode",
            "wind_speed_10m",
            "wind_direction_10m",
            "uv_index",
            "cloud_cover",
            "is_day",
        ]),
        "timezone": "auto",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
    }
    async with httpx.AsyncClient(timeout=5.0) as c:
        r = await c.get("https://api.open-meteo.com/v1/forecast", params=params)
        r.raise_for_status()
        return r.json()


def _format_response(resolved: str, data: dict) -> str:
    """Format dữ liệu Open-Meteo thành câu tiếng Việt đầy đủ."""
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    feels = cur.get("apparent_temperature")
    hum = cur.get("relative_humidity_2m")
    precip = cur.get("precipitation", 0)
    code = cur.get("weathercode", 0)
    wind_spd = cur.get("wind_speed_10m", 0)
    wind_dir = cur.get("wind_direction_10m")
    uv = cur.get("uv_index", 0)

    desc = _wmo_text(code)
    wd = _wind_dir_text(wind_dir) if wind_dir is not None else ""

    lines = [f"📍 Thời tiết tại {resolved}:"]
    lines.append(f"  🌡  Nhiệt độ: {temp}°C (cảm giác như {feels}°C).")
    lines.append(f"  ☁️  {desc}.")
    lines.append(f"  💧 Độ ẩm: {hum}%.")
    if precip and precip > 0:
        lines.append(f"  🌧  Lượng mưa: {precip} mm.")
    lines.append(f"  🌬  Gió: {wind_spd} km/h{', hướng ' + wd if wd else ''}.")
    lines.append(f"  ☀️  Chỉ số UV: {uv}.")

    return "\n".join(lines)


def sanitize_weather_display_text(text: str) -> str:
    """Dọn ký hiệu LaTeX do LLM chèn vào các đơn vị thời tiết."""
    if not text:
        return text

    cleaned = re.sub(r"\^\s*\\circ\s*C\b", "°C", text, flags=re.I)
    cleaned = re.sub(r"\\circ\s*C\b", "°C", cleaned, flags=re.I)
    cleaned = cleaned.replace(r"\%", "%")

    weather_measurement = r"[+-]?\d+(?:[.,]\d+)?\s*(?:km/h|m/s|mm|°C|%)"
    cleaned = re.sub(
        rf"\$(?=\s*{weather_measurement})",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.sub(
        rf"({weather_measurement})\$",
        r"\1",
        cleaned,
        flags=re.I,
    )
    return cleaned


# ── Legacy API (giữ cho greeting engine) ──

WEATHER_TRANSLATIONS = {
    "sunny": "trời nắng",
    "clear": "trời quang mây tạnh",
    "partly cloudy": "trời có mây rải rác",
    "cloudy": "trời nhiều mây",
    "overcast": "trời u ám",
    "mist": "sương mù nhẹ",
    "fog": "sương mù",
    "thunderstorm": "bão giông",
    "patchy rain nearby": "mưa rải rác gần đây",
    "patchy rain possible": "có thể có mưa rải rác",
    "patchy snow possible": "có thể có tuyết rải rác",
    "patchy sleet possible": "có thể có mưa tuyết rải rác",
    "patchy freezing drizzle possible": "có thể có mưa phùn băng giá",
    "thundery outbreaks in nearby": "có giông gần đây",
    "thundery outbreaks possible": "có thể có giông bão",
    "blowing snow": "tuyết thổi",
    "blizzard": "bão tuyết",
    "freezing fog": "sương mù đóng băng",
    "patchy light drizzle": "mưa phùn nhẹ rải rác",
    "light drizzle": "mưa phùn nhẹ",
    "freezing drizzle": "mưa phùn đóng băng",
    "heavy freezing drizzle": "mưa phùn đóng băng nặng hạt",
    "patchy light rain": "mưa nhẹ rải rác",
    "light rain": "mưa nhẹ",
    "moderate rain at times": "đôi khi có mưa vừa",
    "moderate rain": "mưa vừa",
    "heavy rain at times": "đôi khi có mưa to",
    "heavy rain": "mưa to",
    "light freezing rain": "mưa băng nhẹ",
    "moderate or heavy freezing rain": "mưa băng vừa hoặc mưa băng to",
    "light sleet": "mưa tuyết nhẹ",
    "moderate or heavy sleet": "mưa tuyết vừa hoặc mưa tuyết nặng",
    "patchy light snow": "tuyết rơi nhẹ rải rác",
    "light snow": "tuyết rơi nhẹ",
    "patchy moderate snow": "tuyết rơi vừa rải rác",
    "moderate snow": "tuyết rơi vừa",
    "patchy heavy snow": "tuyết rơi nhiều rải rác",
    "heavy snow": "tuyết rơi nhiều",
    "ice pellets": "mưa đá nhỏ",
    "light rain shower": "mưa rào nhẹ",
    "moderate or heavy rain shower": "mưa rào vừa hoặc mưa rào to",
    "torrential rain shower": "mưa rào như trút nước",
    "light sleet showers": "mưa tuyết rào nhẹ",
    "moderate or heavy sleet showers": "mưa tuyết rào vừa hoặc mưa tuyết rào to",
    "light snow showers": "tuyết rào nhẹ",
    "moderate or heavy snow showers": "tuyết rào vừa hoặc tuyết rào to",
    "light showers of ice pellets": "mưa đá rào nhẹ",
    "moderate or heavy showers of ice pellets": "mưa đá rào vừa hoặc mưa đá rào to",
    "patchy light rain with thunder": "mưa nhẹ rải rác kèm giông",
    "moderate or heavy rain with thunder": "mưa vừa hoặc mưa to kèm giông",
    "patchy light snow with thunder": "tuyết nhẹ rải rác kèm giông",
    "moderate or heavy snow with thunder": "tuyết vừa hoặc tuyết to kèm giông",
    "rain with thunderstorm": "mưa giông",
    "smoky haze": "trời mù khói bụi",
    "haze": "trời mù khói bụi",
}

def translate_weather_desc(desc: str) -> str:
    if not desc:
        return ""
    cleaned = desc.strip().lower()
    if cleaned in WEATHER_TRANSLATIONS:
        return WEATHER_TRANSLATIONS[cleaned]
    for en, vi in WEATHER_TRANSLATIONS.items():
        if en in cleaned:
            return vi
    return desc

_LOCATION_NAME = "Hồ Chí Minh"
_HCM_LAT, _HCM_LON = 10.762622, 106.660172
# Open-Meteo free giới hạn lượt gọi: dính 429 thì nghỉ nguồn này một lúc thay vì gọi lại liên tục.
_OPEN_METEO_COOLDOWN_SECONDS = 15 * 60
# Thời tiết không đổi từng phút: dùng lại kết quả gần đây để đỡ tốn lượt gọi.
_SNAPSHOT_TTL_SECONDS = 10 * 60
# Mọi nguồn đều lỗi thì vẫn dùng kết quả cũ nếu chưa quá hạn này.
_SNAPSHOT_STALE_SECONDS = 60 * 60
_open_meteo_blocked_until = 0.0
_snapshot_cache: Optional[tuple[float, dict]] = None


def _is_rate_limited(e: Exception) -> bool:
    if isinstance(e, httpx.HTTPStatusError) and e.response.status_code == 429:
        return True
    msg = str(e).lower()
    return "429" in msg or "limit exceeded" in msg or "too many requests" in msg


def _mark_open_meteo_limited() -> None:
    global _open_meteo_blocked_until
    _open_meteo_blocked_until = time.time() + _OPEN_METEO_COOLDOWN_SECONDS


def _describe_open_meteo(code, cloud_cover, is_day) -> str:
    """Mã WMO 0-3 chỉ phân loại mây rất thô (vd. mã 1 nhưng mây 42%); dùng % mây thật
    để biết là nắng hay nhiều mây. Có mưa/sương/giông (mã >= 45) thì theo mã."""
    code = int(code or 0)
    if code >= 45 or cloud_cover is None:
        return _wmo_text(code).lower()
    day = bool(is_day)
    if cloud_cover < 20:
        return "trời nắng đẹp" if day else "trời quang"
    if cloud_cover < 50:
        return "trời nắng, có ít mây" if day else "trời ít mây"
    if cloud_cover < 85:
        return "trời nhiều mây"
    return "trời u ám"


def _classify(desc: str) -> Optional[str]:
    """Nhóm bầu trời cho lời nhắc. Thứ tự quan trọng: 'sương mù khói' là khói bụi, không phải sương."""
    d = (desc or "").lower()
    for kind, keys in (
        ("storm", ("giông", "bão", "thunder", "storm")),
        ("rain", ("mưa", "rain", "drizzle", "shower")),
        ("snow", ("tuyết", "snow")),
        ("haze", ("khói", "bụi", "haze", "smoke")),
        ("fog", ("sương", "fog", "mist")),
        ("clear", ("nắng", "quang", "trong xanh", "sunny", "clear")),
        ("cloudy", ("mây", "u ám", "cloud", "overcast")),
    ):
        if any(k in d for k in keys):
            return kind
    return None


async def _open_meteo_snapshot() -> dict:
    data = await _fetch_open_meteo(_HCM_LAT, _HCM_LON)
    cur = data.get("current", {})
    temp = cur.get("temperature_2m")
    return {
        "desc": _describe_open_meteo(cur.get("weathercode"), cur.get("cloud_cover"), cur.get("is_day", 1)),
        "temp": round(temp) if temp is not None else None,
        "is_day": bool(cur.get("is_day", 1)),
        "source": "open-meteo",
    }


async def _wttr_snapshot() -> Optional[dict]:
    async with httpx.AsyncClient(timeout=5.0) as http:
        resp = await http.get(
            "https://wttr.in/h%E1%BB%93%20ch%C3%AD%20minh",
            params={"format": "%C|%t", "lang": "en"},
        )
        resp.raise_for_status()
    desc_en, _, temp_raw = resp.text.strip().partition("|")
    m = re.search(r"-?\d+", temp_raw)
    # wttr trả trang lỗi/HTML khi quá tải; không đúng dạng "Mô tả|+31°C" thì bỏ.
    if not m or not desc_en or len(desc_en) > 60 or "<" in desc_en:
        return None
    return {"desc": translate_weather_desc(desc_en).lower(), "temp": int(m.group()), "is_day": None, "source": "wttr"}


def _baomoi_snapshot(temp_raw, desc_raw) -> Optional[dict]:
    """Báo Mới là cào HTML: trang đổi giao diện hoặc chặn bot thì selector trả rác —
    chỉ nhận khi nhiệt độ là số hợp lý và mô tả là một cụm ngắn."""
    m = re.fullmatch(r"\s*\+?(-?\d{1,2})\s*°?\s*C?\s*", temp_raw or "")
    desc = (desc_raw or "").strip()
    if not m or not (2 <= len(desc) <= 40) or not -10 <= int(m.group(1)) <= 50:
        return None
    return {"desc": desc[0].lower() + desc[1:], "temp": int(m.group(1)), "is_day": None, "source": "baomoi"}


async def _baomoi_fetch_snapshot() -> Optional[dict]:
    from scrapling.fetchers import AsyncFetcher
    response = await AsyncFetcher.get("https://baomoi.com/tien-ich-thoi-tiet.epi", timeout=10)
    if getattr(response, "status", 200) != 200:
        return None
    return _baomoi_snapshot(
        response.css("span[class*='text-[5rem]']::text").get(),
        response.css("span[class*='text-[#777]'][class*='ml-[13px]']::text").get(),
    )


async def fetch_weather_snapshot() -> Optional[dict]:
    """Thời tiết hiện tại ở dạng có cấu trúc: {desc, temp, is_day, kind, source, text}.
    Thứ tự: Open-Meteo (số đo chính xác) -> wttr.in (free, khi Open-Meteo bị limit/lỗi)
    -> Báo Mới (cào web, dễ bị chặn bot nên để cuối)."""
    global _snapshot_cache
    now = time.time()
    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_TTL_SECONDS:
        return _snapshot_cache[1]

    sources = []
    if now >= _open_meteo_blocked_until:
        sources.append(("open-meteo", _open_meteo_snapshot))
    sources += [("wttr", _wttr_snapshot), ("baomoi", _baomoi_fetch_snapshot)]

    for name, fetch in sources:
        try:
            snap = await fetch()
        except Exception as e:
            if name == "open-meteo" and _is_rate_limited(e):
                _mark_open_meteo_limited()
                log.warning("Open-Meteo rate limited; dùng nguồn khác trong %d phút", _OPEN_METEO_COOLDOWN_SECONDS // 60)
            else:
                log.warning(f"Weather source {name} failed: {e}")
            continue
        if snap and snap.get("desc"):
            snap["kind"] = _classify(snap["desc"])
            temp = f", nhiệt độ {snap['temp']}°C" if snap.get("temp") is not None else ""
            snap["text"] = f"Thời tiết tại {_LOCATION_NAME} hiện tại là {snap['desc']}{temp}"
            _snapshot_cache = (now, snap)
            _ctx_cache["weather"] = snap["text"]
            return snap

    if _snapshot_cache and now - _snapshot_cache[0] < _SNAPSHOT_STALE_SECONDS:
        return _snapshot_cache[1]
    return None


async def fetch_weather() -> str:
    """Bản chữ của fetch_weather_snapshot (dùng làm fallback cho weather_search)."""
    snap = await fetch_weather_snapshot()
    return snap["text"] if snap else "Hiện chưa có thông tin thời tiết."
