import asyncio
from enum import Enum

from loguru import logger


class TaskState(str, Enum):
    IDLE = "idle"
    PENDING = "pending"
    WORKING = "working"
    DONE = "done"


class IntervalTask:
    """State-machine scheduler for a single recurring task.

    The ticker sets state → PENDING on each interval elapse.
    The worker monitors for PENDING, transitions WORKING → DONE, then
    returns to monitoring for the next tick.

    Usage::

        task = IntervalTask("process", interval=1800, pause_gate=pg, stop_event=stop)
        await task.run(do_work)
    """

    def __init__(
        self,
        name: str,
        interval: int,
        *,
        pause_gate=None,
        stop_event: asyncio.Event,
    ):
        self.name = name
        self.interval = interval
        self.pause_gate = pause_gate
        self.stop_event = stop_event

        self.state = TaskState.IDLE
        self._wake = asyncio.Event()

    async def _ticker(self) -> None:
        while not self.stop_event.is_set():
            try:
                async with asyncio.timeout(self.interval):
                    await self.stop_event.wait()
                return
            except TimeoutError:
                pass

            if self.pause_gate and await self.pause_gate.is_paused():
                logger.debug("[{}] paused, deferring tick", self.name)
                continue

            self.state = TaskState.PENDING
            self._wake.set()
            logger.info("[{}] state → pending", self.name)

    async def _worker(self, do_work) -> None:
        while not self.stop_event.is_set():
            if not await self._wait_wake_or_stop():
                return

            if self.state != TaskState.PENDING:
                continue

            self._wake.clear()
            self.state = TaskState.WORKING
            logger.info("[{}] state → working", self.name)

            try:
                await do_work()
            except Exception:
                logger.exception("[{}] cycle failed", self.name)

            self.state = TaskState.DONE
            logger.info("[{}] state → done", self.name)
            self.state = TaskState.IDLE

    async def _wait_wake_or_stop(self) -> bool:
        """Wait for _wake or stop_event. Returns True if woken, False if stopped."""
        if self._wake.is_set() or self.stop_event.is_set():
            return not self.stop_event.is_set()

        wake_fut = asyncio.ensure_future(self._wake.wait())
        stop_fut = asyncio.ensure_future(self.stop_event.wait())
        try:
            done, _ = await asyncio.wait(
                {wake_fut, stop_fut}, return_when=asyncio.FIRST_COMPLETED,
            )
            return wake_fut in done
        finally:
            wake_fut.cancel()
            stop_fut.cancel()

    async def run(self, do_work) -> None:
        """Start ticker + worker and run until stop_event is set."""
        await asyncio.gather(self._ticker(), self._worker(do_work))
