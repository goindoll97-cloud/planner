from __future__ import annotations

from unittest.mock import patch
import unittest

from engine.stage2 import psm_narrative_workspace as nw
from tests.test_psm_narrative_workspace import FakeClient, _with_facts
from tests.test_psm_workspace_page import _project
from ui.narrative_panel import progress_lines


class ProgressTests(unittest.TestCase):
    def test_generation_reports_each_batch_start_and_finish(self):
        events = []
        project = _with_facts(_project())
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient(), progress=events.append)
        kinds = [e["event"] for e in events]
        self.assertEqual(kinds, ["start", "done"] * (len(kinds) // 2))
        self.assertEqual(events[-1]["done"], events[-1]["total"])
        self.assertEqual(events[-1]["generated"], len(result.generated))
        self.assertTrue(events[0]["labels"])

    def test_a_broken_progress_callback_never_stops_generation(self):
        project = _with_facts(_project())

        def broken(info):
            raise RuntimeError("화면 오류")
        with patch("engine.stage2.storage.save_project"):
            result = nw.generate(project, FakeClient(), progress=broken)
        self.assertTrue(result.generated)

    def test_progress_text_is_plain_korean_with_a_fraction(self):
        ratio, text = progress_lines({"event": "start", "done": 1, "total": 4, "labels": ["A", "B", "C", "D"], "elapsed": 12.4,
                                      "generated": 5, "rejected": 0})
        self.assertEqual(ratio, 0.25)
        self.assertIn("2/4번째", text)
        self.assertIn("A, B, C 외", text)
        ratio, text = progress_lines({"event": "done", "done": 4, "total": 4, "labels": [], "elapsed": 50, "generated": 15, "rejected": 1})
        self.assertEqual(ratio, 1.0)
        self.assertIn("초안 15개", text)


if __name__ == "__main__":
    unittest.main()
