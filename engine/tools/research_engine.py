"""Tool web_research: tìm hiểu thông tin chung trên web cho chế độ mục tiêu (spec 2026-09-26).
Tìm bằng browser.search_news (Google News RSS trước, DDG/Google sau) rồi đọc 3 bài đầu song song.
browser.research() (DDG) không dùng được: DDG trả 202 chống bot trên máy thật (2026-09-27).
Mỗi trang qua chốt chặn prompt injection (engine/plans/untrusted.py) trước khi tới model."""
import asyncio
import logging

from engine.plans.untrusted import clean, looks_injected

log = logging.getLogger("jarvis.research_engine")

RESEARCH_TIMEOUT_S = 45
_PAGES = 3
_PAGE_CHARS = 1500
_VISIT_TIMEOUT_MS = 12_000
_PAGE_SEP = "\n\n---\n\n"


async def _read(result) -> str:
    """Một bài: nội dung trang, không đọc được thì dùng đoạn trích của kết quả tìm kiếm."""
    from engine.tools.browser import browser
    try:
        page = await browser.visit_article(result.url, timeout_ms=_VISIT_TIMEOUT_MS)
    except Exception as exc:
        log.info("[RESEARCH] visit failed %s: %s", result.url, exc)
        page = None
    # gộp khoảng trắng: trang báo trả rất nhiều dòng trống, phí giới hạn _PAGE_CHARS
    text = " ".join((page.text_content if page and page.text_content else result.snippet or "").split())
    return f"## {result.title}\nURL: {result.url}\n\n{text[:_PAGE_CHARS]}" if text else ""


async def _collect(query: str) -> list[str]:
    from engine.tools.browser import browser
    results = await browser.search_news(query, vietnam_only=True)
    return list(await asyncio.gather(*(_read(r) for r in results[:_PAGES])))


async def web_research(query: str) -> str:
    query = " ".join((query or "").split())
    if not query:
        return "Không tìm thấy thông tin: thiếu nội dung cần tìm."
    try:
        raw_pages = await asyncio.wait_for(_collect(query), RESEARCH_TIMEOUT_S)
    except asyncio.TimeoutError:
        log.warning("[RESEARCH] timeout after %ss: %r", RESEARCH_TIMEOUT_S, query)
        return f"Không tìm thấy thông tin cho '{query}': quá thời gian tra cứu."
    except Exception as exc:
        log.warning("[RESEARCH] failed for %r: %s", query, exc)
        return f"Không tìm thấy thông tin cho '{query}': lỗi khi tra cứu."
    pages = []
    for page in raw_pages:
        page = clean(page).strip()
        if not page:
            continue
        if looks_injected(page):
            log.warning("[PLAN] injection suspected in web page, dropped: %r", page[:160])
            continue
        pages.append(page)
    if not pages:
        return f"Không tìm thấy thông tin dùng được cho '{query}'."
    return f"Kết quả tìm hiểu trên web cho '{query}':\n\n" + _PAGE_SEP.join(pages)
