"""Part 1 entry point. Keep test input and real predictions mutually exclusive."""
import logging
import time

from common import robot_hand_control
from common.settings import ACTIONS

log = logging.getLogger("EMG")
REFRESH_SECONDS = 0.2
CYCLE_SECONDS = 3.0


def run_emg_worker(stop):
    """Part 1: replace the wait with armband acquisition and model inference."""
    log.info("EMG 입력 대기 · 분류기를 연결하면 실제 동작을 시작합니다.")
    # Publish each valid prediction with robot_hand_control.set_action(int(label)).
    # Pass -1 on armband loss. Check stop regularly when reading the device.
    stop.wait()


def run_cycle_worker(stop):
    ids = tuple(sorted(ACTIONS))
    state = robot_hand_control._state
    previous_session = None
    while not stop.is_set():
        session = state.ready_session()
        if session is not None:
            now = time.monotonic()
            if session != previous_session:
                started = now
                previous_session = session
            index = int((now - started) / CYCLE_SECONDS) % len(ids)
            state.submit(ids[index], session=session)
        stop.wait(REFRESH_SECONDS)
