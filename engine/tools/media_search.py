import asyncio
import json
import logging
import re
import subprocess
import unicodedata
from pathlib import Path

log = logging.getLogger("jarvis.media_search")


def summary_rules(content: str) -> str:
    """Quy tắc định dạng cho LLM vòng 2 — quyết định theo nội dung kết quả (bảng phim/video hay bài báo tin tức)."""
    if "baomoi.com" not in content:
        # Kết quả tool đã có sẵn bảng đúng (format_media_table); tự dựng bảng khác từng đổi tên cột
        # thành "Tên sản phẩm | Giá" và giữ nhầm dòng, lệch với video thật đang phát.
        return (
            "QUY TẮC ĐỊNH DẠNG KẾT QUẢ PHIM / VIDEO BẮT BUỘC:\n"
            "1. Chép NGUYÊN VĂN bảng Markdown trong kết quả công cụ: đủ mọi dòng, giữ nguyên tiêu đề cột, không tự dựng bảng khác, không dùng gạch đầu dòng.\n"
            "2. Nếu kết quả có dòng 'ĐANG PHÁT: ...' thì nói đúng tên đó là nội dung đang phát.\n"
            "3. Tuyệt đối không chèn thêm dòng trống xen kẽ trong bảng."
        )
    return (
        "QUY TẮC ĐỊNH DẠNG BÀI BÁO TIN TỨC BẮT BUỘC:\n"
        "- Dựng bảng Markdown riêng từng loại (vàng, xăng dầu, đô la, gas) có header rõ ràng.\n"
        "- Tuyệt đối không để dòng trống xen kẽ trong bảng."
    )


def slugify(text: str) -> str:
    """Convert Vietnamese text to hhpanda URL slug (e.g. 'Tiên Nghịch' -> 'tien-nghich')."""
    text = text.lower().strip()
    text = text.replace('\u0111', 'd')  # đ -> d
    text = unicodedata.normalize('NFKD', text)
    text = text.encode('ascii', 'ignore').decode('ascii')
    text = re.sub(r'[^a-z0-9-]', '-', text)
    text = re.sub(r'-+', '-', text)
    return text.strip('-')


def clean_phim_title(title: str) -> str:
    """Lọc sạch các từ khóa thừa trong tên phim của HHPanda."""
    if not title:
        return ""
    # Loại bỏ các cụm từ thừa phổ biến
    t = re.sub(r'\s*-\s*Xem phim\b', '', title, flags=re.IGNORECASE)
    t = re.sub(r'\s*-\s*Xem Hoạt Hình VietSub\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s*\|\s*HHPANDA\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\b(?:HHPANDA|HHpanda|Xem Phim Hoạt Hình|VietSub|Thuyết Minh|Lồng Tiếng|Xem Hoạt Hình VietSub|Xem Hoạt Hình)\b', '', t, flags=re.IGNORECASE)
    # Dọn dẹp dấu gạch ngang, gạch đứng, dấu chéo dư thừa ở đầu và cuối
    t = re.sub(r'[\s|:\\/-]+$', '', t).strip()
    t = re.sub(r'^[\s|:\\/-]+', '', t).strip()
    return t


def clean_phim_desc(desc: str) -> str:
    """Lọc sạch các cụm từ dư thừa ở đầu phần mô tả phim."""
    if not desc:
        return ""
    # Xoá "Nội dung phim", "Tóm tắt nội dung" lặp thừa ở đầu
    d = re.sub(r'^(?:Nội dung phim|Nội dung|Tóm tắt nội dung|Tóm tắt phim|Giới thiệu phim|Giới thiệu)\s*:?\s*', '', desc, flags=re.IGNORECASE)
    return d.strip()


# Playwright helpers (shared between actions.py and server.py)

async def pw_fetch(url: str, wait_ms: int = 2000):
    """Open URL with Playwright, return (page, browser, pw) after JS render.

    If launch/goto fails partway through, any Chromium process/context already
    started is closed before re-raising — otherwise a failed fetch (very common
    against flaky third-party sites) leaks an orphaned headless browser process.
    """
    from playwright.async_api import async_playwright
    pw = await async_playwright().__aenter__()
    browser = None
    try:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        page.set_default_timeout(30000)
        await page.goto(url, wait_until="networkidle")
        await asyncio.sleep(wait_ms / 1000)
        return page, browser, pw
    except Exception:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass
        try:
            await pw.__aexit__(None, None, None)
        except Exception:
            pass
        raise


async def pw_close(page, browser, pw):
    """Close Playwright resources."""
    try:
        await browser.close()
    except Exception:
        pass
    try:
        await pw.__aexit__(None, None, None)
    except Exception:
        pass


async def pw_scrape_iframe(page) -> str:
    """Extract player iframe/video src from a Playwright page."""
    return await page.evaluate("""
        () => {
            const sel = 'iframe[src*="player"], iframe[src*="embed"], iframe[src*="video"], iframe[src*="stream"]';
            const iframe = document.querySelector(sel);
            if (iframe) return iframe.src || '';
            const video = document.querySelector('video source');
            if (video) return video.src || '';
            return '';
        }
    """) or ""


