"""Part 1 without devices: a synthetic armband stream through the real model.

    python -m unittest discover -s tests
"""
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                              # noqa: E402

from common.settings import ACTIONS                             # noqa: E402
from emg_thread.classifier import ACTION_IDS, HOME, EmgClassifier   # noqa: E402
from emg_thread.emg_settings import EmgSettings, load_emg_settings  # noqa: E402
from emg_thread.models import Decision, GestureModel, discover  # noqa: E402
from emg_thread.sensor.link import Link                         # noqa: E402


class Sure(GestureModel):
    """Decides `gesture` with probability `prob` for every 50 samples it is fed."""
    gestures = ["rest", "fist", "open"]

    def __init__(self, gesture="fist", prob=0.9):
        self.gesture, self.prob, self.resets, self.pending = gesture, prob, 0, 0

    def reset(self):
        self.resets += 1
        self.pending = 0

    def feed(self, t, x):
        self.pending += len(t)
        due, self.pending = divmod(self.pending, 50)
        p = np.full(3, (1 - self.prob) / 2)
        p[self.gestures.index(self.gesture)] = self.prob
        return [Decision(float(t[-1]), p) for _ in range(due)]


def wait_for(condition, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return condition()


class Run:
    """An EmgClassifier running on a demo link in its own thread; collects what it publishes."""

    def __init__(self, model, **kw):
        self.sent, self.stop, self.link = [], threading.Event(), Link()
        self.link.open_demo("hex")
        self.classifier = EmgClassifier(model, self.sent.append, link=self.link, **kw)
        self.thread = threading.Thread(target=self.classifier.run, args=(self.stop,), daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=5)


class EmgClassifierTest(unittest.TestCase):
    def test_action_ids_are_the_theaters(self):
        self.assertEqual(sorted(ACTION_IDS.values()), sorted(ACTIONS))
        self.assertEqual((ACTION_IDS["fist"], ACTION_IDS["rest"], ACTION_IDS["open"]), (6, 0, 5))

    def test_publishes_the_confirmed_gesture_for_every_decision(self):
        run = Run(Sure("fist"))
        try:
            self.assertTrue(wait_for(lambda: len(run.sent) >= 5, 8), run.sent)
            self.assertEqual(set(run.sent), {6})                 # only the confirmed gesture, repeatedly
            run.classifier.model.gesture = "open"
            self.assertTrue(wait_for(lambda: 5 in run.sent, 5))
            self.assertTrue(all(type(v) is int for v in run.sent))
        finally:
            run.close()

    def test_an_unsure_model_publishes_nothing(self):
        run = Run(Sure("fist", prob=0.4))
        try:
            time.sleep(3)
            self.assertEqual(run.sent, [])
        finally:
            run.close()

    def test_losing_the_armband_requests_home_once_and_stops_publishing(self):
        run = Run(Sure("fist"))
        try:
            self.assertTrue(wait_for(lambda: 6 in run.sent, 8))
            run.link.close()                                     # the armband is gone
            self.assertTrue(wait_for(lambda: HOME in run.sent, 4))
            at = run.sent.index(HOME)
            time.sleep(1)
            self.assertEqual(run.sent[at:], [HOME])              # nothing after the one home request
            run.link.open_demo("hex")                            # back again: classification restarts
            self.assertTrue(wait_for(lambda: run.sent[-1] == 6, 8), run.sent[at:])
        finally:
            run.close()

    def test_a_model_with_a_gesture_the_theater_lacks_is_refused(self):
        model = Sure()
        model.gestures = ["rest", "scissors"]
        with self.assertRaises(ValueError):
            EmgClassifier(model, lambda _id: None, link=Link())

    def test_the_delivered_forest_runs_on_the_stream(self):
        specs, problems = discover(str(ROOT / "models"))
        self.assertEqual(problems, [])
        spec = next(s for s in specs if "500그루" in s.title)
        run = Run(spec.load(), min_prob=0.0, hold=1)             # the demo signal is not a real gesture: accept any
        try:
            self.assertTrue(wait_for(lambda: len(run.sent) >= 3, 10), run.sent)
            self.assertTrue(set(run.sent) <= set(ACTIONS))
        finally:
            run.close()


class EmgSettingsTest(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            ini = Path(tmp) / "Setup.ini"
            if text is not None:
                ini.write_text(text, encoding="utf-8")
            return load_emg_settings(ini)

    def test_defaults_without_file_or_section(self):
        self.assertEqual(self.read(None), EmgSettings())
        self.assertEqual(self.read("[server]\nip = 127.0.0.1\n"), EmgSettings())

    def test_values_and_errors(self):
        got = self.read("[emg]\nport = COM4\nmodel = 300그루\nmin_prob = 0.7\nhold = 5\n")
        self.assertEqual(got, EmgSettings("COM4", "300그루", 0.7, 5))
        for bad in ("[emg]\nhold = many\n", "[emg]\nmin_prob = 1.5\n", "[emg]\nhold = 0\n"):
            with self.assertRaises(ValueError):
                self.read(bad)


if __name__ == "__main__":
    unittest.main()
