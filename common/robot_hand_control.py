"""The two functions used by the EMG producer; all robot I/O belongs to its worker."""
import logging
import threading
import time

from .settings import ACTIONS

__all__ = ["set_action", "get_current_action"]
log = logging.getLogger("EMG")
INPUT_TIMEOUT = 3.0


class _ActionState:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.session = 0
        self.online = False
        self.requested = -1
        self.current = -1
        self.last_input = None
        self.home_reason = None

    def connection(self, online):
        with self.lock:
            self.session += 1
            self.online = online
            self.requested = self.current = -1
            self.last_input = self.home_reason = None

    def ready_session(self):
        with self.lock:
            return self.session if self.online else None

    def _expire(self, now):
        if self.requested != -1 and now - self.last_input >= INPUT_TIMEOUT:
            self.requested = -1
            self.home_reason = "EMG 입력 두절 (3,000ms)"

    def submit(self, action_id, session=None):
        if type(action_id) is not int:
            raise TypeError("action_id는 Python int여야 합니다.")
        if action_id != -1 and action_id not in ACTIONS:
            raise ValueError(f"등록되지 않은 동작 ID: {action_id}")
        with self.lock:
            if not self.online or (session is not None and self.session != session):
                return
            now = self.clock()
            self._expire(now)
            previous = self.requested
            self.last_input = now
            self.requested = action_id
            if action_id == -1 and previous != -1:
                self.home_reason = "정지 요청"
            if previous != action_id:
                log.debug("요청 ID %d → %d", previous, action_id)

    def next_request(self):
        with self.lock:
            self._expire(self.clock())
            reason, self.home_reason = self.home_reason, None
            return self.requested, reason

    def playing(self, action_id):
        with self.lock:
            self.current = action_id

    def current_id(self):
        with self.lock:
            return self.current


_state = _ActionState()


def set_action(action_id: int) -> None:
    """Publish the latest valid action without waiting for I/O. -1 requests home."""
    _state.submit(action_id)


def get_current_action() -> int:
    """Return the playing sequence ID or -1 when idle/disconnected."""
    return _state.current_id()