async def pw_scrape_episodes(page) -> list[dict]:
    """Extract episode list from an hhpanda series page, excluding Thuyết Minh servers and TM episodes."""
    return await page.evaluate("""
        () => {
            const results = [];
            const seenUrls = new Set();
            const seenEpNumbers = new Set();
            
            // Tìm tất cả các hàng server tập phim (thường là các class chứa danh sách tập)
            const serverLists = document.querySelectorAll('.list-episode, .halim-list-eps, ul.halim-list-eps');
            
            if (serverLists.length > 0) {
                for (const listEl of serverLists) {
                    // Kiểm tra xem server này có tên là Thuyết Minh hay không
                    let isThuyetMinh = false;
                    const parent = listEl.closest('.halim-server, div[class*="server"]');
                    if (parent) {
                        const serverTitleEl = parent.querySelector('.server-name, h3, .server-title');
                        if (serverTitleEl) {
                            const name = serverTitleEl.textContent.toLowerCase();
                            if (name.includes('thuyết minh') || name.includes('tm') || name.includes('lồng tiếng')) {
                                isThuyetMinh = true;
                            }
                        }
                    }
                    
                    // Nếu là server Thuyết Minh, bỏ qua hoàn toàn các tập trong danh sách này
                    if (isThuyetMinh) {
                        continue;
                    }
                    
                    // Cào các tập của server này
                    const anchors = listEl.querySelectorAll('a[href*="/watch-"]');
                    for (const a of anchors) {
                        const href = a.href;
                        if (!href || seenUrls.has(href)) continue;
                        
                        const title = a.title || a.textContent?.trim() || '';
                        const lowerTitle = title.toLowerCase();
                        
                        // Lọc theo title
                        if (lowerTitle.includes('thuyết minh') || lowerTitle.includes(' tm') || lowerTitle.endsWith('tm')) {
                            continue;
                        }
                        
                        // Trích xuất số tập (ví dụ "Tập 147" -> "147") để lọc trùng lặp tập Vietsub
                        const epMatch = lowerTitle.match(/(?:tập|tập\\s*|ep\\s*)(\\d+)/);
                        const epNum = epMatch ? epMatch[1] : title;
                        if (seenEpNumbers.has(epNum)) {
                            continue; // Skip tập thuyết minh bị trùng số tập
                        }
                        
                        seenUrls.add(href);
                        seenEpNumbers.add(epNum);
                        results.push({
                            url: href,
                            title: title,
                        });
                    }
                }
            }
            
            // Fallback nếu không chia theo server list cụ thể được
            if (results.length === 0) {
                const items = document.querySelectorAll('a[href*="/watch-"]');
                for (const a of items) {
                    const href = a.href;
                    if (!href || seenUrls.has(href)) continue;
                    
                    const title = a.title || a.textContent?.trim() || '';
                    const lowerTitle = title.toLowerCase();
                    
                    // Kiểm tra xem thẻ a này có nằm trong container thuyết minh không bằng cách leo ngược DOM
                    let isThuyetMinhContainer = false;
                    let parent = a.parentElement;
                    for (let depth = 0; depth < 5 && parent; depth++) {
                        const className = (parent.className || '').toLowerCase();
                        const idName = (parent.id || '').toLowerCase();
                        if (className.includes('thuyết minh') || className.includes('tm') || className.includes('lồng tiếng') ||
                            idName.includes('thuyết minh') || idName.includes('tm')) {
                            isThuyetMinhContainer = true;
                            break;
                        }
                        // Thử tìm thẻ tiêu đề server nằm trong parent
                        const serverTitle = parent.querySelector('.server-name, .server-title, h3');
                        if (serverTitle && (serverTitle.textContent.toLowerCase().includes('thuyết minh') || serverTitle.textContent.toLowerCase().includes('tm'))) {
                            isThuyetMinhContainer = true;
                            break;
                        }
                        parent = parent.parentElement;
                    }
                    
                    if (isThuyetMinhContainer) {
                        continue;
                    }
                    
                    if (lowerTitle.includes('thuyết minh') || lowerTitle.includes(' tm') || lowerTitle.endsWith('tm')) {
                        continue;
                    }
                    
                    const epMatch = lowerTitle.match(/(?:tập|tập\\s*|ep\\s*)(\\d+)/);
                    const epNum = epMatch ? epMatch[1] : title;
                    if (seenEpNumbers.has(epNum)) {
                        continue;
                    }
                    
                    seenUrls.add(href);
                    seenEpNumbers.add(epNum);
                    results.push({
                        url: href,
                        title: title,
                    });
                }
            }
            return results;
        }
    """) or []


async def search_media(query: str, source: str = "auto") -> list[dict]:
    if source == "local":
        results = search_local(query)
        if results:
            return results
    return await search_youtube(query)


def _strip_noise(text: str) -> str:
    """Strip common routing keywords that LLM sometimes leaves in the query."""
    _noise = re.compile(
        r'\b(?:hhpanda|hhpada|hhpand|hpanda|phim|xem\s*phim|youtube|video|nhạc|music|bài\s*hát|nghe|mở|tìm)\b',
        re.IGNORECASE
    )
    return _noise.sub('', text).strip()


