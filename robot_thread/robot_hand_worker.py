"""Part 2. Only this worker sends commands on the process-wide uHand connection."""
import logging
import time

from common import robot_hand_control
from third_party import uhand_client_module as hand
from .sequence_loader import load_sequences

log = logging.getLogger("로봇")
RETRY_SECONDS = 2.0
STATUS_SECONDS = 1.0
IDLE_POLL = 0.05
HOME_MS = 500


def _outputs_off():
    hand.SetuHandBuzzer(0, 100, True)
    hand.SetuHandLED(0, 0, 0, 100)


def _home():
    _outputs_off()
    hand.SetuHandPulse(1500, 1500, 1500, 1500, 1500, 1500, HOME_MS)


def _play(card, settings, stop):
    if card.kind == "motion":
        hand.SetuHandPulse(*card.args)
    elif card.kind == "led":
        if settings.led_enabled:
            hand.SetuHandLED(*card.args)
    elif settings.buzzer_enabled:
        hand.SetuHandBuzzer(*card.args)
    elif not card.args[2]:
        stop.wait(card.args[1] / 1000)


def _session(settings, sequences, stop, state):
    active = -1
    index = None
    sequence = None
    poll_at = time.monotonic() + STATUS_SECONDS
    while not stop.is_set():
        target, reason = state.next_request()
        if reason:
            log.info("%s · 준비 자세 복귀", reason)
            state.playing(-1)
            _home()
            active, index, sequence = -1, None, None
            continue

        if target not in sequences:
            target = -1
        if target != active:
            if target == -1:
                state.playing(-1)
                _home()
            elif sequence and sequence.missing:
                _outputs_off()
            log.debug("재생 ID %d → %d", active, target)
            active = target
            sequence = sequences.get(active)
            index = 0 if sequence else None
            state.playing(active)

        if index is not None:
            log.debug("ID %d | 카드 %d/%d 시작", active, index + 1, len(sequence.cards))
            _play(sequence.cards[index], settings, stop)
            log.debug("ID %d | 카드 %d 완료", active, index + 1)
            index += 1
            if index == len(sequence.cards):
                index = sequence.repeat_from
        else:
            stop.wait(IDLE_POLL)
        # Also probe when the only timed cards are locally muted.
        if time.monotonic() >= poll_at and not stop.is_set():
            hand.GetStatus()
            poll_at = time.monotonic() + STATUS_SECONDS


def run_robot_worker(settings, directory, stop):
    state = robot_hand_control._state
    sequences = load_sequences(directory)
    log.info("서버 연결 대기 | 요청 ID -1 | 재생 ID -1")
    reported_failure = False
    while not stop.is_set():
        connected = False
        try:
            hand.Connect(settings.ip, settings.port)
            connected = True
            # Connect returns after the server's home and connection melody.
            state.connection(True)
            log.info("로봇손 연결 완료 · 입력 대기")
            reported_failure = False
            _session(settings, sequences, stop, state)
        except hand.UHandError as exc:
            if not reported_failure:
                log.warning("연결 또는 명령 실패 · %s · 재접속 대기", exc)
                reported_failure = True
        finally:
            state.connection(False)
            if connected and stop.is_set():
                try:
                    _outputs_off()
                except hand.UHandError:
                    log.info("종료 중 연결 해제 감지")
            hand.Disconnect()
        stop.wait(RETRY_SECONDS)
