"""Startup configuration and the shared gesture ID registry."""
import configparser
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from third_party.uhand_client_module._validation import endpoint

VERSION = "0.1.0"
ACTIONS = {
    0: "휴식", 1: "검지 펴기", 2: "엄지 쭉 꺾기", 3: "손목 젖히기",
    4: "손목 굽히기", 5: "손 펴기", 6: "주먹", 7: "새끼손가락 쪽으로 꺾기",
}
DEFAULT_INI = """[server]
ip = 192.168.61.1
port = 5000

[output]
led_enabled = true
buzzer_enabled = true

[debug]
enabled = false

[test]
cycle_enabled = false
"""
log = logging.getLogger("설정")


@dataclass(frozen=True)
class Settings:
    ip: str
    port: int
    led_enabled: bool
    buzzer_enabled: bool
    debug: bool
    cycle_enabled: bool


def _parse(text):
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read_string(text)
    ip = cfg.get("server", "ip")
    try:
        port = cfg.getint("server", "port")
        endpoint(ip, port)
    except ValueError as exc:
        raise ValueError(f"[server] ip/port: {exc}") from exc

    def flag(section, key):
        try:
            return cfg.getboolean(section, key)
        except ValueError as exc:
            raise ValueError(f"[{section}] {key}: {exc}") from exc

    return Settings(ip, port, flag("output", "led_enabled"), flag("output", "buzzer_enabled"),
                    flag("debug", "enabled"), flag("test", "cycle_enabled"))


def _backup(path, data):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    index = 0
    while True:
        suffix = "" if index == 0 else f"-{index}"
        backup = path.with_name(f"{path.name}.{stamp}{suffix}.bak")
        try:
            with backup.open("xb") as stream:
                stream.write(data)
            return backup
        except FileExistsError:
            index += 1


def load_settings(path: Path):
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        log.info("설정 파일 없음 · 기본 설정 생성: %s", path)
    else:
        try:
            return _parse(data.decode("utf-8-sig"))
        except (configparser.Error, ValueError) as exc:
            backup = _backup(path, data)
            log.warning("설정 오류 (%s) · 백업 %s · 기본 설정으로 복구", exc, backup)

    with NamedTemporaryFile(dir=path.parent, prefix=".Setup-", suffix=".tmp", delete=False) as temp:
        temp_path = Path(temp.name)
        try:
            temp.write(DEFAULT_INI.encode("utf-8"))
            temp.flush()
        finally:
            temp.close()
    try:
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)
    return _parse(DEFAULT_INI)