_REQUEST_WORDS = re.compile(
    r'(?<!\w)(?:tôi|mình|em|muốn|cần|giúp|hãy|bạn|cho|của|với|nha|nhé|nhá|đi|bật|phát|xem)(?!\w)',
    re.IGNORECASE,
)


def _strip_request_words(text: str) -> str:
    """Bỏ từ đệm của câu nói tự nhiên ("tôi muốn nghe … của …") trước khi xếp hạng YouTube:
    reranking chấm từng từ, nên "của" từng kéo một video drama lên trên bài hát chính chủ.
    ponytail: danh sách từ cố định; tên bài có đúng các từ này mất vài điểm khớp, yt-dlp vẫn tìm ra."""
    return " ".join(_REQUEST_WORDS.sub(" ", text).split())


def no_accent(text: str) -> str:
    """Loại bỏ dấu tiếng Việt để so khớp chuỗi không dấu."""
    text = text.lower()
    text = text.replace('\u0111', 'd')  # đ -> d
    text = unicodedata.normalize('NFKD', text)
    return "".join(c for c in text if not unicodedata.combining(c))


async def search_youtube(query: str, max_results: int = 4) -> list[dict]:
    try:
        query = _strip_request_words(_strip_noise(query)) or query
        # Tìm nhiều hơn 10 video để lọc Shorts, sau đó cắt lấy tối đa 4 video
        result = await asyncio.to_thread(_yt_search, query, max_results=12)
        # Lọc bỏ các video ngắn (Shorts) có thời lượng dưới 60 giây (giữ lại None vì Live Stream có duration là None)
        filtered = []
        for r in result:
            dur = r.get("duration")
            if dur is None or (isinstance(dur, (int, float)) and dur >= 60):
                filtered.append(r)
                
        # Thuật toán Reranking & Live Boost
        query_normalized = no_accent(query)
        query_words = [w for w in query_normalized.split() if len(w) > 1]
        
        # Nhận diện xem người dùng có đang muốn xem live stream không
        live_keywords = ["live", "truc tiep", "livestream", "streaming"]
        is_searching_live = any(lk in query_normalized for lk in live_keywords)
        
        # Danh sách từ khóa định dạng phụ dễ gây sai lệch bài gốc
        format_keywords = ["live", "remix", "cover", "karaoke", "fancam", "vietsub", "lyrics", "acoustic", "mashup", "loop", "instrumental", "remake"]
        # Danh sách từ khóa chính thức của ca sĩ
        official_keywords = ["official", "mv", "music video", "visualizer", "audio"]
        
        def get_match_score(item: dict) -> float:
            title_normalized = no_accent(item.get("title", ""))
            
            # 1. Điểm khớp từ đơn lẻ
            matches = sum(1 for w in query_words if w in title_normalized)
            
            # 2. Điểm khớp cụm từ liên tục (Phrases)
            phrase_score = 0
            for i in range(len(query_words) - 1):
                phrase2 = f"{query_words[i]} {query_words[i+1]}"
                if phrase2 in title_normalized:
                    phrase_score += 2
            for i in range(len(query_words) - 2):
                phrase3 = f"{query_words[i]} {query_words[i+1]} {query_words[i+2]}"
                if phrase3 in title_normalized:
                    phrase_score += 4
                    
            # 3. Live Boost: Ưu tiên kết quả trực tiếp nếu truy vấn yêu cầu xem live
            if is_searching_live:
                if any(lk in title_normalized for lk in live_keywords):
                    phrase_score += 5
            
            # 4. Format Penalty: Trừ điểm nếu tiêu đề chứa từ khóa định dạng mà truy vấn của user không yêu cầu
            for fk in format_keywords:
                if fk in title_normalized and fk not in query_normalized:
                    phrase_score -= 5
                    
            # 5. Official Bonus: Cộng điểm thưởng cho các ấn bản chính thức
            if any(ok in title_normalized for ok in official_keywords):
                phrase_score += 2
                
            # 6. Channel & Official Channel Boost: Ưu tiên kênh chính chủ của ca sĩ
            channel_normalized = no_accent(item.get("channel", ""))
            channel_words_matched = sum(1 for w in query_words if w in channel_normalized)
            if channel_words_matched > 0:
                phrase_score += channel_words_matched * 2
                # Thưởng thêm nếu có nhãn chính thức trong tên kênh
                if any(ok in channel_normalized for ok in ["official", "vevo", "artist", "chinh chu"]):
                    phrase_score += 5
            else:
                # Phạt kênh re-upload không khớp tên ca sĩ
                phrase_score -= 4
                    
            return matches + phrase_score

        filtered.sort(key=get_match_score, reverse=True)
        return filtered[:4]
    except Exception as e:
        log.warning(f"YouTube search failed: {e}")
        return []


