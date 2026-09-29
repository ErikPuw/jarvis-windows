"""Read-only New Outlook access through Windows UI Automation."""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta
from pathlib import Path
import re
import time
from typing import Any, Callable


_OUTLOOK_APP_ID = (
    "Microsoft.OutlookForWindows_8wekyb3d8bbwe!"
    "Microsoft.OutlookforWindows"
)
_OUTLOOK_PROCESSES = {"olk", "outlookforwindows"}
_FILTER_AUTOMATION_ID = "mailListFilterMenu"
_ALL_FILTER_BUTTON_NAMES = {"bộ lọc", "filter"}
_CLEAR_FILTER_NAMES = {"xóa bộ lọc", "clear filter"}
_CALENDAR_NAVIGATION_ID = "8cbeb86f-83e1-43b5-aaba-cd3514322f0b"
_MAIL_NAVIGATION_ID = "ddea774c-382b-47d7-aab5-adc2139a802b"
_CALENDAR_VIEW_ID = "2530"
_DAY_VIEW_NAMES = {"ngày", "day"}


def _window_handle_exists(handle: int) -> bool:
    user32 = ctypes.windll.user32
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    return bool(user32.IsWindow(handle))


@dataclass(frozen=True)
class CalendarEvent:
    starts_at: datetime
    title: str
    ends_at: datetime | None = None
    calendar_name: str = ""
    all_day: bool = False


def _vietnamese_clock(value: str, period: str) -> tuple[int, int]:
    hour_text, minute_text = value.split(":", 1)
    hour = int(hour_text) % 12
    if period.casefold() == "ch":
        hour += 12
    return hour, int(minute_text)


def parse_outlook_calendar_event(text: str) -> CalendarEvent:
    normalized = " ".join(str(text or "").split())
    date_pattern = (
        r"[^,]+,\s*Tháng\s+(?P<month>\d{1,2})\s+"
        r"(?P<day>\d{1,2}),\s*(?P<year>\d{4})"
    )
    timed = re.fullmatch(
        r"(?P<title>.+?),\s*"
        r"(?P<start>\d{1,2}:\d{2})\s*(?P<start_period>SA|CH)"
        r"\s+đến\s+"
        r"(?P<end>\d{1,2}:\d{2})\s*(?P<end_period>SA|CH),\s*"
        + date_pattern
        + r"(?:,\s*.*)?",
        normalized,
        flags=re.IGNORECASE,
    )
    if timed:
        values = timed.groupdict()
        start_hour, start_minute = _vietnamese_clock(
            values["start"], values["start_period"]
        )
        end_hour, end_minute = _vietnamese_clock(
            values["end"], values["end_period"]
        )
        starts_at = datetime(
            int(values["year"]),
            int(values["month"]),
            int(values["day"]),
            start_hour,
            start_minute,
        )
        ends_at = datetime(
            starts_at.year,
            starts_at.month,
            starts_at.day,
            end_hour,
            end_minute,
        )
        if ends_at <= starts_at:
            ends_at += timedelta(days=1)
        return CalendarEvent(
            starts_at=starts_at,
            ends_at=ends_at,
            title=values["title"].strip(),
        )

    all_day = re.fullmatch(
        r"(?P<title>.+?),\s*Cả ngày,\s*"
        + date_pattern
        + r"(?:,\s*.*)?",
        normalized,
        flags=re.IGNORECASE,
    )
    if all_day:
        values = all_day.groupdict()
        return CalendarEvent(
            starts_at=datetime(
                int(values["year"]),
                int(values["month"]),
                int(values["day"]),
            ),
            title=values["title"].strip(),
            all_day=True,
        )
    raise ValueError("Unsupported Outlook calendar event text")


def select_calendar_events(
    events: list[CalendarEvent],
    *,
    today: date,
    limit: int = 10,
) -> list[CalendarEvent]:
    start = datetime.combine(today, datetime_time.min)
    end = start + timedelta(days=7)
    selected = [
        event for event in events
        if start <= event.starts_at < end
    ]
    selected.sort(key=lambda event: event.starts_at)
    return selected[:max(1, min(int(limit), 10))]


