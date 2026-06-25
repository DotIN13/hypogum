import asyncio
import shutil
import sys
from abc import ABC, abstractmethod

from loguru import logger


class WindowDetector(ABC):
    """Abstract cross-platform window detection."""

    @abstractmethod
    async def get_active_windows(self) -> list[str]:
        """Return a list of currently visible window titles. Best-effort — may be empty."""
        ...

    async def get_active_window_title(self) -> str | None:
        """Return the title of the frontmost (focused) window, or None."""
        return None


class WindowsWindowDetector(WindowDetector):
    """Windows window titles via ctypes + user32.dll (no external deps)."""

    async def get_active_window_title(self) -> str | None:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return None
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value.strip()
            return title if title else None
        except Exception as e:
            logger.debug("Windows active window detection failed: {}", e)
            return None

    async def get_active_windows(self) -> list[str]:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL,
                wintypes.HWND, wintypes.LPARAM)

            titles: list[str] = []

            def _callback(hwnd, _lparam):
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length == 0:
                    return True
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title:
                    titles.append(title)
                return True

            user32.EnumWindows(WNDENUMPROC(_callback), 0)
            return titles

        except Exception as e:
            logger.debug("Windows window detection failed: {}", e)
            return []


class MacOSWindowDetector(WindowDetector):
    """macOS window titles via osascript (AppleScript)."""

    async def get_active_window_title(self) -> str | None:
        if not shutil.which("osascript"):
            return None
        try:
            script = (
                'tell application "System Events" to '
                'get name of front window of first process '
                'whose frontmost is true'
            )
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                return stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            logger.debug("macOS active window detection failed: {}", e)
        return None

    async def get_active_windows(self) -> list[str]:
        if not shutil.which("osascript"):
            return []
        try:
            script = (
                'tell application "System Events" to '
                'get name of every window of every process '
                'whose visible is true'
            )
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                text = stdout.decode("utf-8", errors="replace").strip()
                return [t.strip() for t in text.split(", ")
                        if t.strip() and t.strip() != "missing value"]
            return []
        except Exception as e:
            logger.debug("macOS window detection failed: {}", e)
            return []


class LinuxWindowDetector(WindowDetector):
    """Linux window titles via xdotool or wmctrl."""

    async def get_active_window_title(self) -> str | None:
        if not shutil.which("xdotool"):
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "getactivewindow", "getwindowname",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0 and stdout:
                return stdout.decode("utf-8", errors="replace").strip()
        except Exception as e:
            logger.debug("Linux active window detection failed: {}", e)
        return None

    async def get_active_windows(self) -> list[str]:
        if shutil.which("xdotool"):
            return await self._via_xdotool()
        if shutil.which("wmctrl"):
            return await self._via_wmctrl()
        return []

    async def _via_xdotool(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "xdotool", "search", "--onlyvisible", "--name", "",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return []

            window_ids = stdout.decode().strip().split("\n")
            titles: list[str] = []
            for wid in window_ids:
                wid = wid.strip()
                if not wid:
                    continue
                proc2 = await asyncio.create_subprocess_exec(
                    "xdotool", "getwindowname", wid,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await proc2.communicate()
                title = out.decode("utf-8", errors="replace").strip()
                if title:
                    titles.append(title)
            return titles
        except Exception as e:
            logger.debug("xdotool window detection failed: {}", e)
            return []

    async def _via_wmctrl(self) -> list[str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wmctrl", "-l",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return []
            titles: list[str] = []
            for line in stdout.decode("utf-8", errors="replace").strip().split("\n"):
                parts = line.split(None, 3)
                if len(parts) >= 4:
                    titles.append(parts[3].strip())
            return titles
        except Exception as e:
            logger.debug("wmctrl window detection failed: {}", e)
            return []


class NoopWindowDetector(WindowDetector):
    """Returns empty list — fallback when no detection method is available."""

    async def get_active_windows(self) -> list[str]:
        return []


def create_window_detector() -> WindowDetector:
    """Factory: return the platform-appropriate WindowDetector."""
    if sys.platform == "win32":
        return WindowsWindowDetector()
    elif sys.platform == "darwin":
        return MacOSWindowDetector()
    else:
        det = LinuxWindowDetector()
        if shutil.which("xdotool") or shutil.which("wmctrl"):
            return det
        logger.info("No window detection tool found (install xdotool or wmctrl)")
        return NoopWindowDetector()
