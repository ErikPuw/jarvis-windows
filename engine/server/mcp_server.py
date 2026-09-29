"""
MCP Server Configuration Manager

Handles:
1. Generate and manage mcp_config.json in config/ directory
2. Register MCP servers, tools and resources
3. NO communication with llm_server.py (isolated layer)
"""

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Optional, Any
from dataclasses import dataclass

import httpx

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("jarvis.mcp_server")

# Paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
MCP_CONFIG_FILE = CONFIG_DIR / "mcp_config.json"


@dataclass
class MCPServerConfig:
    """MCP Server configuration"""
    command: Optional[str] = None
    args: Optional[list[str]] = None
    env: Optional[dict[str, str]] = None
    enabled: bool = True
    type: str = "stdio"
    url: Optional[str] = None
    headers: Optional[dict[str, str]] = None


@dataclass
class MCPTool:
    """MCP Tool definition"""
    name: str
    description: str
    input_schema: dict
    category: str = "general"
    enabled: bool = True


@dataclass
class MCPResource:
    """MCP Resource definition"""
    uri: str
    name: str
    description: str
    mime_type: str = "text/plain"
    enabled: bool = True


class MCPServer:
    """Manages MCP configuration and servers"""

    def __init__(self):
        self.servers: dict[str, MCPServerConfig] = {}
        self.tools: dict[str, MCPTool] = {}
        self.resources: dict[str, MCPResource] = {}
        self.config: dict[str, Any] = {
            "mcpServers": {},
        }
        self._ensure_config_dir()

    def _ensure_config_dir(self):
        """Create config directory if it doesn't exist"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)


    def list_tools(self, enabled_only: bool = True) -> list[MCPTool]:
        """List all registered tools"""
        tools = list(self.tools.values())
        if enabled_only:
            tools = [t for t in tools if t.enabled]
        return tools


    def load_config(self) -> bool:
        """Load configuration from mcp_config.json"""
        if not MCP_CONFIG_FILE.exists():
            log.warning(f"MCP config file not found: {MCP_CONFIG_FILE}")
            return False

        try:
            data = json.loads(MCP_CONFIG_FILE.read_text())
            self.config = data

            # Reconstruct servers from config
            for server_name, server_data in data.get("mcpServers", {}).items():
                server = MCPServerConfig(**server_data)
                self.servers[server_name] = server

            log.info(f"MCP config loaded from {MCP_CONFIG_FILE}")
            return True
        except Exception as e:
            log.error(f"Failed to load MCP config: {e}")
            return False


    def get_stats(self) -> dict:
        """Get statistics about registered servers, tools and resources"""
        return {
            "total_servers": len(self.servers),
            "enabled_servers": sum(1 for s in self.servers.values() if s.enabled),
            "total_tools": len(self.tools),
            "enabled_tools": sum(1 for t in self.tools.values() if t.enabled),
            "total_resources": len(self.resources),
            "enabled_resources": sum(1 for r in self.resources.values() if r.enabled),
        }

# ─── MCPHub — Quản lý kết nối MCP servers ───
class MCPHub:
    """Manages multiple MCP server connections and exposes their tools to JARVIS."""

    def __init__(self):
        self.servers: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, ClientSession] = {}
        self._stop_events: dict[str, asyncio.Event] = {}
        self._lifecycle_tasks: dict[str, asyncio.Task] = {}
        self._load_config()

    def _load_config(self):
        """Load MCP configuration from config/mcp_config.json."""
        if not MCP_CONFIG_FILE.exists():
            log.info("No MCP config found at %s", MCP_CONFIG_FILE)
            return
        try:
            with open(MCP_CONFIG_FILE) as f:
                data = json.load(f)
            for name, cfg in data.get("mcpServers", {}).items():
                if cfg.get("enabled", True):
                    self.servers[name] = {
                        "command": cfg.get("command"),
                        "args": cfg.get("args", []),
                        "env": {**os.environ, **cfg.get("env", {})},
                        "status": "disconnected",
                        "type": cfg.get("type", "stdio"),
                        "url": cfg.get("url"),
                        "headers": cfg.get("headers") or {},
                    }
            log.info("Loaded %d MCP servers from config", len(self.servers))
        except Exception as e:
            log.error("Failed to load MCP config: %s", e)

    def get_stats(self) -> dict:
        """Return connection statistics."""
        total = len(self.servers)
        connected = sum(1 for s in self.servers.values() if s["status"] == "connected")
        return {
            "total_servers": total,
            "connected": connected,
            "disconnected": total - connected,
            "servers": {k: v["status"] for k, v in self.servers.items()},
        }


    async def connect_server(self, name: str) -> bool:
        """Connect to a registered MCP server."""
        if name not in self.servers:
            log.error("MCP server '%s' not registered", name)
            return False

        if name in self._lifecycle_tasks and not self._lifecycle_tasks[name].done():
            log.warning("MCP server '%s' already connected or connecting", name)
            return True

        config = self.servers[name]
        server_type = config.get("type", "stdio")

        stop_event = asyncio.Event()
        self._stop_events[name] = stop_event

        connected_future = asyncio.get_running_loop().create_future()

        if server_type == "sse":
            url = config.get("url")
            if not url:
                log.error("MCP server '%s' is type '%s' but lacks 'url'", name, server_type)
                return False
            task = asyncio.create_task(self._run_server_sse(name, url, connected_future, stop_event, config.get("headers") or {}))
        elif server_type in ("remote", "http", "streamable-http"):
            url = config.get("url")
            if not url:
                log.error("MCP server '%s' is type '%s' but lacks 'url'", name, server_type)
                return False
            task = asyncio.create_task(self._run_server_streamable_http(name, url, connected_future, stop_event, config.get("headers") or {}))
        else:
            params = StdioServerParameters(
                command=config["command"],
                args=config["args"],
                env=config["env"],
            )
            task = asyncio.create_task(self._run_server(name, params, connected_future, stop_event))
            
        self._lifecycle_tasks[name] = task

        try:
            return await asyncio.wait_for(connected_future, timeout=60)
        except asyncio.TimeoutError:
            log.warning("Connection to '%s' timed out (>60s), retrying in background", name)
            return False
        except Exception as e:
            log.error("Connection to '%s' failed: %s", name, e)
            config["status"] = "failed"
            return False

    async def _run_server_streamable_http(self, name: str, url: str, connected_future: asyncio.Future, stop_event: asyncio.Event, headers: dict[str, str] = None):
        """Background task to run the server lifecycle via Streamable HTTP with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():
            if attempts >= max_retries:
                log.error("MCP server '%s' (Streamable HTTP) failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                http_client = httpx.AsyncClient(headers=headers or {})
                try:
                    async with streamable_http_client(url, http_client=http_client) as (read, write, _):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            self.sessions[name] = session
                            self.servers[name]["status"] = "connected"
                            log.info("Connected to MCP server '%s' (Streamable HTTP) successfully", name)

                            if not connected_future.done():
                                connected_future.set_result(True)

                            retry_delay = 5
                            attempts = 0
                            await stop_event.wait()
                            break
                finally:
                    await http_client.aclose()

            except asyncio.CancelledError:
                log.info("MCP server '%s' (Streamable HTTP) cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' (Streamable HTTP) error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' (Streamable HTTP) in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def _run_server_sse(self, name: str, url: str, connected_future: asyncio.Future, stop_event: asyncio.Event, headers: dict[str, str] = None):
        """Background task to run the server lifecycle via SSE with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():
            if attempts >= max_retries:
                log.error("MCP server '%s' (SSE) failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                async with sse_client(url, headers=headers or {}) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.sessions[name] = session
                        self.servers[name]["status"] = "connected"
                        log.info("Connected to MCP server '%s' (SSE) successfully", name)

                        if not connected_future.done():
                            connected_future.set_result(True)

                        retry_delay = 5
                        attempts = 0
                        await stop_event.wait()
                        break

            except asyncio.CancelledError:
                log.info("MCP server '%s' (SSE) cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' (SSE) error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' (SSE) in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def _run_server(self, name: str, params: StdioServerParameters, connected_future: asyncio.Future, stop_event: asyncio.Event):
        """Background task to run the server lifecycle with auto-reconnect."""
        retry_delay = 5
        max_delay = 60
        max_retries = 5
        attempts = 0

        while not stop_event.is_set():

            if attempts >= max_retries:
                log.error("MCP server '%s' failed after %d attempts", name, max_retries)
                self.servers[name]["status"] = "failed_permanently"
                break

            try:
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        self.sessions[name] = session
                        self.servers[name]["status"] = "connected"
                        log.info("Connected to MCP server '%s' successfully", name)

                        if not connected_future.done():
                            connected_future.set_result(True)

                        retry_delay = 5
                        attempts = 0
                        await stop_event.wait()
                        break

            except asyncio.CancelledError:
                log.info("MCP server '%s' cancelled", name)
                break
            except Exception as e:
                attempts += 1
                self.servers[name]["status"] = "failed"
                log.error("MCP server '%s' error: %s", name, e)

                if stop_event.is_set():
                    break

                log.info("Retrying '%s' in %ds (attempt %d/%d)", name, retry_delay, attempts, max_retries)
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=retry_delay)
                    break
                except asyncio.TimeoutError:
                    retry_delay = min(retry_delay * 2, max_delay)
            finally:
                if name in self.sessions:
                    del self.sessions[name]
                if not stop_event.is_set():
                    self.servers[name]["status"] = "reconnecting"
                else:
                    self.servers[name]["status"] = "disconnected"

        if not connected_future.done():
            connected_future.set_result(False)

    async def connect_all(self) -> bool:
        """Connect to all enabled servers."""
        tasks = [self.connect_server(name) for name in self.servers]
        if not tasks:
            return True
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return all(r is True for r in results)

    async def list_all_tools(self) -> dict[str, list[Any]]:
        """List tools from all connected servers."""
        all_tools = {}
        for name, session in self.sessions.items():
            try:
                tools_result = await session.list_tools()
                all_tools[name] = [
                    {"name": t.name, "description": t.description, "inputSchema": t.inputSchema}
                    for t in tools_result.tools
                ]
            except Exception as e:
                log.error("Failed to list tools from '%s': %s", name, e)
        return all_tools


    async def call_tool(
        self, server_name: str, tool_name: str, arguments: dict[str, Any] = None, timeout: float = 60.0
    ) -> Any:
        """Call a tool on a specific MCP server.

        Bounded by `timeout` — a hung MCP stdio/HTTP server used to stall
        whichever user request invoked it indefinitely, with no fallback.
        """
        if server_name not in self.sessions:
            raise ValueError(f"Server '{server_name}' not connected")
        session = self.sessions[server_name]
        try:
            result = await asyncio.wait_for(session.call_tool(tool_name, arguments or {}), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError(
                f"MCP tool '{tool_name}' on server '{server_name}' timed out after {timeout}s"
            ) from exc
        return result

    async def shutdown(self):
        """Close all sessions."""
        for name, event in self._stop_events.items():
            event.set()
        if self._lifecycle_tasks:
            await asyncio.gather(*self._lifecycle_tasks.values(), return_exceptions=True)
        self.sessions.clear()
        self._stop_events.clear()
        self._lifecycle_tasks.clear()


# ─── Globals ───

_mcp_server: Optional[MCPServer] = None
_hub: Optional[MCPHub] = None


def get_mcp_server() -> MCPServer:
    """Get or create the global MCP server instance"""
    global _mcp_server
    if _mcp_server is None:
        _mcp_server = MCPServer()
    return _mcp_server


def initialize_mcp() -> MCPServer:
    """Initialize MCP server and load existing config"""
    server = get_mcp_server()
    server.load_config()
    return server


def get_mcp_hub() -> MCPHub:
    """Get or create the global MCPHub instance"""
    global _hub
    if _hub is None:
        _hub = MCPHub()
    return _hub


