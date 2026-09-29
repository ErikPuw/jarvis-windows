"""Tra cứu giá sản phẩm từ các trang bán lẻ đã được người dùng phê duyệt."""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from urllib.parse import quote, quote_plus

from engine.tools.browser import browser


log = logging.getLogger(__name__)

# Quy tắc định dạng cho LLM vòng 2 — bàn giao từ actions.py cho tool sở hữu
SUMMARY_RULES: dict[str, str] = {
    "search_products": (
        "QUY TẮC ĐỊNH DẠNG TRA GIÁ SẢN PHẨM BẮT BUỘC:\n"
        "- Giữ nguyên tên sản phẩm, giá niêm yết, nguồn và liên kết từ kết quả công cụ.\n"
        "- Không tự suy đoán hoặc bổ sung giá không có trong dữ liệu nguồn.\n"
        "- Nếu công cụ đang hỏi địa điểm AEON hoặc LOTTE, chỉ chuyển nguyên câu hỏi đó cho người dùng."
    ),
}

_TECH_KW = (
    "iphone", "ipad", "macbook", "laptop", "legion", "thinkpad", "ram",
    "ddr", "ssd", "cpu", "gpu", "điện thoại", "máy tính", "tai nghe",
    "sạc", "màn hình", "samsung", "xiaomi", "oppo", "vivo",
)
_GROCERY_KW = (
    "đi chợ", "thịt", "gà", "heo", "bò", "cá", "tôm", "rau", "củ",
    "quả", "trái cây", "kimchi", "kim chi", "sữa", "gạo", "mì", "nước",
    "gia vị", "thực phẩm", "bánh", "kẹo",
)
_PRICE_RE = re.compile(
    r"(?P<price>\d{1,3}(?:[.\s]\d{3})+|\d{4,})\s*(?:₫|đ|vnđ|vnd)(?!\w)",
    re.IGNORECASE,
)
_NOISE_RE = re.compile(
    r"^(?:đăng nhập|giỏ hàng|danh mục|xem thêm|mua ngay|so sánh|"
    r"trang chủ|khuyến mãi|sản phẩm|tìm kiếm|giảm|giam)$",
    re.IGNORECASE,
)
_NON_PRODUCT_PREFIXES = (
    "css_prices",
    "smember",
    "s-student",
    "tra gop",
    "them vao so sanh",
)
_QUERY_STOPWORDS = frozenset({
    "tim", "kiem", "tra", "cuu", "xem", "mua", "gia", "san", "pham",
})
_PRODUCT_QUERY_PREFIX_RE = re.compile(
    r"^(?:(?:hãy|giúp|vui\s+lòng|làm\s+ơn)\s+)?"
    r"(?:tìm(?:\s+kiếm)?|tra(?:\s+cứu)?|xem)\s+"
    r"(?:(?:sản\s+ph(?:ẩm|ầm)|mặt\s+hàng|công\s+nghệ|bách\s+hóa|giá)\s+)?",
    re.IGNORECASE,
)

LOTTE_STORES = {
    "nam sai gon": ("vi-nsg", "LOTTE Mart Nam Sài Gòn"),
    "nam sai gòn": ("vi-nsg", "LOTTE Mart Nam Sài Gòn"),
    "binh duong": ("vi-bdg", "LOTTE Mart Bình Dương"),
    "bình dương": ("vi-bdg", "LOTTE Mart Bình Dương"),
    "da nang": ("vi-dda", "LOTTE Mart Đà Nẵng"),
    "đà nẵng": ("vi-dda", "LOTTE Mart Đà Nẵng"),
    "ba dinh": ("vi-bdh", "LOTTE Mart Ba Đình"),
    "ba đình": ("vi-bdh", "LOTTE Mart Ba Đình"),
}


def _plain(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"\w+", _plain(query))
        if len(token) >= 3 and token not in _QUERY_STOPWORDS
    }


def _name_after_price(lines: list[str], index: int, query_tokens: set[str]) -> str:
    """FPT xếp giá trước tên (giá gốc, % giảm, giá sale, 'Giảm Xđ', hết giờ, rồi tên).
    Chỉ gọi cho dòng giá trần — nhìn về sau vài dòng để lấy tên thật của sản phẩm."""
    for look in range(index + 1, min(index + 7, len(lines))):
        candidate = lines[look].strip(" :-|")
        plain_candidate = _plain(candidate)
        if (
            len(candidate) < 4
            or _NOISE_RE.match(candidate)
            or plain_candidate.startswith(_NON_PRODUCT_PREFIXES)
        ):
            continue
        if query_tokens and not any(
            re.search(rf"\b{re.escape(token)}\b", plain_candidate)
            for token in query_tokens
        ):
            continue
        if _PRICE_RE.search(candidate):
            continue
        return candidate
    return ""


def normalize_product_query(query: str) -> str:
    """Bỏ tiền tố ra lệnh, chỉ giữ từ khóa sản phẩm cho website bán lẻ."""
    cleaned = _PRODUCT_QUERY_PREFIX_RE.sub("", query.strip(), count=1).strip()
    return cleaned or query.strip()


def classify_product_query(query: str) -> str:
    """Phân loại nguồn cần tra mà không đưa logic mua sắm vào search_engine."""
    text = query.lower()
    if any(keyword in text for keyword in _TECH_KW):
        return "technology"
    if any(keyword in text for keyword in _GROCERY_KW):
        return "grocery"
    return "general"


