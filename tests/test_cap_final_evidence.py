from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from engine.stage2 import cap_final_evidence as ev
from engine.stage2 import psm_attachments as att
from engine.stage2.cap_final_gate import evaluate_cap_final_gate
from engine.stage2.scope_validation import validate_selected_scope
from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests


def _project():
    return CAPForm1EngineTests()._project()


def _status(project, checkpoint_id):
    gate = evaluate_cap_final_gate(project, validate_selected_scope(project))
    return next(item for item in gate.checkpoints if item.key == checkpoint_id).status


class FinalEvidenceTests(unittest.TestCase):
    def test_unanswered_questions_hold_the_final_gate(self):
        project = _project()
        self.assertEqual(_status(project, "cap.final.other_system_review"), "HOLD")
        self.assertEqual(_status(project, "cap.final.joint_emergency"), "HOLD")

    def test_not_applicable_and_single_submission_pass_without_files(self):
        project = _project()
        ev.save_answers(project, "미해당", "단독제출")
        self.assertEqual(_status(project, "cap.final.other_system_review"), "PASS")
        self.assertEqual(_status(project, "cap.final.joint_emergency"), "PASS")

    def test_applicable_answers_need_the_company_files_before_passing(self):
        project = _project()
        ev.save_answers(project, "해당", "공동제출")
        self.assertEqual(_status(project, "cap.final.other_system_review"), "REVIEW_REQUIRED")
        with tempfile.TemporaryDirectory() as tmp, patch("engine.stage2.storage.DEFAULT_ROOT", Path(tmp)):
            self.assertTrue(ev.link_evidence(project, ev.OTHER_KEY, "psm-review.pdf", b"%PDF result"))
            self.assertTrue(ev.link_evidence(project, ev.JOINT_KEY, "joint.pdf", b"%PDF joint"))
            self.assertFalse(ev.link_evidence(project, ev.OTHER_KEY, "psm-review.pdf", b"%PDF result"))  # 같은 파일
        self.assertEqual(_status(project, "cap.final.other_system_review"), "PASS")
        self.assertEqual(_status(project, "cap.final.joint_emergency"), "PASS")
        self.assertEqual(ev.evidence_names(project, ev.OTHER_KEY), ["psm-review.pdf"])

    def test_files_cannot_be_linked_before_the_fact_is_confirmed(self):
        project = _project()
        with self.assertRaises(ValueError):
            ev.link_evidence(project, ev.OTHER_KEY, "a.pdf", b"x")
        ev.save_answers(project, "미해당", "단독제출")
        with self.assertRaises(ValueError):
            ev.link_evidence(project, ev.OTHER_KEY, "a.pdf", b"x")

    def test_resaving_the_same_answer_keeps_evidence_and_changing_it_drops_it(self):
        project = _project()
        ev.save_answers(project, "해당", "단독제출")
        with tempfile.TemporaryDirectory() as tmp, patch("engine.stage2.storage.DEFAULT_ROOT", Path(tmp)):
            ev.link_evidence(project, ev.OTHER_KEY, "r.pdf", b"%PDF")
        ev.save_answers(project, "해당", "단독제출")
        self.assertEqual(ev.evidence_names(project, ev.OTHER_KEY), ["r.pdf"])
        ev.save_answers(project, "미해당", "단독제출")
        self.assertEqual(ev.evidence_names(project, ev.OTHER_KEY), [])


class CapAttachmentTests(unittest.TestCase):
    def test_cap_slots_use_keys_that_do_not_collide_with_form_data(self):
        keys = {slot.key for slot in att.CAP_SLOTS}
        self.assertNotIn("cap.safety.dike_layout", keys)
        self.assertNotIn("cap.safety.gas_detection", keys)
        project = _project()
        with tempfile.TemporaryDirectory() as tmp:
            att.attach(project, "cap.site.equipment_layout", "layout.pdf", b"%PDF", root=Path(tmp))
        state = {item["slot"].key: item["state"] for item in att.status(project, att.CAP_SLOTS)}
        self.assertEqual(state["cap.site.equipment_layout"], "내용 확인 필요")
        self.assertEqual(state["documents.pid"], "올리지 않음")


if __name__ == "__main__":
    unittest.main()


class PanelRenderTests(unittest.TestCase):
    def test_final_evidence_and_attachment_panels_render(self):
        from streamlit.testing.v1 import AppTest

        root = str(Path(__file__).resolve().parents[1])
        code = (
            f"import sys; sys.path.insert(0, {root!r})\n"
            "from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests\n"
            "from engine.stage2 import psm_attachments\n"
            "from ui import attachments_panel, cap_final_evidence_panel\n"
            "project = CAPForm1EngineTests()._project()\n"
            "cap_final_evidence_panel.render(project)\n"
            "attachments_panel.render(project, psm_attachments.CAP_SLOTS, 'cap')\n"
        )
        at = AppTest.from_string(code, default_timeout=90).run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.selectbox), 2)
        self.assertTrue(any("올리지 않음" in e.label for e in at.expander))
