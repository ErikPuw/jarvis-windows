import asyncio
import logging
import os
import subprocess
from typing import Optional

import redis.asyncio as aioredis

log = logging.getLogger("jarvis.redis")

redis_client: Optional[aioredis.Redis] = None
_redis_process: Optional[subprocess.Popen] = None


_CLI_CANDIDATES = ["redis-cli", "memurai-cli"]


async def ensure_redis_started() -> bool:
    """Start redis-server if not already running. Returns True if running."""
    global _redis_process
    for cli in _CLI_CANDIDATES:
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                [cli, "ping"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=3,
            )
            if result.returncode == 0 and "PONG" in result.stdout:
                log.info("Redis is already running (via %s)", cli)
                return True
            break
        except FileNotFoundError:
            continue
        except Exception:
            break
    else:
        log.warning("Neither redis-cli nor memurai-cli found on PATH")
        return False

    try:
        log.info("Starting redis-server...")
        _redis_process = subprocess.Popen(
            ["redis-server"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        await asyncio.sleep(1.5)
        result = await asyncio.to_thread(
            subprocess.run,
            ["redis-cli", "ping"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=3,
        )
        if result.returncode == 0 and "PONG" in result.stdout:
            log.info("redis-server started successfully")
            return True
        log.warning("redis-server started but not responding")
        return False
    except Exception as e:
        log.warning("Failed to start redis-server: %s", e)
        return False


async def connect_redis() -> bool:
    global redis_client
    await ensure_redis_started()
    redis_url = os.getenv("REDIS_URL")
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True, protocol=2, retry_on_timeout=True, socket_keepalive=True)
        await asyncio.wait_for(redis_client.ping(), timeout=5.0)
        log.info("Connected to Redis at %s", redis_url)
        return True
    except Exception as e:
        log.warning("Redis connection failed at %s: %s", redis_url, e)
        alt_url = "redis://127.0.0.1:6379/0" if "localhost" in redis_url else "redis://localhost:6379/0"
        try:
            log.info("Attempting Redis fallback to %s...", alt_url)
            redis_client = aioredis.from_url(alt_url, decode_responses=True, protocol=2, retry_on_timeout=True, socket_keepalive=True)
            await asyncio.wait_for(redis_client.ping(), timeout=3.0)
            log.info("Connected to Redis via fallback at %s", alt_url)
            return True
        except Exception as e2:
            log.error("Redis connection failed on all attempts: %s", e2)
            redis_client = None
            return False


async def worker_loop():
    """Tạm thời vô hiệu hóa worker loop do chưa xây dựng work_mode."""
    log.info("Redis worker loop is disabled (work_mode not implemented)")
    return


async def close_redis():
    """Close Redis connection and stop server."""
    global redis_client, _redis_process
    if redis_client:
        try:
            await redis_client.aclose()
        except Exception as e:
            log.warning(f"Redis close error: {e}")
        redis_client = None
    if _redis_process:
        try:
            _redis_process.terminate()
            await asyncio.sleep(0.5)
            if _redis_process.poll() is None:
                _redis_process.kill()
        except Exception as e:
            log.warning(f"Redis process terminate error: {e}")
        _redis_process = None
    log.info("Redis shut down")
