"""Media playback resolution — resolve iframe embed URLs for movies/episodes."""

import asyncio
import logging

log = logging.getLogger("jarvis.media_play")


async def resolve_episode_embed(slug: str, episode_num: str, movie_title: str = "") -> tuple[str, str]:
    """Resolve iframe embed URL for a specific episode.
    Returns (embed_url, display_title).
    """
    from engine.tools.media_search import pw_fetch, pw_close, pw_scrape_iframe
    watch_url = f"https://hhpanda.st/watch-{slug}/tap-{episode_num}-sv1.html"
    log.info(f"Resolving episode embed: {watch_url}")
    page = browser = pw = None
    try:
        page, browser, pw = await pw_fetch(watch_url)
        embed_url = await pw_scrape_iframe(page)
        display_title = f"{movie_title} - Tập {episode_num}" if movie_title else f"Tập {episode_num}"
        return embed_url, display_title
    except Exception as e:
        log.debug(f"Resolve episode {episode_num} failed: {e}")
        return "", ""
    finally:
        if browser is not None:
            await pw_close(page, browser, pw)


async def resolve_latest_embed(slug: str, episodes: list[dict], movie_title: str = "") -> tuple[str, str]:
    """Resolve iframe embed URL for the latest episode.
    If episodes list is provided, uses the first (latest) entry.
    If empty, scrapes the movie page to find episodes.
    Returns (embed_url, display_title).
    """
    if episodes:
        from engine.tools.media_search import pw_fetch, pw_close, pw_scrape_iframe
        watch_url = episodes[0]["url"]
        ep_title = episodes[0].get("title", "")
        log.info(f"Resolving latest episode embed: {watch_url}")
        page = browser = pw = None
        try:
            page, browser, pw = await pw_fetch(watch_url)
            embed_url = await pw_scrape_iframe(page)
            return embed_url, f"{movie_title} - {ep_title}" if movie_title else ep_title
        except Exception as e:
            log.debug(f"Resolve latest episode failed: {e}")
            return "", ""
        finally:
            if browser is not None:
                await pw_close(page, browser, pw)

    from engine.tools.media_search import pw_fetch, pw_close, pw_scrape_episodes, pw_scrape_iframe
    movie_url = f"https://hhpanda.st/{slug}/"
    log.info(f"No episodes given, scraping movie page: {movie_url}")
    page = browser = pw = None
    try:
        page, browser, pw = await pw_fetch(movie_url)
        eps = await pw_scrape_episodes(page)
        if eps:
            watch_url = eps[0]["url"]
            await page.goto(watch_url, wait_until="networkidle")
            await asyncio.sleep(1.2)
            embed_url = await pw_scrape_iframe(page)
            ep_title = eps[0].get("title", "")
            return embed_url, f"{movie_title} - {ep_title}" if movie_title else ep_title
    except Exception as e:
        log.debug(f"Resolve latest from scrape failed: {e}")
    finally:
        if browser is not None:
            await pw_close(page, browser, pw)
    return "", ""
