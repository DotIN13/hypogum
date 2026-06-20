import asyncio
import shutil
import sys
from abc import ABC, abstractmethod

from loguru import logger


class Notifier(ABC):
    """Abstract cross-platform desktop notification provider."""

    @abstractmethod
    async def notify(self, title: str, body: str) -> bool:
        """Fire a desktop notification. Returns True if successful."""
        ...


class WindowsNotifier(Notifier):
    """Windows notification via native WinRT toast API."""

    async def notify(self, title: str, body: str) -> bool:
        try:
            if shutil.which("powershell"):
                ps = (
                    "[Windows.UI.Notifications.ToastNotificationManager,"
                    "Windows.UI.Notifications,ContentType=WindowsRuntime];"
                    "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
                    "GetTemplateContent(1);"
                    "$template.SelectSingleNode('//text[1]').InnerText = "
                    f"'{title.replace(chr(39), chr(39)+chr(39))}';"
                    "$texts = $template.GetElementsByTagName('text');"
                    "if ($texts.Count -gt 1) { $texts[1].InnerText = "
                    f"'{body.replace(chr(39), chr(39)+chr(39))}'" "};"
                    "$notifier = [Windows.UI.Notifications.ToastNotificationManager]"
                    "::CreateToastNotifier('hypogum');"
                    "$notifier.Show($template)"
                )
                proc = await asyncio.create_subprocess_exec(
                    "powershell", "-NoProfile", "-Command", ps,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
                if proc.returncode == 0:
                    return True

            logger.info("[notification] {} — {}", title, body)
            return False
        except Exception as e:
            logger.debug("Windows notification failed: {}", e)
            return False


class MacOSNotifier(Notifier):
    """macOS notification via osascript display notification."""

    async def notify(self, title: str, body: str) -> bool:
        try:
            safe_title = title.replace('"', '\\"').replace("\n", " ")
            safe_body = body.replace('"', '\\"').replace("\n", " ")
            script = (
                f'display notification "{safe_body}" '
                f'with title "{safe_title}" '
                'sound name "default"'
            )
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as e:
            logger.debug("macOS notification failed: {}", e)
            return False


class LinuxNotifier(Notifier):
    """Linux notification via notify-send (libnotify)."""

    async def notify(self, title: str, body: str) -> bool:
        if not shutil.which("notify-send"):
            logger.info("[notification] {} — {}", title, body)
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                "notify-send", title, body,
                "--app-name=hypogum",
                "--icon=dialog-information",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return proc.returncode == 0
        except Exception as e:
            logger.debug("Linux notification failed: {}", e)
            return False


def create_notifier() -> Notifier:
    """Factory: return the platform-appropriate Notifier."""
    if sys.platform == "win32":
        return WindowsNotifier()
    elif sys.platform == "darwin":
        return MacOSNotifier()
    else:
        return LinuxNotifier()