def _yt_search(query: str, max_results: int = 12) -> list[dict]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-json",
        "--no-warnings",
        f"ytsearch{max_results}:{query}",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    results = []
    for line in proc.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            video_id = data.get("id")
            if not video_id:
                continue
            
            # Lọc sơ bộ nếu tiêu đề chứa Shorts hoặc shorts
            title = data.get("title", "")
            if "shorts" in title.lower():
                continue

            results.append({
                "id": video_id,
                "title": title,
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "embed_url": f"https://www.youtube.com/embed/{video_id}",
                "thumbnail": data.get("thumbnail", f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"),
                "duration": data.get("duration"),
                "channel": data.get("channel", ""),
                "source": "youtube",
            })
        except json.JSONDecodeError:
            continue
    return results


async def resolve_phim_from_slug(slug: str) -> list[dict]:
    """Try to access movie page directly by slug (e.g. 'tien-nghich' -> hhpanda.st/tien-nghich/).
    Returns list with 1 result containing 'episodes' if successful, empty list otherwise."""
    url = f"https://hhpanda.st/{slug}/"
    log.info(f"Trying direct phim URL: {url}")
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(15000)
            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=15000)
            except Exception:
                log.info(f"Direct URL timed out or failed: {url}")
                await browser.close()
                return []
            await asyncio.sleep(1.5)

            if resp and resp.status >= 400:
                log.info(f"Direct URL returned {resp.status}: {url}")
                await browser.close()
                return []

            episodes = await pw_scrape_episodes(page)
            # Cào tổng số tập dự kiến của phim từ web (thường có dạng: "Tập 147/180 [4K]" hoặc tương tự)
            total_eps_str = await page.evaluate("""() => {
                // Thử tìm ở các nơi hiển thị trạng thái tập phim
                const selectors = [
                    'span.new-ep',
                    '.halim-post-title-sub',
                    '.movie-meta .status',
                    '.episode-total',
                    'span.status',
                    '.halim-post-title-box .halim-post-title-sub'
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent.trim()) {
                        return el.textContent.trim();
                    }
                }
                return '';
            }""")
            
            total_eps = ""
            if total_eps_str:
                # Tìm định dạng phân số phổ biến ví dụ: 147/180 hoặc 12/12
                m_fraction = re.search(r'(\d+)\s*/\s*(\d+)', total_eps_str)
                if m_fraction:
                    total_eps = m_fraction.group(2) # Lấy số tổng đứng sau dấu /
                else:
                    # Thử tìm dạng "180 Tập" hoặc tương tự
                    m_num = re.search(r'(\d+)\s*(?:tập|ep)', total_eps_str.lower())
                    if m_num:
                        total_eps = m_num.group(1)

            # Nếu không tìm thấy hoặc giá trị rỗng, lấy độ dài danh sách tập làm mặc định động
            if not total_eps:
                total_eps = str(len(episodes)) if episodes else "1"

            # Ghép trạng thái tập thực tế đã lọc Vietsub / Tổng số tập (ví dụ: 147/180 hoặc 12/12)
            episode_status = f"{len(episodes)}/{total_eps}" if episodes else f"0/{total_eps}"

            title = await page.evaluate("() => document.title?.replace(' - Xem phim','').replace(' | HHpanda','').trim() || ''")
            if not title:
                title = await page.evaluate("""() => {
                    const h1 = document.querySelector('h1, h2.entry-title, .entry-title, .title');
                    return h1?.textContent?.trim() || '';
                }""")
            
            # Làm sạch chữ "Tên" bị dính ở đầu tiêu đề do cấu trúc HTML đặc thù của hhpanda (ví dụ "TênTiên Nghịch" -> "Tiên Nghịch")
            if title.startswith("Tên"):
                title = title[3:].strip()

            if not title and episodes:
                # Extract movie name from first episode URL: /watch-{slug}/tap-1-sv1.html
                ep_url = episodes[0].get("url", "")
                m = re.search(r'/watch-(.+?)/', ep_url)
                if m:
                    title = m.group(1).replace('-', ' ').title()

            # Trích xuất ảnh poster của phim từ trang chi tiết
            thumbnail = await page.evaluate("""() => {
                const img = document.querySelector('.film-poster-img, .wp-post-image, img-responsive, img[src*="uploads"]');
                return img ? img.src : '';
            }""")

            # Trích xuất thể loại và mô tả chi tiết từ trang phim
            genre = await page.evaluate("""() => {
                const genreEl = document.querySelector('.halim-cat, .genre, span[class*="cat"], .movie-genre');
                return genreEl ? genreEl.textContent.trim() : '';
            }""")

            description = await page.evaluate("""() => {
                const descEl = document.querySelector('.entry-content, .film-excerpt, .description, #halim-user-excerp-content');
                return descEl ? descEl.textContent.trim() : '';
            }""")

            clean_desc = clean_phim_desc(description)

            movie_title = clean_phim_title(title or slug.replace('-', ' ').title())
            log.info(f"Direct URL resolved: {movie_title} with {len(episodes)} episodes, thumbnail: {thumbnail}")
            await browser.close()

            return [{
                "id": url,
                "title": movie_title,
                "url": url,
                "thumbnail": thumbnail,
                "genre": genre,
                "description": clean_desc[:350],
                "source": "phim",
                "episodes": episodes,
                "slug": slug,
                "episode_status": episode_status,
            }]
    except Exception as e:
        log.debug(f"Direct phim resolution failed: {e}")
        return []