def build_source_urls(
    query: str,
    category: str,
    *,
    lotte_store: str | None = None,
) -> list[dict[str, str]]:
    """Tạo URL tìm kiếm theo đúng thanh tìm kiếm của từng nguồn."""
    encoded = quote_plus(query.strip())
    if category == "technology":
        return [
            {
                "source": "CellphoneS",
                "url": f"https://cellphones.com.vn/catalogsearch/result?q={encoded}",
            },
            {
                "source": "FPT Shop",
                "url": f"https://fptshop.com.vn/tim-kiem?s={encoded}",
            },
        ]
    if category == "general":
        return [{
            "source": "Shopee",
            "url": f"https://shopee.vn/search?keyword={encoded}",
        }]

    sources = [
        {
            "source": "Bách Hóa Xanh",
            "url": f"https://www.bachhoaxanh.com/tim-kiem?key={encoded}",
        },
        {
            "source": "AEONESHOP",
            "url": f"https://aeoneshop.com/products/search/{quote(query.strip())}",
        },
    ]
    if lotte_store:
        sources.append({
            "source": "LOTTE Mart",
            "store": lotte_store,
            "url": f"https://www.lottemart.vn/{lotte_store}/category?q={encoded}",
        })
    return sources


def _lotte_choice(text: str) -> tuple[str, str] | None:
    plain = _plain(text)
    if re.fullmatch(r"vi-[a-z]{3}", plain.strip()):
        return plain.strip(), plain.strip()
    for label, value in LOTTE_STORES.items():
        if _plain(label) in plain:
            return value
    return None


def _extract_rows(
    text: str,
    source: str,
    url: str,
    limit: int = 5,
    *,
    query: str = "",
) -> list[dict[str, str]]:
    query_tokens = _query_tokens(query)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [
        line for line in lines
        if line and not _plain(line).startswith("css_prices:")
    ]
    rows_by_name: dict[str, dict[str, str]] = {}
    seen: set[tuple[str, str]] = set()
    for index, line in enumerate(lines):
        match = _PRICE_RE.search(line)
        if not match:
            continue
        label = line[:match.start()].strip(" :-|")
        if label:
            if not (
                len(label) >= 4
                and not _NOISE_RE.match(label)
                and not _plain(label).startswith(_NON_PRODUCT_PREFIXES)
            ):
                continue
            name = label
        else:
            prev_name = ""
            if index:
                prev = lines[index - 1].strip(" :-|")
                if (
                    len(prev) >= 4
                    and not _NOISE_RE.match(prev)
                    and not _plain(prev).startswith(_NON_PRODUCT_PREFIXES)
                    and not _PRICE_RE.search(prev)
                ):
                    prev_name = prev
            name = prev_name
            if not name:
                name = _name_after_price(lines, index, query_tokens)
                if not name:
                    continue
        plain_name = _plain(name)
        if query_tokens and not any(
            re.search(rf"\b{re.escape(token)}\b", plain_name)
            for token in query_tokens
        ):
            continue
        price = match.group(0).replace(" ", "")
        key = (name.casefold(), price.casefold())
        if key in seen:
            continue
        seen.add(key)
        rows_by_name[name.casefold()] = {
            "name": name[:140],
            "price": price,
            "source": source,
            "url": url,
        }
        if len(rows_by_name) >= limit:
            break
    return list(rows_by_name.values())


async def _fetch_source(
    item: dict[str, str],
    query: str,
) -> tuple[dict[str, str], list[dict[str, str]]]:
    try:
        page = await browser.visit_product_listing(item["url"])
        return item, _extract_rows(
            page.text_content,
            item["source"],
            item["url"],
            query=query,
        )
    except Exception as exc:
        log.warning("Không thể tra giá từ %s: %s", item["source"], exc)
        return item, []


def _format_results(
    query: str,
    fetched: list[tuple[dict[str, str], list[dict[str, str]]]],
) -> str:
    lines = [
        f"Kết quả tra giá cho **{query}**:",
        "",
        "| Sản phẩm | Giá niêm yết | Nguồn |",
        "| :--- | ---: | :--- |",
    ]
    found = False
    for source, rows in fetched:
        for row in rows:
            found = True
            lines.append(
                f"| {row['name']} | {row['price']} | "
                f"[{source['source']}]({row['url']}) |"
            )
    if not found:
        lines = [
            f"Chưa trích xuất được giá có cấu trúc cho **{query}**. "
            "Có thể website đang yêu cầu JavaScript, cookie hoặc xác minh truy cập.",
            "",
            "Bạn có thể xem trực tiếp:",
        ]
        lines.extend(f"- [{item['source']}]({item['url']})" for item, _ in fetched)
    lines.extend([
        "",
        "Giá và tình trạng hàng có thể thay đổi; Jarvis chỉ tra cứu, không đặt hàng.",
    ])
    return "\n".join(lines)


async def search_products(query: str, ws=None) -> str:
    """Tra giá sản phẩm từ từ khóa hiện tại, không giữ trạng thái mua sắm riêng."""
    original_query = normalize_product_query(query)
    if not original_query:
        return "Vui lòng cho biết tên sản phẩm cần tra giá."

    category = classify_product_query(original_query)
    text = original_query.lower()
    lotte_choice = _lotte_choice(original_query) if category == "grocery" else None
    lotte_store = lotte_choice[0] if lotte_choice else None

    sources = build_source_urls(
        original_query,
        category,
        lotte_store=lotte_store,
    )
    if category == "grocery":
        if "aeon" in text:
            sources = [item for item in sources if item["source"] == "AEONESHOP"]
        elif "lotte" in text and lotte_store:
            sources = [item for item in sources if item["source"] == "LOTTE Mart"]
        elif "bách hóa xanh" in text or "bach hoa xanh" in text:
            sources = [item for item in sources if item["source"] == "Bách Hóa Xanh"]
    fetched = await asyncio.gather(*(
        _fetch_source(item, original_query) for item in sources
    ))
    return _format_results(original_query, list(fetched))