def _process_name(window: Any) -> str:
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(0x1000, False, window.process_id())
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buffer))
        if not kernel32.QueryFullProcessImageNameW(
            handle, 0, buffer, ctypes.byref(size)
        ):
            return ""
        return Path(buffer.value).stem.casefold()
    finally:
        kernel32.CloseHandle(handle)


class NewOutlookAutomation:
    def __init__(
        self,
        *,
        desktop: Any | None = None,
        process_name_resolver: Callable[[Any], str] | None = None,
        send_keys: Callable[[str], Any] | None = None,
        window_handle_exists: Callable[[int], bool] | None = None,
        sleeper: Callable[[float], Any] = time.sleep,
    ) -> None:
        if desktop is None:
            from pywinauto import Desktop

            desktop = Desktop(backend="uia")
        self._desktop = desktop
        self._process_name = process_name_resolver or _process_name
        self._send_keys = send_keys
        self._window_handle_exists = (
            window_handle_exists or _window_handle_exists
        )
        self._sleep = sleeper

    @staticmethod
    def _filter_buttons(window: Any) -> list[Any]:
        return [
            control
            for control in window.descendants()
            if str(control.automation_id() or "") == _FILTER_AUTOMATION_ID
        ]


    def find_mail_window(self) -> Any:
        matches = []
        for window in self._desktop.windows(visible_only=True):
            process_name = (
                self._process_name(window)
                .casefold()
                .removesuffix(".exe")
            )
            if process_name not in _OUTLOOK_PROCESSES:
                continue
            if not window.is_visible() or not window.is_enabled():
                continue
            if len(self._filter_buttons(window)) == 1:
                matches.append(window)
        if len(matches) != 1:
            raise LookupError(
                f"Expected one New Outlook mail window, got {len(matches)}"
            )
        return matches[0]

    def find_outlook_window(self) -> Any:
        matches = []
        for window in self._desktop.windows(visible_only=True):
            process_name = (
                self._process_name(window)
                .casefold()
                .removesuffix(".exe")
            )
            if process_name not in _OUTLOOK_PROCESSES:
                continue
            if not window.is_visible() or not window.is_enabled():
                continue
            navigation = [
                control
                for control in window.descendants()
                if str(control.automation_id() or "")
                == _CALENDAR_NAVIGATION_ID
            ]
            if len(navigation) == 1:
                matches.append(window)
        if len(matches) != 1:
            raise LookupError(
                f"Expected one New Outlook window, got {len(matches)}"
            )
        return matches[0]

    @staticmethod
    def detect_active_module(window: Any) -> str:
        filter_buttons = NewOutlookAutomation._filter_buttons(window)
        if len(filter_buttons) == 1:
            return "mail"
        calendar_views = [
            control
            for control in window.descendants()
            if str(control.automation_id() or "") == _CALENDAR_VIEW_ID
        ]
        if len(calendar_views) == 1:
            return "calendar"
        raise LookupError("Could not determine active Outlook module")

    @staticmethod
    def _controls_by_automation_id(
        window: Any, automation_id: str
    ) -> list[Any]:
        return [
            control
            for control in window.descendants()
            if str(control.automation_id() or "") == automation_id
        ]

    def open_calendar_module(self, window: Any) -> None:
        if self.detect_active_module(window) == "calendar":
            return
        buttons = self._controls_by_automation_id(
            window, _CALENDAR_NAVIGATION_ID
        )
        if len(buttons) != 1:
            raise LookupError(
                "Calendar navigation was not unique: "
                f"{len(buttons)} candidates"
            )
        buttons[0].click_input()
        for _attempt in range(50):
            try:
                if self.detect_active_module(window) == "calendar":
                    return
            except LookupError:
                pass
            self._sleep(0.1)
        raise RuntimeError("Calendar module was not verified")

    def _calendar_view_name(self, window: Any) -> str:
        buttons = self._controls_by_automation_id(
            window, _CALENDAR_VIEW_ID
        )
        if len(buttons) != 1:
            raise LookupError(
                "Calendar view button was not unique: "
                f"{len(buttons)} candidates"
            )
        return str(buttons[0].window_text() or "").strip()

    def _visible_named_controls(
        self, names: set[str], control_type: str
    ) -> list[Any]:
        return [
            control
            for top_window in self._desktop.windows(visible_only=True)
            for control in [top_window, *top_window.descendants()]
            if str(control.element_info.control_type or "")
            == control_type
            and str(
                control.window_text() or ""
            ).strip().casefold() in names
        ]

    def set_calendar_day_view(self, window: Any) -> str:
        original_view = self._calendar_view_name(window)
        if original_view.casefold() in _DAY_VIEW_NAMES:
            return original_view
        view_buttons = self._controls_by_automation_id(
            window, _CALENDAR_VIEW_ID
        )
        view_buttons[0].click_input()
        self._sleep(0.5)
        day_items = self._visible_named_controls(
            _DAY_VIEW_NAMES, "MenuItem"
        )
        if len(day_items) != 1:
            raise LookupError(
                f"Day view was not unique: {len(day_items)} candidates"
            )
        day_items[0].click_input()
        for _attempt in range(50):
            if (
                self._calendar_view_name(window).casefold()
                in _DAY_VIEW_NAMES
            ):
                return original_view
            self._sleep(0.1)
        raise RuntimeError("Calendar day view was not verified")

    def restore_calendar_view(
        self, window: Any, original_view: str
    ) -> bool:
        if (
            self._calendar_view_name(window).casefold()
            == original_view.casefold()
        ):
            return True
        view_buttons = self._controls_by_automation_id(
            window, _CALENDAR_VIEW_ID
        )
        view_buttons[0].click_input()
        self._sleep(0.5)
        control_type = (
            "MenuItem"
            if original_view.casefold() in _DAY_VIEW_NAMES
            else "RadioButton"
        )
        original_items = self._visible_named_controls(
            {original_view.casefold()}, control_type
        )
        if len(original_items) != 1:
            return False
        if control_type == "RadioButton":
            original_items[0].select()
        else:
            original_items[0].click_input()
        for _attempt in range(50):
            if (
                self._calendar_view_name(window).casefold()
                == original_view.casefold()
            ):
                return True
            self._sleep(0.1)
        return False

    def restore_module(
        self, window: Any, original_module: str
    ) -> bool:
        try:
            if self.detect_active_module(window) == original_module:
                return True
        except LookupError:
            pass
        if original_module != "mail":
            return False
        buttons = self._controls_by_automation_id(
            window, _MAIL_NAVIGATION_ID
        )
        if len(buttons) != 1:
            return False
        buttons[0].click_input()
        for _attempt in range(50):
            try:
                if self.detect_active_module(window) == "mail":
                    return True
            except LookupError:
                pass
            self._sleep(0.1)
        return False

    def read_calendar_events(
        self, window: Any, limit: int = 10
    ) -> list[CalendarEvent]:
        original_module = self.detect_active_module(window)
        self.open_calendar_module(window)
        original_view = self._calendar_view_name(window)
        try:
            self.set_calendar_day_view(window)
            events = self.collect_seven_day_events(window)
            return events[:max(1, min(int(limit), 10))]
        finally:
            view_restored = self.restore_calendar_view(
                window, original_view
            )
            module_restored = self.restore_module(
                window, original_module
            )
            if not view_restored or not module_restored:
                raise RuntimeError(
                    "Outlook Calendar state was not restored"
                )

    def ensure_all_filter(self, window: Any) -> None:
        buttons = self._filter_buttons(window)
        if len(buttons) != 1:
            raise LookupError(
                f"Expected one Outlook filter button, got {len(buttons)}"
            )
        current_name = str(
            buttons[0].window_text() or ""
        ).strip().casefold()
        if current_name in _ALL_FILTER_BUTTON_NAMES:
            return

        clear_buttons = [
            control
            for control in window.descendants()
            if str(control.element_info.control_type or "") == "Button"
            and str(
                control.window_text() or ""
            ).strip().casefold() in _CLEAR_FILTER_NAMES
        ]
        if len(clear_buttons) != 1:
            raise RuntimeError(
                "Outlook is filtered but no unique clear-filter button "
                "was found"
            )
        clear_buttons[0].click_input()
        for _attempt in range(50):
            current_buttons = self._filter_buttons(window)
            if (
                len(current_buttons) == 1
                and str(
                    current_buttons[0].window_text() or ""
                ).strip().casefold() in _ALL_FILTER_BUTTON_NAMES
            ):
                return
            self._sleep(0.1)
        raise RuntimeError("Outlook all-mail filter was not verified")


    @staticmethod
    def read_unread_rows(window: Any, max_results: int) -> list[str]:
        rows = [
            *window.descendants(control_type="ListItem"),
            *window.descendants(control_type="DataItem"),
        ]
        results = []
        for row in rows:
            if not str(row.automation_id() or ""):
                continue
            text = " ".join(str(row.window_text() or "").split())
            if text:
                results.append(text[:500])
            if len(results) >= max_results:
                break
        return results

    def collect_seven_day_events(
        self, window: Any
    ) -> list[CalendarEvent]:
        events = []
        try:
            for day_index in range(7):
                controls = window.descendants()
                status_controls = [
                    control
                    for control in controls
                    if "đã tải" in str(
                        control.window_text() or ""
                    ).casefold()
                ]
                if len(status_controls) != 1:
                    raise RuntimeError(
                        "Calendar day load status was not unique"
                    )
                for control in controls:
                    if str(
                        control.element_info.control_type or ""
                    ) != "Button":
                        continue
                    try:
                        event = parse_outlook_calendar_event(
                            str(control.window_text() or "")
                        )
                    except ValueError:
                        continue
                    events.append(event)
                if day_index == 6:
                    continue
                next_buttons = [
                    control
                    for control in controls
                    if str(
                        control.element_info.control_type or ""
                    ) == "Button"
                    and str(
                        control.window_text() or ""
                    ).strip().casefold().startswith((
                        "đi đến ngày tiếp theo",
                        "go to next day",
                    ))
                ]
                if len(next_buttons) != 1:
                    raise LookupError(
                        "Expected one Calendar next-day button, got "
                        f"{len(next_buttons)}"
                    )
                next_buttons[0].click_input()
                self._sleep(0.7)
        finally:
            today_buttons = [
                control
                for control in window.descendants()
                if str(
                    control.element_info.control_type or ""
                ) == "Button"
                and str(
                    control.window_text() or ""
                ).strip().casefold().startswith((
                    "đi đến hôm nay",
                    "go to today",
                ))
            ]
            if len(today_buttons) != 1:
                raise LookupError(
                    "Expected one Calendar today button, got "
                    f"{len(today_buttons)}"
                )
            today_buttons[0].click_input()
            self._sleep(0.7)
        return events

    def close_window_and_verify(
        self, window: Any, timeout: float = 5.0
    ) -> bool:
        handle = int(getattr(window, "handle", 0) or 0)
        window.close()
        if not handle:
            return False
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self._window_handle_exists(handle):
                return True
            self._sleep(0.1)
        return not self._window_handle_exists(handle)