async def search_phim(query: str, max_results: int = 8) -> list[dict]:
    try:
        # Extract episode number if specified
        episode_match = re.search(r'tập\s*(\d+)', query.lower())
        episode_num = episode_match.group(1) if episode_match else ""

        # Strip noise keywords that LLM sometimes leaves in the query
        query = _strip_noise(query)

        # Strip episode number for slug resolution
        clean_query = re.sub(r'tập\s*\d+\s*', '', query).strip() or query.strip()
        
        # Step 1: Try direct URL by slug (most accurate)
        slug = slugify(clean_query)
        direct_results = await resolve_phim_from_slug(slug)
        if direct_results:
            # If specific episode requested, mark it in the result
            if episode_num:
                direct_results[0]["requested_episode"] = episode_num
            return direct_results

        log.info(f"Direct URL failed, falling back to search: {query}")

        # Step 2: Search fallback

        encoded = query.replace(" ", "+")
        url = f"https://hhpanda.st/?s={encoded}"
        log.info(f"Fetching phim: {url}")

        html = await _fetch_phim_http(url)
        items = []

        if html:
            items = _parse_phim_html(html, max_results)
            if items:
                log.info(f"Found {len(items)} phim results (HTTP)")
                return items
            log.info("HTTP fetch succeeded but no items found, trying browser...")

        log.info("Using Playwright for hhpanda...")
        items = await _fetch_phim_playwright(url, max_results)
        if items:
            log.info(f"Found {len(items)} phim results (Playwright)")
            return items

        log.warning("No phim results found")
        return []
    except Exception as e:
        log.warning(f"Phim search failed: {e}")
        return []


async def _fetch_phim_http(url: str) -> str | None:
    try:
        from scrapling.fetchers import AsyncFetcher
        resp = await AsyncFetcher.get(url, stealthy_headers=True, timeout=20000)
        html = (resp.text or "").strip()
        return html if len(html) > 500 else None
    except Exception as e:
        log.debug(f"HTTP fetch failed: {e}")
        return None


def sort_phim_by_newest_season(results: list[dict]) -> list[dict]:
    """Sắp xếp danh sách phim hoạt hình sao cho phần mới nhất (Season cao nhất) lên hàng đầu."""
    import re
    def extract_season_num(title: str) -> int:
        title_lower = title.lower()
        # Tìm các ký tự chỉ phần phim như "phần 5", "phần v", "ss5", "season 5"
        m = re.search(r'(?:phần|season|ss|p\.?)\s*(\d+)', title_lower)
        if m:
            return int(m.group(1))
        # Chuyển đổi số La Mã cơ bản nếu có (ví dụ: phần iv, phần v)
        roman_map = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5, 'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}
        for r_str, r_num in roman_map.items():
            if re.search(r'\bphần\s+' + r_str + r'\b', title_lower):
                return r_num
        return 1  # mặc định nếu không xác định được phần

    return sorted(results, key=lambda x: extract_season_num(x.get("title", "")), reverse=True)


def _parse_phim_html(html: str, max_results: int) -> list[dict]:
    """Parse hhpanda movie listing HTML (works for both HTTP and Playwright sources)."""
    import re
    from scrapling import Stealthy
    results = []
    seen = set()

    page = Stealthy(html)

    # Chọn tất cả các thẻ anchor của phim (thường có class halim-thumb)
    articles = page.css("a.halim-thumb")
    if not articles:
        articles = page.css(".halim-item-list a")
    if not articles:
        articles = page.css("article")

    for article in articles:
        href = article.attrib.get("href", "")
        title = article.attrib.get("title", "") or article.text or ""
        
        # Nếu chưa tìm thấy title, thử tìm trong các thẻ con (h2, figcaption...)
        if not title:
            h2 = article.css("h2").first
            if h2:
                title = h2.text or ""

        title = clean_phim_title(re.sub(r'\s+', ' ', title).strip())
        if not title or len(title) < 2:
            continue

        key = title.lower()[:40]
        if key in seen:
            continue
        seen.add(key)

        # Trích xuất ảnh thu nhỏ (thumbnail)
        img = article.css("img").first
        thumb = ""
        if img:
            thumb = img.attrib.get("data-src", "") or img.attrib.get("data-lazy-src", "") or img.attrib.get("src", "")

        # Trích xuất thể loại (genre)
        genre = ""
        genre_el = article.css(".halim-cat, .genre, .entry-categories, span[class*='cat']").first
        if genre_el:
            genre = re.sub(r'\s+', ' ', genre_el.text or "").strip()

        # Trích xuất mô tả ngắn
        description = ""
        desc_el = article.css(".entry-content, .halim-desc, .description, p").first
        if desc_el:
            raw_desc = re.sub(r'\s+', ' ', desc_el.text or "").strip()
            description = clean_phim_desc(raw_desc)[:350]

        # Trích xuất số tập (status / episode / label)
        episode_status = ""
        ep_el = article.css(".status, .episode, .label, span[class*='status'], span[class*='episode']").first
        if ep_el:
            episode_status = re.sub(r'\s+', ' ', ep_el.text or "").strip()

        full_url = href if href.startswith("http") else f"https://hhpanda.st{href}"
        # Tạo slug cho URL hhpanda chuẩn
        slug_match = re.search(r'hhpanda\.st/([^/?#]+)', full_url)
        slug_val = slug_match.group(1) if slug_match else ""

        results.append({
            "id": href,
            "title": title,
            "url": full_url,
            "thumbnail": thumb or "",
            "genre": genre,
            "description": description,
            "slug": slug_val,
            "source": "phim",
            "episode_status": episode_status,
        })
        if len(results) >= max_results * 2: # Lấy dư ra chút để lát sort phần mới nhất rồi mới cắt max_results
            break

    # Sắp xếp để phần mới nhất ở trên đầu
    sorted_results = sort_phim_by_newest_season(results)
    return sorted_results[:max_results]


