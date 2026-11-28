"""Part 1 entry point. Keep test input and real predictions mutually exclusive."""
import logging
from pathlib import Path
import time

from common import robot_hand_control
from common.settings import ACTIONS

log = logging.getLogger("EMG")
REFRESH_SECONDS = 0.2
CYCLE_SECONDS = 3.0
ROOT = Path(__file__).resolve().parent.parent


def run_emg_worker(stop):
    """Part 1: read the armband, classify, and publish each new decision's action ID.

    The model libraries are imported here, so the cycle test (`run_cycle_worker`) runs without
    them. Settings come from the optional [emg] section of Setup.ini; the model is the file in
    models/ whose name contains `model`.
    """
    try:
        from .classifier import EmgClassifier
        from .emg_settings import load_emg_settings
        from .models import discover
    except ImportError as exc:
        log.error("EMG 분류에 필요한 패키지가 없습니다 (%s) · python -m pip install -r requirements.txt", exc)
        raise
    settings = load_emg_settings(ROOT / "Setup.ini")
    specs, problems = discover(str(ROOT / "models"))
    for problem in problems:
        log.warning("모델 종류를 불러오지 못함 · %s", problem)
    spec = next((s for s in specs if settings.model.lower() in s.title.lower()), None)
    if spec is None:
        names = ", ".join(s.title for s in specs) or "없음"
        raise FileNotFoundError(f"models/에서 '{settings.model}' 모델을 찾지 못했습니다 (있는 모델: {names})")
    model = spec.load()
    log.info("모델 %s | %s", spec.title, model.info)
    log.info("암밴드 포트 %s | 확정 조건 %.0f%% 이상 %d회 연속", settings.port, 100 * settings.min_prob, settings.hold)
    EmgClassifier(model, robot_hand_control.set_action, settings.port, settings.min_prob, settings.hold).run(stop)


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
