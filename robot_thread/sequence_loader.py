"""Read only playback data from uHandMotionCreator files. Never execute file contents."""
from dataclasses import dataclass
import json
import logging

from common.settings import ACTIONS
from third_party.uhand_client_module._validation import buzzer_params, led_params, pulse_params

log = logging.getLogger("동작")
NOTES = (131, 147, 165, 175, 196, 220, 247, 262, 294, 330, 349, 392, 440, 494, 523, 587)
UNITS = {"pulse": "us", "running_time": "ms", "frequency": "Hz"}
MAX_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Card:
    kind: str
    args: tuple

    @property
    def timed(self):
        return self.kind == "motion" or (self.kind == "buzzer" and not self.args[2])


@dataclass(frozen=True)
class Sequence:
    cards: tuple
    repeat_from: int | None
    missing: bool = False


def _card(row, version):
    if not isinstance(row, dict):
        raise ValueError("카드 객체 필요")
    name = row["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 60 or any(ord(c) < 32 for c in name):
        raise ValueError("유효하지 않은 카드 이름")
    kind = row["kind"]
    if kind == "motion":
        pulses, ms = row["pulses"], row["running_time"]
        if not isinstance(pulses, list):
            raise ValueError("펄스 배열 필요")
        pulse_params(pulses, ms)
        return Card(kind, (*pulses, ms))
    if kind == "buzzer":
        args = (row["frequency"], row["running_time"], row["continuous"])
        buzzer_params(*args)
        return Card(kind, args)
    if kind == "led":
        rgb = tuple(row[channel] for channel in ("red", "green", "blue"))
        required_type = bool if version == 1 else int
        if any(type(channel) is not required_type for channel in rgb):
            raise ValueError("LED 채널 자료형 확인")
        if version == 1:
            if "brightness" in row:
                raise ValueError("스키마 1 LED에는 밝기가 없습니다.")
            args = (*[255 * value for value in rgb], 100)
        else:
            args = (*rgb, row["brightness"])
        led_params(*args)
        return Card(kind, args)
    raise ValueError(f"지원하지 않는 카드 종류 {kind}")


def _unique_keys(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"중복 JSON 키 {key}")
        obj[key] = value
    return obj


def read_sequence(path):
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("5 MiB 초과")
    doc = json.loads(data.decode("utf-8-sig"), object_pairs_hook=_unique_keys)
    if not isinstance(doc, dict) or doc.get("format") != "uhand-motion-sequence":
        raise ValueError("uHandMotionCreator 파일 형식 확인")
    version = doc.get("schema_version")
    if type(version) is not int or version not in (1, 2) or doc.get("units") != UNITS:
        raise ValueError("스키마 버전 또는 단위 확인")
    rows = doc.get("cards")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5000:
        raise ValueError("동작 카드 1~5000개 필요")
    cards = []
    for number, row in enumerate(rows, 1):
        try:
            cards.append(_card(row, version))
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError(f"카드 {number}: {exc}") from exc
    return Sequence(tuple(cards), 0 if any(c.timed for c in cards) else None)


def missing_sequence(action_id):
    if not 0 <= action_id < len(NOTES):
        raise ValueError("누락 표시 범위 0~15를 벗어났습니다.")
    if action_id == 0:
        first = (2200, 800, 800, 800, 800, 500)
        second = (*first[:5], 2500)
    else:
        fingers = tuple(800 if action_id & mask else 2000 for mask in (8, 4, 2, 1))
        first = (800, *fingers, 1500)
        second = (800, 2000, 2000, 2000, 2000, 1500)
    return Sequence((Card("led", (255, 0, 0, 50)), Card("buzzer", (NOTES[action_id], 300, True)),
                     Card("motion", (*first, 300)), Card("motion", (*second, 300))), 2, True)


def load_sequences(directory):
    sequences = {}
    missing = damaged = 0
    for action_id in ACTIONS:
        path = directory / f"action_{action_id:02d}.uhjson"
        try:
            try:
                sequences[action_id] = read_sequence(path)
            except FileNotFoundError:
                missing += 1
                log.info("%s 누락 · ID %d 요청 시 기본 표시", path.name, action_id)
                sequences[action_id] = missing_sequence(action_id)
        except (OSError, ValueError, RecursionError) as exc:
            damaged += 1
            log.error("%s 재생 보류 · %s", path.name, exc)
    log.info("등록 %d | 파일 로드 %d | 누락 %d | 재생 보류 %d",
             len(ACTIONS), len(ACTIONS) - missing - damaged, missing, damaged)
    return sequences
