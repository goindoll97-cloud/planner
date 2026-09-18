from __future__ import annotations

import unittest

from engine.stage2.project import EvidenceRef, Stage2Project
from engine.stage2.workflow import (
    PREF_KEY,
    VALIDATION_FINGERPRINT_KEY,
    mark_validation_confirmed,
    validation_confirmed,
)


class Stage2ValidationFingerprintTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-VALIDATION-FP",
            company_name="테스트화학",
            psm_required=True,
            cap_required=True,
            cap_group="1군",
            scope_confirmed=True,
            psm_selected=False,
            cap_selected=True,
            stage1_source_fingerprint="stage1-fixture",
            stage1_snapshot={
                "decision": {"cap_status": "1군"},
                "business": {"회사명": "테스트화학"},
            },
        )
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "최대보유량": 800, "단위": "kg"}],
            "USER_CONFIRMED",
            evidence=[
                EvidenceRef(
                    source_type="ATTACHMENT",
                    source_name="company_sds.pdf",
                    sha256="a" * 64,
                )
            ],
        )
        project.set_field(
            "inventory.facilities",
            "시설별 최대보유량 자료",
            [{"설비번호": "TK-301", "설비명": "염소 저장탱크"}],
            "USER_CONFIRMED",
        )
        return project

    def test_confirmation_is_bound_to_current_project_state(self):
        project = self._project()
        mark_validation_confirmed(project, True)

        self.assertTrue(validation_confirmed(project))
        prefs = project.stage1_snapshot[PREF_KEY]
        self.assertTrue(prefs["validation_confirmed"])
        self.assertTrue(prefs[VALIDATION_FINGERPRINT_KEY])

    def test_company_fact_change_invalidates_confirmation(self):
        project = self._project()
        mark_validation_confirmed(project, True)
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "최대보유량": 900, "단위": "kg"}],
            "USER_CONFIRMED",
        )

        self.assertFalse(validation_confirmed(project))

    def test_evidence_change_invalidates_confirmation(self):
        project = self._project()
        mark_validation_confirmed(project, True)
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "염소", "CAS 번호": "7782-50-5", "최대보유량": 800, "단위": "kg"}],
            "USER_CONFIRMED",
            evidence=[
                EvidenceRef(
                    source_type="ATTACHMENT",
                    source_name="revised_company_sds.pdf",
                    sha256="b" * 64,
                )
            ],
        )

        self.assertFalse(validation_confirmed(project))

    def test_scope_change_invalidates_confirmation(self):
        project = self._project()
        mark_validation_confirmed(project, True)
        project.set_authoring_scope(psm_selected=True, cap_selected=True)

        self.assertFalse(validation_confirmed(project))

    def test_ai_draft_change_does_not_invalidate_confirmation(self):
        project = self._project()
        mark_validation_confirmed(project, True)
        project.set_field(
            "ai_draft.CAP.cap.internal.shutdown",
            "AI 초안",
            {"draft_text": "확인된 사실만 사용한 문장 초안"},
            "AI_DRAFT",
        )

        self.assertTrue(validation_confirmed(project))

    def test_legacy_boolean_without_fingerprint_fails_closed(self):
        project = self._project()
        project.stage1_snapshot[PREF_KEY] = {"validation_confirmed": True}

        self.assertFalse(validation_confirmed(project))

    def test_explicit_unconfirm_removes_fingerprint(self):
        project = self._project()
        mark_validation_confirmed(project, True)
        mark_validation_confirmed(project, False)

        prefs = project.stage1_snapshot[PREF_KEY]
        self.assertFalse(prefs["validation_confirmed"])
        self.assertNotIn(VALIDATION_FINGERPRINT_KEY, prefs)
        self.assertFalse(validation_confirmed(project))


if __name__ == "__main__":
    unittest.main()
