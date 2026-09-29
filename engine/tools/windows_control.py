"""Điều khiển Windows cho `@control`.

Hai đường, cả hai chạy nền (không chiếm chuột/bàn phím):
- đổi trạng thái cửa sổ (phóng to/thu nhỏ/khôi phục): UIA qua pywinauto, có đọc lại để xác minh;
- mọi việc khác: cua-driver (UIA theo element_index). LLM đang chạy (Gemma/Qwen đều được) chọn từng
  bước dưới dạng JSON, chỉ dùng chữ — không cần vision, không bấm theo toạ độ.

Env (đều tuỳ chọn):
  CUA_DRIVER_PATH  đường dẫn cua-driver.exe; trống = PATH rồi %LOCALAPPDATA%\\Programs\\Cua\\cua-driver\\bin
  CUA_CONFIRM      each = xác nhận từng thao tác thay đổi máy (mặc định) | off = không hỏi
                   (nút mang nhãn Delete/Uninstall/Xóa… luôn hỏi dù off)
  CUA_MAX_STEPS    số bước tối đa mỗi lệnh (12)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from contextlib import AsyncExitStack
from typing import Any

log = logging.getLogger("jarvis.win_control")


class WindowsControl:
    """Tìm cửa sổ và đổi trạng thái của nó bằng UIA."""

    def __init__(self, desktop: Any | None = None, process_name_resolver=None) -> None:
        if desktop is None:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
        self._desktop = desktop
        self._process_name_resolver = process_name_resolver or self._process_name

    @staticmethod
    def _normalized(value: str) -> str:
        """Compare UIA text without invisible browser title characters."""
        return "".join(
            char for char in (value or "").casefold()
            if unicodedata.category(char) != "Cf"
        )

    @staticmethod
    def _process_name(window: Any) -> str:
        import psutil

        return psutil.Process(window.process_id()).name().removesuffix(".exe").casefold()

    def find_windows(
        self, query: str, *, include_hidden: bool = False
    ) -> list[Any]:
        """Find windows by process identity, optionally including minimized ones."""
        requested = self._normalized(query).strip()
        requested_process = re.sub(r"\s+", "", requested)
        process_matches = []
        title_matches = []
        for candidate in self._desktop.windows(visible_only=not include_hidden):
            if not include_hidden and not candidate.is_visible():
                continue
            title = self._normalized(candidate.window_text())
            process_name = self._normalized(
                self._process_name_resolver(candidate)
            ).removesuffix(".exe")
            if (
                process_name == requested_process
                or process_name.endswith(requested_process)
            ):
                process_matches.append(candidate)
            elif requested in title:
                title_matches.append(candidate)
        return process_matches or title_matches

    @staticmethod
    def _window_state(window: Any) -> str:
        handle = getattr(window, "handle", None)
        if handle:
            try:
                import ctypes

                user32 = ctypes.windll.user32
                if user32.IsIconic(int(handle)):
                    return "minimized"
                if user32.IsZoomed(int(handle)):
                    return "maximized"
                return "normal"
            except (AttributeError, OSError, TypeError, ValueError):
                pass
        if window.is_minimized():
            return "minimized"
        if window.is_maximized():
            return "maximized"
        if window.is_normal():
            return "normal"
        return "unknown"

    def set_window_state(self, window: Any, action: str) -> dict[str, Any]:
        """Change one resolved window state and verify the resulting UIA state."""
        operations = {
            "minimize": ("minimize", "minimized"),
            "maximize": ("maximize", "maximized"),
            "restore": ("restore", "normal"),
        }
        if action not in operations:
            raise ValueError(f"Unsupported window state action: {action}")
        method_name, expected_state = operations[action]
        before_state = WindowsControl._window_state(window)
        getattr(window, method_name)()
        state = WindowsControl._window_state(window)
        if state != expected_state:
            import time

            deadline = time.monotonic() + 1.0
            while state != expected_state and time.monotonic() < deadline:
                time.sleep(0.05)
                state = WindowsControl._window_state(window)
        if state != expected_state:
            raise ValueError(
                f"Window state verification failed: expected {expected_state}, got {state}"
            )
        return {
            "window_title": str(window.window_text()),
            "before_state": before_state,
            "state": state,
            "verified": True,
        }


_WINDOW_STATE_PATTERNS = (
    ("minimize", "thu nhỏ", r"(?:thu\s+nh(?:ỏ|o)|minimi[sz]e)"),
    ("maximize", "phóng to", r"(?:ph(?:ó|o)ng\s+(?:to|l(?:ớ|o)n)|maximi[sz]e)"),
    (
        "restore",
        "khôi phục",
        r"(?:restore\s+down|ph(?:ó|o)ng\s+nh(?:ỏ|o)|kh(?:ô|o)i\s+ph(?:ụ|u)c|restore)",
    ),
)


def parse_window_state_request(user_text: str) -> tuple[str, str] | None:
    """Parse one explicit state action and its application/window target."""
    command = re.sub(r"^\s*@control\s*", "", user_text or "", flags=re.I)
    for action, _label, pattern in _WINDOW_STATE_PATTERNS:
        match = re.search(pattern, command, flags=re.I)
        if not match:
            continue
        target = command[match.end():].strip()
        target = re.sub(
            r"^(?:(?:cửa\s+sổ|ứng\s+dụng|app)\s+)+",
            "",
            target,
            flags=re.I,
        ).strip()
        if target:
            return action, target
    return None


async def run_window_state_workflow(
    user_text: str,
    ws: Any,
    safe_ws_send_json: Any,
    *,
    automation_factory=WindowsControl,
    confirm=None,
    select_window=None,
) -> str:
    """Select, confirm, change, and verify one existing application window."""
    request = parse_window_state_request(user_text)
    if request is None:
        return "Không xác định được thao tác hoặc cửa sổ ứng dụng cần điều khiển."
    action, target = request
    action_label = next(
        label for candidate, label, _pattern in _WINDOW_STATE_PATTERNS
        if candidate == action
    )

    if confirm is None:
        from engine.main.ask_verifi import ask_user_confirmation

        async def confirm(message: str) -> bool:
            return await ask_user_confirmation(
                ws, safe_ws_send_json, "win_control", message
            )
    if select_window is None:
        from engine.main.ask_verifi import ask_user_selection

        async def select_window(
            message: str, options: list[dict[str, str]]
        ) -> str | None:
            return await ask_user_selection(
                ws, safe_ws_send_json, "win_control", message, options
            )

    automation = automation_factory()
    matches = await asyncio.to_thread(
        automation.find_windows,
        target,
        include_hidden=action == "restore",
    )
    if not matches:
        return (
            f"Không tìm thấy cửa sổ ứng dụng '{target}' đang hoạt động; "
            "tôi không tự mở thêm ứng dụng."
        )

    selected = matches[0]
    if len(matches) > 1:
        options = [
            {"id": str(index), "label": str(window.window_text())}
            for index, window in enumerate(matches)
        ]
        selected_id = await select_window(
            f"Tìm thấy nhiều cửa sổ khớp '{target}'. Chọn cửa sổ cần {action_label}.",
            options,
        )
        if selected_id is None:
            return "Đã hủy vì bạn chưa chọn cửa sổ cần điều khiển."
        try:
            selected = matches[int(selected_id)]
        except (ValueError, IndexError):
            return "Lựa chọn cửa sổ không hợp lệ; tôi chưa thực hiện thao tác."

    title = str(selected.window_text())
    if not await confirm(
        f"Tôi sẽ {action_label} cửa sổ '{title}'. Bạn có đồng ý không?"
    ):
        return f"Đã không {action_label} cửa sổ vì bạn chưa xác nhận."

    try:
        receipt = await asyncio.to_thread(
            automation.set_window_state, selected, action
        )
    except (LookupError, ValueError, AttributeError) as exc:
        return f"Không thể {action_label} cửa sổ '{title}': {exc}"
    return (
        f"Đã {action_label} và xác minh trạng thái cửa sổ "
        f"'{receipt['window_title']}'."
    )


# ---------------------------------------------------------------------------
# cua-driver
# ---------------------------------------------------------------------------

_CUA_DEFAULT_EXE = r"%LOCALAPPDATA%\Programs\Cua\cua-driver\bin\cua-driver.exe"
_CUA_MAX_ROWS = 80
_CUA_CALL_TIMEOUT = 30.0

_CLICK_ARGS = ({"pid", "window_id", "element_index"}, {"pid", "window_id", "element_index"}, True)
# tool -> (tham số được phép, tham số bắt buộc, đổi trạng thái máy?).
# Cố ý không có x/y/target/delivery_mode: chỉ chạm phần tử theo element_index (chạy nền, không chuột)
# và mọi thao tác nhập đều nhắm một tiến trình cụ thể, không bao giờ nhắm cả màn hình.
_CUA_TOOLS = {
    "list_windows": ({"on_screen_only", "pid"}, set(), False),
    "get_window_state": ({"pid", "window_id", "query"}, {"pid", "window_id"}, False),
    "scroll": ({"pid", "window_id", "element_index", "direction", "amount"}, {"pid", "direction"}, False),
    "launch_app": ({"name"}, {"name"}, True),
    "click": _CLICK_ARGS,
    "double_click": _CLICK_ARGS,
    "right_click": _CLICK_ARGS,
    "type_text": ({"pid", "window_id", "element_index", "text"}, {"pid", "text"}, True),
    "set_value": ({"pid", "window_id", "element_index", "value"}, {"pid", "value"}, True),
    "press_key": ({"pid", "window_id", "element_index", "key", "modifiers"}, {"pid", "key"}, True),
    "hotkey": ({"pid", "window_id", "element_index", "keys"}, {"pid", "keys"}, True),
    "invoke_menu": ({"pid", "window_id", "path"}, {"pid", "window_id", "path"}, True),
    # taskbar + Start/Search menu: cua-driver không thấy, đi qua pywinauto (ShellUia)
    "shell_state": ({"query"}, set(), False),
    "shell_click": ({"element_index"}, {"element_index"}, True),
    "shell_set_text": ({"element_index", "text"}, {"element_index", "text"}, True),
}
_CUA_KEYBOARD = {"type_text", "press_key", "hotkey"}
_CUA_FINISH_TOOLS = {"finish", "done", "final", "stop", "complete"}
_CUA_VERBS = {
    "launch_app": "mở ứng dụng", "click": "bấm", "double_click": "bấm đúp", "right_click": "bấm chuột phải",
    "type_text": "gõ", "set_value": "đặt giá trị", "press_key": "nhấn phím", "hotkey": "nhấn tổ hợp phím",
    "invoke_menu": "chọn menu", "shell_click": "bấm", "shell_set_text": "gõ",
}
_CUA_RISKY = re.compile(
    r"delete|remove|uninstall|format|erase|wipe|reset|shut\s*down|restart|sign\s*out|log\s*off"
    r"|xóa|xoá|gỡ|định\s+dạng|tắt\s+máy|khởi\s+động\s+lại|đăng\s+xuất",
    re.I,
)

# Nút cài đặt nằm liền sau dòng tiêu đề bản cập nhật (cùng cha, không lồng trong nhau); bản Preview không bao giờ được bấm.
_INSTALL_BUTTON = re.compile(r"install|cài\s+đặt|tải\s+xuống", re.I)
_INSTALL_ALL = re.compile(r"install\s+all|cài\s+đặt\s+tất\s+cả", re.I)
_PREVIEW_UPDATE = re.compile(r"preview\s+(?:cumulative\s+)?update|update\s+preview|xem\s+trước", re.I)

_CUA_PROMPT = """You control Windows apps through the cua-driver accessibility (UIA) API, one step at a time.
Reply with ONE JSON object and nothing else:
{"tool": "<name>", "args": {...}}  to act, or  {"finish": "<result for the user, in Vietnamese>"}  when done or impossible (finish is NOT a tool).
Start the finish text with "Lỗi:" only when the task failed or you could not verify it; if a conditional step ("if X appears, click it") has its condition unmet, just report that plainly, without "Lỗi".