async def _fetch_phim_playwright(url: str, max_results: int) -> list[dict]:
    """Use Playwright to get fully rendered HTML from hhpanda.st."""
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(20000)
            await page.goto(url, wait_until="networkidle")
            await asyncio.sleep(2)  # extra wait for JS rendering

            # Extract movie items via evaluate using updated selectors
            items = await page.evaluate("""
                () => {
                    const results = [];
                    const seen = new Set();
                    const anchors = Array.from(document.querySelectorAll('a.halim-thumb, .halim-item-list a, article a'));
                    
                    for (const a of anchors) {
                        const href = a.href || '';
                        if (!href) continue;
                        
                        let title = a.title || a.getAttribute('title') || '';
                        if (!title) {
                            const h2 = a.querySelector('h2, .title, figcaption');
                            if (h2) title = h2.textContent || '';
                        }
                        if (!title) title = a.textContent || '';
                        
                        title = title.replace(/\\s+/g, ' ').trim();
                        // Lọc sạch các cụm từ thừa phổ biến
                        title = title.replace(/\\s*-\\s*Xem phim/gi, '');
                        title = title.replace(/\\s*-\\s*Xem Hoạt Hình VietSub/gi, '');
                        title = title.replace(/\\s*\\|\\s*HHPANDA/gi, '');
                        title = title.replace(/\\b(?:HHPANDA|HHpanda|Xem Phim Hoạt Hình|VietSub|Thuyết Minh|Lồng Tiếng|Xem Hoạt Hình VietSub|Xem Hoạt Hình)\\b/gi, '');
                        // Dọn dấu dư thừa đầu/cuối
                        title = title.replace(/[\\s|:\\/\\/-]+$/, '').replace(/^[\\s|:\\/\\/-]+/, '').trim();
                        if (title.length < 2) continue;
                        
                        const key = title.toLowerCase().slice(0, 40);
                        if (seen.has(key)) continue;
                        seen.add(key);

                        const imgEl = a.querySelector('img');
                        let img = '';
                        if (imgEl) {
                            img = imgEl.getAttribute('data-src') || imgEl.getAttribute('data-lazy-src') || imgEl.src || '';
                        }

                        // Lấy thể loại
                        const genreEl = a.querySelector('.halim-cat, .genre, span[class*="cat"]');
                        const genre = genreEl ? genreEl.textContent.trim() : '';

                        // Lấy mô tả
                        const descEl = a.querySelector('.entry-content, .halim-desc, .description, p');
                        let description = descEl ? descEl.textContent.trim() : '';
                        // Lọc sạch 'Nội dung phim' lặp thừa
                        description = description.replace(/^(?:Nội dung phim|Nội dung|Tóm tắt nội dung|Tóm tắt phim|Giới thiệu phim|Giới thiệu)\\s*:?\\s*/i, '').trim().slice(0, 350);

                        // Lấy số tập
                        const epEl = a.querySelector('.status, .episode, .label, span[class*="status"], span[class*="episode"]');
                        const episode_status = epEl ? epEl.textContent.trim() : '';

                        // Trích slug từ URL
                        const slugMatch = href.match(/hhpanda\\.st\\/([^/?#]+)/);
                        const slug = slugMatch ? slugMatch[1] : '';

                        results.push({
                            id: href,
                            title: title,
                            url: href,
                            thumbnail: img,
                            genre: genre,
                            description: description,
                            slug: slug,
                            source: 'phim',
                            episode_status: episode_status,
                        });
                    }
                    return results;
                }
            """)
            await browser.close()
            # Sắp xếp phần mới nhất lên đầu
            sorted_items = sort_phim_by_newest_season(items)
            return sorted_items[:max_results]
    except Exception as e:
        log.warning(f"Playwright fetch failed: {e}")
        return []


