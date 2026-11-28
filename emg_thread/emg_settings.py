"""Part 1 settings: the optional [emg] section of Setup.ini. Every key has a default, so a
Setup.ini without the section (or one restored to its defaults) still works."""
from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EmgSettings:
    port: str = "auto"          # "auto" = the armband's CH340 USB receiver; a port such as "COM4";
    #                             without an armband: "demo", or "replay:<recorded session folder>"
    model: str = "500그루"      # any part of a model file's name in models/
    min_prob: float = 0.6       # a new gesture is confirmed after `hold` decisions in a row at this probability
    hold: int = 3


def load_emg_settings(ini: Path) -> EmgSettings:
    """-> the [emg] settings. A missing file or section gives the defaults; a value that cannot
    be read raises ValueError naming the key."""
    cfg = configparser.ConfigParser(interpolation=None)
    try:
        cfg.read_string(ini.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return EmgSettings()
    except configparser.Error as exc:
        raise ValueError(f"Setup.ini: {exc}") from exc
    if not cfg.has_section("emg"):
        return EmgSettings()
    base = EmgSettings()
    try:
        settings = EmgSettings(
            port=cfg.get("emg", "port", fallback=base.port).strip() or base.port,
            model=cfg.get("emg", "model", fallback=base.model).strip() or base.model,
            min_prob=cfg.getfloat("emg", "min_prob", fallback=base.min_prob),
            hold=cfg.getint("emg", "hold", fallback=base.hold),
        )
    except ValueError as exc:
        raise ValueError(f"[emg]: {exc}") from exc
    if not 0.0 < settings.min_prob <= 1.0 or settings.hold < 1:
        raise ValueError("[emg]: min_prob는 0 초과 1 이하, hold는 1 이상이어야 합니다.")
    return settings