Tools:
- list_windows {on_screen_only?}: windows with pid and window_id.
- launch_app {name}: open an app by name (e.g. "notepad", "msedge") or a Settings page (e.g. "ms-settings:windowsupdate"); then find its window with list_windows.
- get_window_state {pid, window_id, query?}: UI elements of one window as [element_index] role "label". query is a plain substring of the label; leave it out if unsure. Call it before any element action and again after acting to verify.
- click / double_click / right_click {pid, window_id, element_index}
- set_value {pid, window_id, element_index, value}: set a text field directly (prefer it when the element lists set_value). type_text {pid, window_id, element_index, text}: type into an element.
- press_key {pid, key: "Enter", modifiers?} / hotkey {pid, keys: ["ctrl","s"]}: keyboard input to that app (e.g. Enter to submit an address bar).
- scroll {pid, window_id, element_index, direction: up|down|left|right}
- invoke_menu {pid, window_id, path: ["File","Save"]}
- shell_state {query?}: the taskbar (Start button, pinned/running apps, system tray, clock) and the Start/Search menu when open, as [element_index] role "label". shell_click {element_index}, shell_set_text {element_index, text} act on the latest shell_state. Elements from shell_state must be acted on ONLY with shell_click / shell_set_text (never click/type_text). Only for things the user names as Start menu, taskbar or tray; to just open an app use launch_app. shell_set_text already fills the box: do not click it again. Typical Start flow: shell_state -> shell_click "Start" -> shell_state query "Search box" -> shell_set_text -> shell_state query <app name> -> shell_click the result.
Rules: never guess an element_index, read it from the latest get_window_state. Never click an install button that belongs to a Preview update. Do only what the task asks. If a window or element is missing, finish with "Lỗi: ...". Never ask the user questions."""


def cua_driver_path() -> str | None:
    for candidate in (os.getenv("CUA_DRIVER_PATH"), shutil.which("cua-driver"), os.path.expandvars(_CUA_DEFAULT_EXE)):
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


class CuaSession:
    """Một tiến trình `cua-driver mcp` cho một lệnh (khởi động ~0.2s, không cần daemon/Docker)."""

    async def __aenter__(self) -> "CuaSession":
        exe = cua_driver_path()
        if not exe:
            raise FileNotFoundError("cua-driver")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(
                stdio_client(StdioServerParameters(command=exe, args=["mcp"]))
            )
            self._session = await self._stack.enter_async_context(ClientSession(read, write))
            await self._session.initialize()
        except BaseException:
            await self._stack.aclose()
            raise
        return self

    async def __aexit__(self, *exc) -> bool:
        await self._stack.aclose()
        return False

    async def call(self, tool: str, args: dict) -> dict:
        res = await asyncio.wait_for(self._session.call_tool(tool, args), _CUA_CALL_TIMEOUT)
        text = "".join(getattr(c, "text", "") for c in res.content if getattr(c, "type", "") == "text")
        return {"is_error": bool(res.isError), "text": text, "data": res.structuredContent or {}}


_SHELL_HOSTS = {"startmenuexperiencehost.exe", "searchhost.exe"}
_SHELL_ROLES = {"Button", "ListItem", "Edit", "Hyperlink", "CheckBox", "MenuItem", "TabItem", "SplitButton",
                "ComboBox", "RadioButton"}
_shell_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shell-uia")  # UIA/COM luôn chạy trên một luồng


def _tool_result(text: str, *, error: bool = False, data: dict | None = None) -> dict:
    return {"is_error": error, "text": text, "data": data or {}}


class ShellUia:
    """Taskbar và Start/Search menu qua pywinauto (UIA), vì cua-driver không thấy hai bề mặt này.
    Chỉ dùng pattern Invoke/Toggle/Select/Value, không click_input nên không dời chuột."""

    def __init__(self, surfaces=None) -> None:
        self._surfaces = surfaces or self._live_surfaces
        self._els: list = []

    @staticmethod
    def _live_surfaces() -> list:
        import psutil
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        found = []
        tray = desktop.window(class_name="Shell_TrayWnd")
        if tray.exists(timeout=1):
            found.append(tray.wrapper_object())
        for w in desktop.windows():
            try:
                if psutil.Process(w.process_id()).name().lower() in _SHELL_HOSTS and w.rectangle().width() > 100:
                    found.append(w)
            except Exception:  # noqa: BLE001 - tiến trình vừa thoát
                continue
        return found

    async def call(self, tool: str, args: dict) -> dict:
        return await asyncio.get_running_loop().run_in_executor(_shell_pool, self._dispatch, tool, args)

    def _dispatch(self, tool: str, args: dict) -> dict:
        try:
            if tool == "shell_state":
                return self._state(str(args.get("query") or ""))
            if tool == "shell_click":
                return self._click(args["element_index"])
            if tool == "shell_set_text":
                return self._set_text(args["element_index"], str(args["text"]))
        except Exception as exc:  # noqa: BLE001 - phần tử biến mất, COM lỗi...
            return _tool_result(f"{tool}: {type(exc).__name__}: {exc}", error=True)
        return _tool_result(f"tool lạ: {tool}", error=True)

    def _state(self, query: str) -> dict:
        self._els, rows = [], []
        for surface in self._surfaces():
            for el in surface.descendants():
                info = el.element_info
                label = (info.name or "").strip() or (info.automation_id or "").strip()
                if info.control_type in _SHELL_ROLES and label:
                    rows.append({"element_index": len(self._els), "role": info.control_type, "label": label})
                    self._els.append(el)
        q = query.lower()
        shown = [r for r in rows if q in r["label"].lower()] if q else rows
        return _tool_result("", data={"elements": shown, "total_element_count": len(rows)})

    def _pick(self, index: Any):
        if not self._els:
            return None, _tool_result("Chưa có snapshot: gọi shell_state trước.", error=True)
        if not isinstance(index, int) or not 0 <= index < len(self._els):
            return None, _tool_result(f"element_index {index} không có trong shell_state mới nhất.", error=True)
        return self._els[index], None

    def _click(self, index: Any) -> dict:
        el, err = self._pick(index)
        if err:
            return err
        label = el.element_info.name or el.element_info.automation_id
        for how in ("invoke", "toggle", "select"):
            try:
                getattr(el, how)()
                return _tool_result(f"✅ {how} '{label}' (UIA, không dùng chuột)")
            except Exception:  # noqa: BLE001 - phần tử không có pattern này, thử pattern kế
                continue
        return _tool_result(f"'{label}' không hỗ trợ thao tác nền (invoke/toggle/select).", error=True)

    def _set_text(self, index: Any, text: str) -> dict:
        el, err = self._pick(index)
        if err:
            return err
        label = el.element_info.name or el.element_info.automation_id
        try:
            value = el.iface_value
        except Exception:  # noqa: BLE001 - không có ValuePattern
            value = None
        if value is None or el.element_info.control_type != "Edit":
            return _tool_result(f"'{label}' không phải ô nhập.", error=True)
        value.SetValue(text)
        return _tool_result(f"✅ đã điền '{label}' (UIA ValuePattern)")


def _confirm_mode() -> str:
    return "off" if (os.getenv("CUA_CONFIRM") or "each").strip().lower() == "off" else "each"


def _int_env(key: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(key, default)))
    except ValueError:
        return default


def _parse_action(text: str) -> dict | None:
    """Lấy object JSON đầu tiên có 'tool' hoặc 'finish' (chịu được chữ thừa và ```json)."""
    decoder = json.JSONDecoder()
    for m in re.finditer(r"\{", text or ""):
        try:
            obj, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
        if str(obj.get("tool") or "").lower() in _CUA_FINISH_TOOLS or (
            "finish" in obj and not (isinstance(obj["finish"], str) and obj["finish"].strip())
        ):
            # model nhỏ hay kết thúc kiểu {"tool":"finish","args":{"result":"…"}} hoặc {"finish":true,"result":"…"}
            if isinstance(obj.get("args"), str) and obj["args"].strip():
                return {"finish": obj["args"].strip()}
            pools = [obj.get("finish"), args, obj]
            texts = (v for pool in pools if isinstance(pool, dict) for k, v in pool.items()
                     if k not in ("tool", "args") and isinstance(v, str) and v.strip())
            return {"finish": next(texts, "")}
        if "finish" in obj or "tool" in obj:
            return obj
    return None


def _fmt_windows(data: dict) -> str:
    rows = []
    for w in data.get("windows") or []:
        title = (w.get("title") or "").strip()
        if not title or "cua-driver" in (w.get("app_name") or "").lower():
            continue
        rows.append(
            f"pid={w.get('pid')} window_id={w.get('window_id')} {w.get('app_name')} | {title[:80]}"
            + (" (minimized)" if w.get("minimized") else "")
        )
    return "\n".join(rows[:30]) or "(không có cửa sổ nào)"


def _fmt_state(data: dict) -> str:
    elements = data.get("elements") or []
    total = data.get("total_element_count") or len(elements)
    rows = []
    for e in elements[:_CUA_MAX_ROWS]:
        row = f'[{e.get("element_index")}] {e.get("role")} "{str(e.get("label") or "")[:80]}"'
        if e.get("value"):
            row += f' value="{str(e["value"])[:60]}"'
        if e.get("actions"):
            row += f' ({",".join(e["actions"])})'
        rows.append(row)
    head = f"{len(rows)}/{total} phần tử" + (" (dùng query để lọc)" if total > len(rows) else "")
    return head + "\n" + "\n".join(rows)


def _preview_install(rows: list[dict], index: Any) -> bool:
    """Nút cài đặt (trừ 'Install all') mà vài dòng ngay trước nó là tiêu đề một bản cập nhật Preview."""
    pos = next((i for i, e in enumerate(rows) if e.get("element_index") == index), None)
    if pos is None:
        return False
    label = str(rows[pos].get("label") or "")
    if not _INSTALL_BUTTON.search(label) or _INSTALL_ALL.search(label):
        return False
    return any(_PREVIEW_UPDATE.search(str(e.get("label") or "")) for e in rows[max(0, pos - 4):pos])


def _describe(tool: str, args: dict, label: str) -> str:
    what = args.get("text") if args.get("text") is not None else args.get("value")
    if what is not None:
        detail = f"{str(what)[:100]!r}" + (f" vào {label!r}" if label else "")
    else:
        detail = repr(str(label or args.get("name") or " > ".join(args.get("path") or []) or args.get("key")
                          or "+".join(args.get("keys") or []) or "")[:100])
    return f"Tôi sẽ {_CUA_VERBS.get(tool, tool)} {detail}. Bạn có đồng ý không?"


async def _cua_llm(messages: list) -> str:
    from engine.server.llm_server import call_llm

    resp = await call_llm(messages=messages, temperature=0.0, thinking=False, max_tokens=400)
    return (resp.choices[0].message.content or "").strip()


async def run_cua_task(
    task: str, ws: Any, safe_ws_send_json: Any, *,
    session_factory=None, ask_llm=None, confirm=None, max_steps: int | None = None, shell=None,
) -> str:
    """Vòng lặp: LLM chọn một tool cua-driver -> chạy -> đưa kết quả lại cho LLM. Tham số keyword để test thay thế."""
    task = (task or "").strip()
    if not task:
        return "Lỗi: Chưa có yêu cầu để điều khiển máy."
    if confirm is None:
        async def confirm(message: str) -> bool:
            if not ws or not safe_ws_send_json:
                return False  # không có giao diện để hỏi thì không tự làm
            from engine.main.ask_verifi import ask_user_confirmation

            return await ask_user_confirmation(ws, safe_ws_send_json, "win_control", message, timeout=300.0)
    try:
        async with (session_factory or CuaSession)() as cua:
            return await _cua_loop(
                task, cua, ask_llm or _cua_llm, confirm, _confirm_mode(), max_steps or _int_env("CUA_MAX_STEPS", 12),
                shell or ShellUia(),
            )
    except FileNotFoundError:
        return "Lỗi: chưa tìm thấy cua-driver. Hãy cài cua-driver hoặc đặt CUA_DRIVER_PATH trong .env."
    except Exception as exc:  # noqa: BLE001 - báo lỗi thật thay vì giả vờ đã làm
        log.warning("[CUA] lỗi: %s", exc, exc_info=True)
        return f"Lỗi: cua-driver: {exc}"


async def _cua_loop(task, cua, ask_llm, confirm, mode, steps, shell) -> str:
    messages = [{"role": "system", "content": _CUA_PROMPT}, {"role": "user", "content": f"Task: {task}"}]
    snapshots: dict[tuple, list[dict]] = {}  # (pid, window_id) -> các dòng của snapshot mới nhất
    last_window: dict[Any, Any] = {}  # pid -> window_id vừa đọc gần nhất
    snapshot_ids: dict[tuple, str] = {}  # (pid, window_id) -> snapshot_id mới nhất
    state_at: dict[str, int] = {}  # tool -> vị trí tin nhắn chứa snapshot mới nhất của tool đó
    last_mutation = None
    bad_replies = 0
    for step in range(1, steps + 1):
        reply = await ask_llm(messages)
        act = _parse_action(reply)
        if act is None:
            bad_replies += 1
            if bad_replies >= 2:
                return "Lỗi: mô hình không trả về hành động hợp lệ nên tôi dừng để tránh thao tác sai."
            messages += [{"role": "assistant", "content": reply[:300]},
                         {"role": "user", "content": "Reply with exactly one JSON object."}]
            continue
        bad_replies = 0
        if "finish" in act:
            log.info("[CUA] kết thúc: %s", " ".join(reply[:200].split()))
            return str(act["finish"]).strip() or "Lỗi: mô hình kết thúc mà không nêu kết quả cụ thể nên tôi không xác nhận là đã xong."

        tool = str(act.get("tool") or "")
        raw_args = act.get("args") if isinstance(act.get("args"), dict) else {}
        spec = _CUA_TOOLS.get(tool)
        observation, snapshot = None, False
        if spec is None:
            observation = f"Tool '{tool}' không được phép. Chỉ dùng: {', '.join(_CUA_TOOLS)}."
        else:
            allowed, required, mutating = spec
            args = {k: v for k, v in raw_args.items() if k in allowed}
            if "window_id" in allowed and "window_id" not in args and args.get("pid") in last_window:
                args["window_id"] = last_window[args["pid"]]  # pid có nhiều cửa sổ thì driver đòi window_id: lấy cửa sổ vừa đọc
            if missing := required - args.keys():
                observation = f"Thiếu tham số: {', '.join(sorted(missing))}."
            else:
                if tool == "get_window_state":
                    args["include_screenshot"] = False  # chỉ đọc chữ; không gửi ảnh cho model
                snap = (args.get("pid"), args.get("window_id"))
                rows = snapshots.get(snap, [])
                if "element_index" in args and not tool.startswith("shell_"):
                    # cua-driver đòi snapshot_id đi kèm element_index (chỉ số cũ thì lỗi): tự gắn bản mới nhất
                    if snap not in snapshot_ids:
                        observation = "Chưa có snapshot của cửa sổ này: gọi get_window_state(pid, window_id) trước khi thao tác theo element_index. (Phần tử lấy từ shell_state thì dùng shell_click / shell_set_text, không dùng tool này.)"
                    else:
                        args["snapshot_id"] = snapshot_ids[snap]
                if observation is None and mutating and _preview_install(rows, args.get("element_index")):
                    observation = "Bị chặn: nút cài đặt này thuộc bản cập nhật Preview, không được bấm. Dừng lại và báo người dùng."
                if observation is None and mutating:
                    key = (tool, json.dumps(args, sort_keys=True, default=str))
                    # ponytail: chặn cả lần bấm lặp hợp lệ liên tiếp (vd bấm "+" hai lần); model xen thao tác khác để tránh
                    if key == last_mutation:
                        return "Lỗi: mô hình lặp lại cùng một thao tác nên tôi dừng, không để nó chạy lung tung."
                    last_mutation = key
                    label = next((str(e.get("label") or "") for e in rows if e.get("element_index") == args.get("element_index")), "")
                    risky = _CUA_RISKY.search(f"{label} {' '.join(map(str, args.get('path') or []))}")
                    if (mode == "each" or risky) and not await confirm(_describe(tool, args, label)):
                        return f"Lỗi: đã dừng ở bước {step} vì bạn không xác nhận."
                if observation is None:
                    backend = shell if tool.startswith("shell_") else cua
                    result = await backend.call(tool, args)
                    if result["is_error"] and tool in _CUA_KEYBOARD and "Background delivery is not available" in result["text"]:
                        # Chromium/Electron không nhận phím nền: driver tạm đưa cửa sổ lên trước rồi trả lại; chuột không bị dời
                        result = await cua.call(tool, {**args, "delivery_mode": "foreground"})
                    if result["is_error"]:
                        observation = f"Lỗi từ công cụ: {result['text'][:300]}"
                    elif tool == "list_windows":
                        observation = _fmt_windows(result["data"])
                    elif tool in ("get_window_state", "shell_state"):
                        observation, snapshot = _fmt_state(result["data"]), True
                        snapshots[snap] = result["data"].get("elements") or []
                        if tool == "get_window_state":
                            if result["data"].get("snapshot_id"):
                                snapshot_ids[snap] = result["data"]["snapshot_id"]
                            last_window[snap[0]] = snap[1]
                    else:
                        observation = (result["text"] or "ok")[:400]
        log.info("[CUA] bước %d: %s %s -> %s", step, tool, json.dumps(raw_args, ensure_ascii=False)[:200],
                 str(observation).splitlines()[0][:160] if observation else "")
        if snapshot and tool in state_at:
            messages[state_at[tool]]["content"] = "(bản chụp cũ đã bỏ, dùng bản mới nhất)"
        messages += [{"role": "assistant", "content": reply[:400]},
                     {"role": "user", "content": f"Kết quả {tool}:\n{observation}"}]
        if snapshot:
            state_at[tool] = len(messages) - 1
    return f"Lỗi: đã chạy tối đa {steps} bước nhưng chưa xác nhận được việc hoàn thành: {task}"


async def run_win_control_workflow(user_text: str, ws: Any, safe_ws_send_json: Any) -> str:
    """Điểm vào của `@control` (actions.py gọi hàm này)."""
    if parse_window_state_request(user_text):
        # Phóng to/thu nhỏ/khôi phục: UIA làm chắc chắn, có xác minh, nhanh hơn để model tự dò.
        kwargs = {}
        if _confirm_mode() == "off":
            async def _yes(_message: str) -> bool:
                return True

            kwargs["confirm"] = _yes
        return await run_window_state_workflow(user_text, ws, safe_ws_send_json, **kwargs)
    task = re.sub(r"^\s*@control\s*", "", user_text or "", flags=re.I)
    return await run_cua_task(task, ws, safe_ws_send_json)