def format_media_table(results: list[dict]) -> str:
    """Chuyển list kết quả search_media thành bảng Markdown có poster thumbnail.
    
    Format bảng:
    - Phim (HHPanda): poster | tên phim + thể loại + mô tả | link HHPanda
    - YouTube: thumbnail nhỏ | tên video + kênh + thời lượng | link YouTube
    """
    if not results:
        return ""

    source = results[0].get("source", "youtube")

    if source == "phim":
        rows = []
        rows.append("| Poster | Phim | Nội dung | Tập |")
        rows.append("| :---: | :--- | :--- | :---: |")
        for r in results:
            title = r.get("title", "").strip()
            thumb = r.get("thumbnail", "")
            genre = r.get("genre", "").strip()
            description = r.get("description", "").strip()
            url = r.get("url", "")
            slug = r.get("slug", "")

            # Trích xuất thông tin tập phim
            ep_status = r.get("episode_status", "").strip()
            if not ep_status:
                episodes = r.get("episodes", [])
                if episodes:
                    ep_status = f"{len(episodes)} Tập"
                else:
                    ep_status = "N/A"

            if slug:
                hhpanda_url = f"https://hhpanda.st/{slug}"
            else:
                hhpanda_url = url or ""

            # Lọc ký tự | trong alt
            alt_text = title[:20].replace("|", "-").strip()
            poster_cell = f"![{alt_text}]({thumb})" if thumb else "🎬"

            # Cột 2: Phim (chứa link)
            if hhpanda_url:
                title_link = f"**[{title}]({hhpanda_url})**"
            else:
                title_link = f"**{title}**"

            # Cột 3: Nội dung (Thể loại + Mô tả)
            content_parts = []
            if genre:
                content_parts.append(f"🎭 *{genre}*")
            if description:
                content_parts.append(description)
            content_cell = "<br/>".join(content_parts) if content_parts else "Chưa có mô tả"

            rows.append(f"| {poster_cell} | {title_link} | {content_cell} | {ep_status} |")

        return "\n".join(rows)

    else:  # youtube
        rows = []
        rows.append("| Poster | Tên bài | Nghệ sĩ | Thời Lượng |")
        rows.append("| :---: | :--- | :--- | :---: |")
        for r in results:
            title = r.get("title", "").strip()
            video_id = r.get("id", "")
            channel = r.get("channel", "").strip()
            duration = r.get("duration")
            url = r.get("url", "")

            if video_id:
                thumb_url = f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg"
            else:
                thumb_url = r.get("thumbnail", "")

            # Lọc ký tự | trong alt
            alt_text = title[:20].replace("|", "-").strip()
            poster_cell = f"![{alt_text}]({thumb_url})" if thumb_url else "▶️"

            # Dọn dẹp ngoặc vuông, ngoặc tròn rác khỏi tên bài
            clean_title = re.sub(r'\s*[\[\(](?:OFFICIAL|Official|MV|Lyrics|LỜI|Linh|Karaoke|Vietsub|Visualizer|Audio|HD|1080p|4K|Remix|Cover|Live|Video|Teaser|Performance|Music Video|Visualizer Video).*?[\]\)]', '', title, flags=re.IGNORECASE).strip()
            # Dọn dẹp các cụm từ đứng tự do hoặc sau dấu gạch đứng/ngang
            clean_title = re.sub(r'\b(?:OFFICIAL VISUALIZER|OFFICIAL MUSIC VIDEO|MUSIC VIDEO|VISUALIZER|OFFICIAL AUDIO|OFFICIAL|MV|AUDIO|LYRIC VIDEO|TEASER|PERFORMANCE)\b', '', clean_title, flags=re.IGNORECASE).strip()
            # Dọn dẹp các vệt ký tự gạch hoặc gạch đứng dư thừa ở cuối tên bài
            clean_title = re.sub(r'[\s|:-]+$', '', clean_title).strip()

            if not clean_title:
                clean_title = title

            # Cột 2: Tên bài (Chứa link)
            if url:
                title_link = f"**[{clean_title}]({url})**"
            else:
                title_link = f"**{clean_title}**"

            # Cột 3: Nghệ sĩ (Chữ sạch)
            artist_cell = channel

            # Cột 4: Thời lượng
            if duration:
                mins = int(duration) // 60
                secs = int(duration) % 60
                duration_cell = f"{mins}:{secs:02d}"
            else:
                duration_cell = "N/A"

            rows.append(f"| {poster_cell} | {title_link} | {artist_cell} | {duration_cell} |")

        return "\n".join(rows)


def search_local(query: str, max_results: int = 8) -> list[dict]:
    media_dirs = [
        Path.home() / "Videos",
        Path.home() / "Music",
        Path.home() / "Downloads",
    ]
    try:
        from engine.tools.skill_manager import get_skill_manager
        config = getattr(get_skill_manager(), "config", {})
        extra = config.get("media_dirs", [])
        if isinstance(extra, list):
            media_dirs.extend(Path(d) for d in extra)
    except Exception:
        pass

    exts = {".mp4", ".mkv", ".avi", ".mov", ".mp3", ".flac", ".wav", ".m4a", ".webm"}
    results = []
    ql = query.lower()

    for d in media_dirs:
        if not d.exists():
            continue
        try:
            for f in d.iterdir():
                if f.suffix.lower() in exts and ql in f.stem.lower():
                    results.append({
                        "id": str(f),
                        "title": f.stem,
                        "url": str(f),
                        "source": "local",
                    })
        except PermissionError:
            continue
    return results


