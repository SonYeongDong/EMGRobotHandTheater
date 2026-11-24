"""Start the EMG input and robot playback workers in one Python process."""
import logging
from pathlib import Path
import signal
import threading

from common.settings import VERSION, load_settings
from emg_thread.emg_worker import run_cycle_worker, run_emg_worker
from robot_thread.robot_hand_worker import run_robot_worker
from third_party import uhand_client_module as hand


def main():
    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")
    log = logging.getLogger("시작")
    root = Path(__file__).resolve().parent
    ini = root / "Setup.ini"
    log.info("EMGRobotHandTheater %s | EMG 로봇손 인형극 제어 | uHandClientModule %s",
             VERSION, hand.__version__)
    try:
        settings = load_settings(ini)
    except OSError as exc:
        log.error("설정 읽기·복구 실패 %s · %s", ini, exc)
        return 1
    if settings.debug:
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        formatter = logging.Formatter("[%(asctime)s.%(msecs)03d] [%(name)s] %(message)s", "%H:%M:%S")
        for handler in logger.handlers:
            handler.setFormatter(formatter)
    log.info("%s | 서버 %s:%d | LED %s | 부저 %s | 디버그 %s", ini, settings.ip, settings.port,
             settings.led_enabled, settings.buzzer_enabled, settings.debug)
    if settings.cycle_enabled:
        log.warning("순환 시험 켜짐 · 등록 ID 순서대로 3초 간격 · 실제 EMG 입력 꺼짐")
    else:
        log.info("순환 시험 꺼짐 · 실제 EMG 입력 대기")

    stop = threading.Event()
    failures = threading.Event()

    def supervise(target, *args):
        try:
            target(*args, stop)
        except Exception:
            logging.getLogger(threading.current_thread().name).exception("워커 중단")
            failures.set()
        finally:
            stop.set()

    def finish(signum, frame):
        stop.set()

    signal.signal(signal.SIGINT, finish)
    signal.signal(signal.SIGTERM, finish)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, finish)
    input_worker = run_cycle_worker if settings.cycle_enabled else run_emg_worker
    threads = [
        threading.Thread(name="로봇", target=supervise, args=(run_robot_worker, settings, root / "sequences")),
        threading.Thread(name="EMG", target=supervise, args=(input_worker,)),
    ]
    for worker in threads:
        worker.start()
    try:
        while not stop.wait(0.2):
            pass
    finally:
        stop.set()
        for worker in threads:
            worker.join()
    log.info("종료 · 서버 연결 정리 완료")
    return int(failures.is_set())


if __name__ == "__main__":
    raise SystemExit(main())
