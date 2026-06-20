import asyncio

from hypogum.agent.utils.activity_detector import PauseGate


class FakeDetector:
    def __init__(self, locked=False, idle=None):
        self.locked = locked
        self.idle = idle

    async def is_locked(self):
        return self.locked

    async def get_idle_seconds(self):
        return self.idle


def _paused(gate):
    return asyncio.run(gate.is_paused())


def test_active_not_paused():
    gate = PauseGate(FakeDetector(locked=False, idle=10), idle_threshold=300)
    assert _paused(gate) is False


def test_locked_pauses():
    gate = PauseGate(FakeDetector(locked=True, idle=0), idle_threshold=300)
    assert _paused(gate) is True


def test_idle_over_threshold_pauses():
    gate = PauseGate(FakeDetector(locked=False, idle=301), idle_threshold=300)
    assert _paused(gate) is True


def test_idle_under_threshold_active():
    gate = PauseGate(FakeDetector(locked=False, idle=299), idle_threshold=300)
    assert _paused(gate) is False


def test_unknown_idle_does_not_pause():
    gate = PauseGate(FakeDetector(locked=False, idle=None), idle_threshold=300)
    assert _paused(gate) is False


def test_lock_disabled_ignores_lock():
    gate = PauseGate(
        FakeDetector(locked=True, idle=0),
        pause_when_locked=False,
        idle_threshold=300,
    )
    assert _paused(gate) is False


def test_idle_disabled_ignores_idle():
    gate = PauseGate(
        FakeDetector(locked=False, idle=9999),
        pause_when_idle=False,
        idle_threshold=300,
    )
    assert _paused(gate) is False


def test_detector_error_fails_open():
    class Boom:
        async def is_locked(self):
            raise RuntimeError("boom")

        async def get_idle_seconds(self):
            raise RuntimeError("boom")

    gate = PauseGate(Boom(), idle_threshold=300)
    assert _paused(gate) is False