async def execute_media_search(arguments: dict, ws=None, safe_ws_send_json=None) -> str | dict:
    """Tìm kiếm nội dung phương tiện (phim, nhạc, youtube), phân tích tập và gửi mã điều khiển phát tới client."""
    query = arguments.get("query") or arguments.get("user_text", "")
    source = arguments.get("source", "auto")
    if not query:
        return "Lỗi: Thiếu nội dung tìm kiếm."
        
    if ws and safe_ws_send_json is None:
        try:
            from server import safe_ws_send_json as _sws
            safe_ws_send_json = _sws
        except Exception:
            pass

    # Phân loại source dựa trên từ khóa trong câu lệnh thô
    if source == "auto":
        user_text_lower = query.lower()
        if any(kw in user_text_lower for kw in ["hhpanda", "hhpada", "hhpand", "hpanda", "phim", "xem phim"]):
            source = "phim"
        elif any(kw in user_text_lower for kw in ["youtube", "video", "nhạc", "nghe nhạc", "bài hát"]):
            source = "youtube"
    query = _strip_noise(query)
    from engine.tools.media_play import resolve_episode_embed, resolve_latest_embed

    results = await search_media(query, source)
    if not results:
        return f"Không tìm thấy nội dung cho '{query}'."

    # Đồng bộ nguồn thực tế tìm thấy từ phần tử đầu tiên của kết quả
    actual_source = results[0].get("source", source)

    embed_url = ""
    resolved_title = ""
    episodes = results[0].get("episodes", []) if actual_source == "phim" else []
    requested_ep = results[0].get("requested_episode", "")

    _should_play = bool(requested_ep) or bool(re.search(r'xem\s+ngay|phát\s+ngay|mở\s+ngay', query.lower()))

    if actual_source == "youtube":
        embed_url = results[0].get("embed_url", "")
        resolved_title = results[0].get("title", "")

    elif actual_source == "phim":
        _slug = results[0].get("slug", "")
        if not _slug:
            _url_clean = results[0]["url"].rstrip("/")
            _slug = _url_clean.split("/")[-1]

        if not episodes:
            try:
                _rere = await resolve_phim_from_slug(_slug)
                if _rere:
                    episodes = _rere[0].get("episodes", [])
            except Exception as _e:
                log.debug(f"Re-resolve episodes failed: {_e}")

        try:
            if requested_ep:
                embed_url, resolved_title = await resolve_episode_embed(_slug, requested_ep, results[0]['title'])
            elif _should_play:
                embed_url, resolved_title = await resolve_latest_embed(_slug, episodes, results[0]['title'])
        except Exception as _e:
            log.debug(f"Phim resolve failed: {_e}")

    lines = [f"Tìm thấy {len(results)} kết quả cho '{query}':", "", format_media_table(results)]

    if episodes and not embed_url:
        lines.append(f"\n📺 {results[0]['title']}:")
        max_show = min(20, len(episodes))
        for ep in episodes[:max_show]:
            lines.append(f"  {ep['title']}")
        if len(episodes) > max_show:
            lines.append(f"  ... và {len(episodes) - max_show} tập khác")
        lines.append("\n💡 Anh muốn xem tập nào? Nói 'xem ngay' để phát tập mới nhất.")
        
        if ws and safe_ws_send_json:
            try:
                _slug = results[0].get("slug", "")
                if not _slug:
                    _url_clean = results[0]["url"].rstrip("/")
                    _slug = _url_clean.split("/")[-1]
                    
                card_options = []
                poster = results[0].get("thumbnail", "")
                for ep in episodes[:20]:
                    card_options.append({
                        "value": ep["url"],
                        "label": ep["title"],
                        "thumbnail": poster,
                        "selected": False
                    })
                    
                await safe_ws_send_json(ws, {
                    "type": "interactive",
                    "card": {
                        "id": f"media_select_{_slug}",
                        "type": "select",
                        "title": f"Chọn tập phim: {results[0]['title']}",
                        "multiple": False,
                        "options": card_options,
                        "submitLabel": "Xem tập này"
                    }
                })
            except Exception as ws_err:
                log.warning(f"Failed to send interactive card via WebSocket: {ws_err}")

    if embed_url and resolved_title:
        lines.append(f"\n✅ ĐANG PHÁT: {resolved_title}")
        if ws and safe_ws_send_json:
            try:
                await safe_ws_send_json(ws, {
                    "type": "media_open",
                    "query": query,
                    "embed_url": embed_url,
                    "title": resolved_title,
                    "source": actual_source,
                })
            except Exception as ws_err:
                log.warning(f"Failed to send media_open via WebSocket: {ws_err}")

    text = "\n".join(lines)
    return {
        "text": text,
        "results": results,
        "query": query,
        "embed_url": embed_url,
        "title": resolved_title,
        "episodes": episodes,
    }