async def _open_new_outlook() -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "explorer.exe",
            f"shell:AppsFolder\\{_OUTLOOK_APP_ID}",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate()
        return True
    except (OSError, RuntimeError):
        return False


def _format_unread_rows(rows: list[str]) -> str:
    if not rows:
        return "Không tìm thấy email gần đây trong New Outlook."
    lines = ["Các email gần nhất trong New Outlook:"]
    lines.extend(f"{index}. {row}" for index, row in enumerate(rows, 1))
    return "\n".join(lines)


async def check_unread_mail(
    *,
    ws: Any,
    safe_ws_send_json: Any,
    max_results: int = 10,
    automation_factory: Callable[[], Any] | None = None,
    open_outlook: Callable[[], Any] | None = None,
    confirm_close: Callable[[str], Any] | None = None,
    sleeper: Callable[[float], Any] = asyncio.sleep,
) -> str:
    if automation_factory is None:
        automation_factory = NewOutlookAutomation
    if confirm_close is None:
        from engine.main.ask_verifi import ask_user_confirmation

        async def confirm_close(message: str) -> bool:
            return await ask_user_confirmation(
                ws, safe_ws_send_json, "email", message, timeout=300.0
            )

    automation = automation_factory()
    try:
        window = await asyncio.to_thread(automation.find_mail_window)
    except LookupError:
        if open_outlook is None:
            open_outlook = _open_new_outlook
        opened = await open_outlook()
        if opened is False:
            return "Không thể mở New Outlook."
        window = None
        for _attempt in range(10):
            await sleeper(1)
            try:
                window = await asyncio.to_thread(automation.find_mail_window)
                break
            except LookupError:
                continue
        if window is None:
            return "Đã mở New Outlook nhưng không tìm thấy cửa sổ Thư."

    limit = max(1, min(int(max_results), 10))
    last_filter_error = None
    for _attempt in range(10):
        try:
            await asyncio.to_thread(
                automation.ensure_all_filter, window
            )
            break
        except LookupError as exc:
            last_filter_error = exc
            await sleeper(0.5)
            try:
                window = await asyncio.to_thread(
                    automation.find_mail_window
                )
            except LookupError:
                continue
    else:
        raise last_filter_error or LookupError(
            "Outlook mail controls did not become ready"
        )
    rows = await asyncio.to_thread(
        automation.read_unread_rows, window, limit
    )
    report = _format_unread_rows(rows)

    should_close = await confirm_close(
        "Tôi đã tổng hợp xong, bạn có đồng ý để tắt Outlook? Hủy để giữ lại."
    )
    if not should_close:
        return f"{report}"

    closed = await asyncio.to_thread(
        automation.close_window_and_verify, window
    )
    if closed:
        return f"{report}"
    return (
        f"{report}"
    )


