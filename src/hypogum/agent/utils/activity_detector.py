import asyncio
import shutil
import sys
from abc import ABC, abstractmethod

from loguru import logger


class ActivityDetector(ABC):
    """Abstract cross-platform user-activity detector (idle time + lock state)."""

    @abstractmethod
    async def is_locked(self) -> bool:
        """Return True if the workstation is locked. Best-effort — False if unknown."""
        ...

    @abstractmethod
    async def get_idle_seconds(self) -> float | None:
        """Return seconds since last user input, or None if it cannot be measured."""
        ...


class WindowsActivityDetector(ActivityDetector):
    """Windows idle/lock detection via ctypes + user32/kernel32 (no external deps)."""

    async def get_idle_seconds(self) -> float | None:
        try:
            import ctypes
            from ctypes import wintypes

            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            kernel32.GetTickCount.restype = wintypes.DWORD

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not user32.GetLastInputInfo(ctypes.byref(lii)):
                return None

            now = kernel32.GetTickCount()
            # GetTickCount wraps every ~49.7 days (DWORD); mask to 32 bits.
            idle_ms = (now - lii.dwTime) & 0xFFFFFFFF
            return idle_ms / 1000.0
        except Exception as e:
            logger.debug("Windows idle detection failed: {}", e)
            return None

    async def is_locked(self) -> bool:
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            user32.OpenInputDesktop.restype = wintypes.HANDLE
            user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

            DESKTOP_READOBJECTS = 0x0001
            UOI_NAME = 2

            hdesk = user32.OpenInputDesktop(0, False, DESKTOP_READOBJECTS)
            if not hdesk:
                # Secure desktop / lock screen denies access to a normal process.
                return True

            try:
                needed = wintypes.DWORD(0)
                buf = ctypes.create_unicode_buffer(256)
                ok = user32.GetUserObjectInformationW(
                    hdesk, UOI_NAME, buf,
                    ctypes.sizeof(buf), ctypes.byref(needed),
                )
                if not ok:
                    return False
                return buf.value.strip().lower() != "default"
            finally:
                user32.CloseDesktop(hdesk)
        except Exception as e:
            logger.debug("Windows lock detection failed: {}", e)
            return False


class MacOSActivityDetector(ActivityDetector):
    """macOS idle via ioreg (HIDIdleTime); lock via Quartz when available."""

    async def get_idle_seconds(self) -> float | None:
        if not shutil.which("ioreg"):
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ioreg", "-c", "IOHIDSystem",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return None
            text = stdout.decode("utf-8", errors="replace")
            best: float | None = None
            for line in text.splitlines():
                if "HIDIdleTime" not in line:
                    continue
                _, _, rhs = line.partition("=")
                rhs = rhs.strip()
                if not rhs.isdigit():
                    continue
                seconds = int(rhs) / 1_000_000_000.0
                if best is None or seconds < best:
                    best = seconds
            return best
        except Exception as e:
            logger.debug("macOS idle detection failed: {}", e)
            return None

    async def is_locked(self) -> bool:
        try:
            import Quartz  # type: ignore[import-not-found]

            session = Quartz.CGSessionCopyCurrentDictionary()
            if not session:
                return False
            return bool(session.get("CGSSessionScreenIsLocked", 0))
        except Exception as e:
            logger.debug("macOS lock detection unavailable: {}", e)
            return False


class LinuxActivityDetector(ActivityDetector):
    """Linux idle via xprintidle (X11); lock via gdbus ScreenSaver probe."""

    async def get_idle_seconds(self) -> float | None:
        if not shutil.which("xprintidle"):
            return None
        try:
            proc = await asyncio.create_subprocess_exec(
                "xprintidle",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0 or not stdout:
                return None
            value = stdout.decode().strip()
            if not value.isdigit():
                return None
            return int(value) / 1000.0
        except Exception as e:
            logger.debug("Linux idle detection failed: {}", e)
            return None

    async def is_locked(self) -> bool:
        if not shutil.which("gdbus"):
            return False
        probes = [
            ("org.gnome.ScreenSaver", "/org/gnome/ScreenSaver", "org.gnome.ScreenSaver.GetActive"),
            ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver", "org.freedesktop.ScreenSaver.GetActive"),
        ]
        for dest, path, method in probes:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "gdbus", "call", "--session",
                    "--dest", dest, "--object-path", path, "--method", method,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and stdout:
                    return "true" in stdout.decode("utf-8", errors="replace").lower()
            except Exception as e:
                logger.debug("Linux lock probe {} failed: {}", dest, e)
        return False


class NoopActivityDetector(ActivityDetector):
    """Fallback when no detection method is available: never locked, idle unknown."""

    async def is_locked(self) -> bool:
        return False

    async def get_idle_seconds(self) -> float | None:
        return None


def create_activity_detector() -> ActivityDetector:
    """Factory: return the platform-appropriate ActivityDetector."""
    if sys.platform == "win32":
        return WindowsActivityDetector()
    elif sys.platform == "darwin":
        return MacOSActivityDetector()
    else:
        if shutil.which("xprintidle") or shutil.which("gdbus"):
            return LinuxActivityDetector()
        logger.info("No activity detection tool found (install xprintidle for idle pausing)")
        return NoopActivityDetector()


class PauseGate:
    """Decides whether the agent should pause based on lock state and idle time.

    Wraps an ActivityDetector. Fails open (does not pause) on detector errors,
    and logs only on active<->paused transitions to avoid log spam.
    """

    def __init__(
        self,
        detector: ActivityDetector,
        *,
        pause_when_locked: bool = True,
        pause_when_idle: bool = True,
        idle_threshold: int = 300,
    ):
        self._detector = detector
        self._pause_when_locked = pause_when_locked
        self._pause_when_idle = pause_when_idle
        self._idle_threshold = idle_threshold
        self._paused = False

    async def is_paused(self) -> bool:
        paused, reason = await self._evaluate()
        if paused and not self._paused:
            logger.info("Pausing observation/processing ({})", reason)
        elif not paused and self._paused:
            logger.info("Resuming observation/processing (system active)")
        self._paused = paused
        return paused

    async def _evaluate(self) -> tuple[bool, str]:
        if self._pause_when_locked:
            try:
                if await self._detector.is_locked():
                    return True, "system locked"
            except Exception as e:
                logger.debug("Lock check failed, treating as active: {}", e)

        if self._pause_when_idle:
            try:
                idle = await self._detector.get_idle_seconds()
            except Exception as e:
                logger.debug("Idle check failed, treating as active: {}", e)
                idle = None
            if idle is not None and idle >= self._idle_threshold:
                return True, f"idle {int(idle)}s >= {self._idle_threshold}s"

        return False, ""
