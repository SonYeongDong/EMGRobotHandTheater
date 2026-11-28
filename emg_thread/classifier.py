"""Part 1: armband samples -> gesture model -> confirmed gesture -> action ID.

The classifier owns the armband link. About fifty times a second it hands the new samples to
the model; for every decision the model returns (ten a second) it publishes the confirmed
gesture's action ID. It publishes -1 once when the signal can no longer be trusted (armband
disconnected, stream stalled, wrong mode) and nothing more until the signal is good again, so
the robot worker's own 3 s input watch also sees a dead classifier.
"""
from __future__ import annotations

import logging
import time
from typing import Callable

import numpy as np

from .decide.stabilizer import Stabilizer
from .models import GestureModel
from .sensor.health import HealthMonitor
from .sensor.link import Link
from .sensor.protocol import LinkState
from .sensor.sources import find_ch340

log = logging.getLogger("EMG")

# gesture key -> action ID of common.settings.ACTIONS
ACTION_IDS = {"rest": 0, "index": 1, "radial_dev": 2, "wrist_ext": 3, "wrist_flex": 4, "open": 5, "fist": 6,
              "ulnar_dev": 7}
HOME = -1
TICK_S = 0.02
HEALTH_S = 0.2
RETRY_S = 2.0


class EmgClassifier:
    def __init__(self, model: GestureModel, publish: Callable[[int], None], port: str = "auto",
                 min_prob: float = 0.6, hold: int = 3, link: Link | None = None) -> None:
        """`publish` receives an action ID or -1 (robot_hand_control.set_action). Pass a `link`
        that is already open (a demo or replayed signal) to run without the armband; the
        classifier then never opens a serial port itself."""
        unknown = [g for g in model.gestures if g not in ACTION_IDS]
        if unknown:
            raise ValueError(f"동작 ID가 없는 모델 동작: {unknown}")
        self.model, self.publish, self.port = model, publish, port
        self.link = link or Link()
        self._own_link = link is None
        self.stabilizer = Stabilizer(min_prob, hold)
        self.health = HealthMonitor()
        self._gen, self._pos = -1, 0
        self._ok = False                 # the signal may drive the robot
        self._next_health = self._next_open = 0.0
        self._said_no_port = False
        self._said_error = ""

    # ------------------------------------------------------------ the loop
    def run(self, stop) -> None:
        """Classify until `stop` is set. The link is closed on the way out."""
        try:
            while not stop.is_set():
                self.tick(time.monotonic())
                stop.wait(TICK_S)
        finally:
            self.link.close()

    def tick(self, now: float) -> None:
        if self._own_link and self.link.state in (LinkState.DISCONNECTED, LinkState.ERROR) and now >= self._next_open:
            self._next_open = now + RETRY_S
            self._open()
        if now >= self._next_health:
            self._next_health = now + HEALTH_S
            self._check_health()
        self._classify()

    # ------------------------------------------------------------ armband
    def _open(self) -> None:
        port = self.port
        if port == "demo":                           # no armband: a synthetic signal (decisions mean nothing)
            self.link.open_demo("hex")
            return
        if port.startswith("replay:"):               # no armband: a recorded session, played again when it ends
            self.link.open_replay(port[len("replay:"):].strip())
            return
        if port == "auto":
            found = find_ch340()
            if not found:
                if not self._said_no_port:
                    log.warning("암밴드 수신기(CH340)를 찾지 못했습니다 · USB에 꽂으면 자동으로 연결합니다.")
                    self._said_no_port = True
                return
            port = found[0]
        self._said_no_port = False
        log.info("암밴드 연결 시도 · %s", port)
        self.link.open_serial(port)

    def _check_health(self) -> None:
        replay = self.link.replay
        h = self.health.check(self.link.snapshot(), self.link.emg.last(500),
                              replay_finished=bool(replay is not None and replay.finished))
        if replay is not None and replay.finished:
            self.link.close()                        # the next tick opens it again from the start
        error = self.link.error if self.link.state == LinkState.ERROR else ""
        if error and error != self._said_error:      # say why the input cannot be opened, once
            log.warning("암밴드 입력을 열지 못했습니다 · %s · %d초마다 다시 시도합니다.", error, int(RETRY_S))
        self._said_error = error or self._said_error
        ok = h.state == LinkState.CONNECTED.value and h.mode == "hex" and h.ok
        if ok and not self._ok:
            log.info("암밴드 신호 정상 · %s · 분류 시작", h.source)
            self._gen = -1                           # start from the newest sample
        elif self._ok and not ok:
            why = "; ".join(i.text for i in h.issues if i.level == "error") or f"연결 상태 {h.state}"
            log.warning("암밴드 신호 이상 · %s · 준비 자세 요청", why)
            self.stabilizer.reset()
            self.publish(HOME)
        self._ok = ok

    # ------------------------------------------------------------ model
    def _classify(self) -> None:
        if not self._ok:
            return
        if self._gen == -1:
            self._gen, self._pos = self.link.gen, self.link.emg.total
            self.model.reset()
            return
        gen, raw, t, pos = self.link.read_since(self._gen, self._pos)
        if gen != self._gen:
            self.model.reset()                       # the stream restarted: forget the old window
            self.stabilizer.reset()
        self._gen, self._pos = gen, pos
        if not len(t):
            return
        for decision in self.model.feed(t, raw):
            top = int(np.argmax(decision.proba))
            gesture = self.stabilizer.update(self.model.gestures[top], float(decision.proba[top]))
            if gesture is not None:                  # nothing is published until a gesture is confirmed
                self.publish(ACTION_IDS[gesture])