def _format_calendar_events(events: list[CalendarEvent]) -> str:
    if not events:
        return (
            "Không có lịch hẹn, ngày lễ hoặc sinh nhật trong 7 ngày tới."
        )

    lines = ["Lịch trong 7 ngày tới:"]
    for event in events:
        day = event.starts_at.strftime("%d/%m/%Y")
        if event.all_day:
            schedule = f"{day} Cả ngày"
        elif event.ends_at is not None:
            schedule = (
                f"{day} {event.starts_at:%H:%M}–{event.ends_at:%H:%M}"
            )
        else:
            schedule = f"{day} {event.starts_at:%H:%M}"
        suffix = (
            f" [{event.calendar_name}]" if event.calendar_name else ""
        )
        lines.append(f"- {schedule} — {event.title}{suffix}")
    return "\n".join(lines)


async def check_calendar(
    *,
    ws: Any,
    safe_ws_send_json: Any,
    max_results: int = 10,
    automation_factory: Callable[[], Any] | None = None,
    open_outlook: Callable[[], Any] | None = None,
    confirm_close: Callable[[str], Any] | None = None,
    today_factory: Callable[[], date] = date.today,
    sleeper: Callable[[float], Any] = asyncio.sleep,
) -> str:
    if automation_factory is None:
        automation_factory = NewOutlookAutomation
    if confirm_close is None:
        from engine.main.ask_verifi import ask_user_confirmation

        async def confirm_close(message: str) -> bool:
            return await ask_user_confirmation(
                ws, safe_ws_send_json, "email", message, timeout=300.0
            )

    automation = automation_factory()
    try:
        window = await asyncio.to_thread(
            automation.find_outlook_window
        )
    except LookupError:
        if open_outlook is None:
            open_outlook = _open_new_outlook
        opened = await open_outlook()
        if opened is False:
            return "Không thể mở New Outlook."
        window = None
        for _attempt in range(10):
            await sleeper(1)
            try:
                window = await asyncio.to_thread(
                    automation.find_outlook_window
                )
                break
            except LookupError:
                continue
        if window is None:
            return "Đã mở New Outlook nhưng không tìm thấy cửa sổ."

    limit = max(1, min(int(max_results), 10))
    events = await asyncio.to_thread(
        automation.read_calendar_events, window, limit
    )
    selected = select_calendar_events(
        events,
        today=today_factory(),
        limit=limit,
    )
    report = _format_calendar_events(selected)

    should_close = await confirm_close(
        "Tôi đã tổng hợp xong, bạn có đồng ý để tắt Outlook? Hủy để giữ lại."
    )
    if not should_close:
        return f"{report}"

    closed = await asyncio.to_thread(
        automation.close_window_and_verify, window
    )
    if closed:
        return f"{report}"
    return (
        f"{report}"
    )
