from __future__ import annotations

import unittest
from unittest.mock import patch

import engine.legal_update_pipeline as pipeline
from engine.regulatory_tables import CandidateResult


class OneClickLegalUpdatePipelineTests(unittest.TestCase):
    @staticmethod
    def _law_rows(status: str = "UPDATE_PENDING"):
        return [
            {
                "key": "CAP_QTY",
                "title": "유해화학물질의 규정수량에 관한 규정",
                "monitor_status": status,
                "monitor_status_ko": "변경 감지·재반영 필요" if status != "CURRENT" else "최신·반영본 일치",
                "observation_valid": True,
                "attachment_file_count": 2,
                "attachment_files": [
                    {"format": "PDF"},
                    {"format": "HWPX"},
                ],
                "change_reason": ["첨부파일 내용 변경: 별표1"] if status != "CURRENT" else [],
            },
            {
                "key": "PSM_DECREE",
                "title": "산업안전보건법 시행령",
                "monitor_status": "CURRENT",
                "monitor_status_ko": "최신·반영본 일치",
                "observation_valid": True,
                "attachment_file_count": 2,
                "attachment_files": [{"format": "PDF"}, {"format": "HWP"}],
                "change_reason": [],
            },
        ]

    @staticmethod
    def _builder(key: str, rows: int = 10, status: str = "REVIEW_REQUIRED"):
        def build():
            return CandidateResult(
                key=key,
                status=status,
                row_count=rows,
                source_file=f"data/runtime/{key}.pdf",
                candidate_file=f"data/runtime/{key}.csv",
                messages=["자동검증 완료"] if status == "REVIEW_REQUIRED" else ["검증 실패"],
                checks={"ok": status == "REVIEW_REQUIRED"},
            )
        return build

    def _builders(self, failing_key: str | None = None):
        rows = []
        for key, label, sheet, _builder in pipeline.REGULATORY_BUILDERS:
            status = "VALIDATION_FAILED" if key == failing_key else "REVIEW_REQUIRED"
            rows.append((key, label, sheet, self._builder(key, status=status)))
        return tuple(rows)

    def test_single_refresh_updates_attachment_only_tables_after_all_validations_pass(self):
        law_rows = self._law_rows()
        evidence = [{"status": "ARCHIVED", "message": "ok"} for _ in range(5)]
        approvals = {key: {"status": "APPROVED", "message": "ok"} for key, *_ in pipeline.REGULATORY_BUILDERS}

        with (
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders()),
            patch.object(pipeline, "run_law_monitor", return_value=law_rows),
            patch.object(
                pipeline,
                "decision_readiness_gate",
                side_effect=[
                    {"decision": "HOLD", "blockers": ["old"]},
                    {"decision": "ALLOW", "blockers": [], "message": "ready"},
                ],
            ),
            patch.object(
                pipeline,
                "approve_latest_observation",
                return_value={"status": "APPROVED", "approved": 1, "message": "law ok"},
            ) as law_approve,
            patch.object(pipeline, "approve_candidate", side_effect=lambda key: approvals[key]) as db_approve,
            patch.object(pipeline, "sync_approved_evidence", return_value=evidence) as sync_evidence,
            patch.object(
                pipeline,
                "_build_current_excel_snapshot",
                return_value={"status": "WRITTEN", "file": "data/legal_archive/current/current.xlsx"},
            ),
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            result = pipeline.refresh_all_legal_assets()

        self.assertEqual(result["status"], "UPDATED")
        self.assertEqual(len(result["candidate_results"]), 5)
        self.assertEqual(len(result["db_approvals"]), 5)
        law_approve.assert_called_once_with(["CAP_QTY"])
        self.assertEqual(db_approve.call_count, 5)
        sync_evidence.assert_called_once()
        self.assertEqual(result["readiness"]["decision"], "ALLOW")

    def test_real_legal_metadata_revision_downloads_and_validates_but_does_not_auto_approve_rules(self):
        law_rows = self._law_rows()
        law_rows[0]["change_reason"] = [
            "시행일: 2026-04-22 → 2027-01-01",
            "공포·발령번호: 제2026-7호 → 제2027-1호",
        ]
        with (
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders()),
            patch.object(pipeline, "run_law_monitor", return_value=law_rows),
            patch.object(pipeline, "decision_readiness_gate", return_value={"decision": "HOLD", "blockers": []}),
            patch.object(pipeline, "approve_latest_observation") as law_approve,
            patch.object(pipeline, "approve_candidate") as db_approve,
            patch.object(pipeline, "sync_approved_evidence") as sync_evidence,
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            result = pipeline.refresh_all_legal_assets()

        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(result.get("requires_program_rule_review"))
        self.assertTrue(any("프로그램 규칙 매핑 검토" in blocker for blocker in result["blockers"]))
        # New official originals/candidates were fetched/built, but the approved
        # legal baseline and decision DB are untouched until deterministic logic
        # is reviewed against the amended provisions.
        self.assertEqual(len(result["candidate_results"]), 5)
        law_approve.assert_not_called()
        db_approve.assert_not_called()
        sync_evidence.assert_not_called()

    def test_non_mapped_attachment_change_does_not_silently_promote_old_logic(self):
        law_rows = self._law_rows(status="CURRENT")
        law_rows.append(
            {
                "key": "CAP_DRAFT",
                "title": "화학사고예방관리계획서 작성 등에 관한 규정",
                "monitor_status": "UPDATE_PENDING",
                "monitor_status_ko": "변경 감지·재반영 필요",
                "observation_valid": True,
                "attachment_file_count": 2,
                "attachment_files": [{"format": "PDF"}, {"format": "HWPX"}],
                "change_reason": ["첨부파일 내용 변경: 별지6"],
            }
        )
        with (
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders()),
            patch.object(pipeline, "run_law_monitor", return_value=law_rows),
            patch.object(pipeline, "decision_readiness_gate", return_value={"decision": "HOLD", "blockers": []}),
            patch.object(pipeline, "approve_latest_observation") as law_approve,
            patch.object(pipeline, "approve_candidate") as db_approve,
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            result = pipeline.refresh_all_legal_assets()

        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("작성 등에 관한 규정" in blocker for blocker in result["blockers"]))
        law_approve.assert_not_called()
        db_approve.assert_not_called()

    def test_parser_failure_stops_before_any_approval(self):
        law_rows = self._law_rows()
        with (
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders(failing_key="CAP_QTY_APP2")),
            patch.object(pipeline, "run_law_monitor", return_value=law_rows),
            patch.object(pipeline, "decision_readiness_gate", return_value={"decision": "HOLD", "blockers": []}),
            patch.object(pipeline, "approve_latest_observation") as law_approve,
            patch.object(pipeline, "approve_candidate") as db_approve,
            patch.object(pipeline, "sync_approved_evidence") as sync_evidence,
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            result = pipeline.refresh_all_legal_assets()

        self.assertEqual(result["status"], "HOLD")
        self.assertTrue(any("별표 2" in blocker for blocker in result["blockers"]))
        law_approve.assert_not_called()
        db_approve.assert_not_called()
        sync_evidence.assert_not_called()

    def test_no_change_and_ready_skips_expensive_rebuild(self):
        law_rows = self._law_rows(status="CURRENT")
        for row in law_rows:
            row["monitor_status"] = "CURRENT"
            row["monitor_status_ko"] = "최신·반영본 일치"
            row["change_reason"] = []

        with (
            patch.object(pipeline, "run_law_monitor", return_value=law_rows),
            patch.object(pipeline, "decision_readiness_gate", return_value={"decision": "ALLOW", "blockers": []}),
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders()),
            patch.object(
                pipeline,
                "_build_current_excel_snapshot",
                return_value={"status": "WRITTEN", "file": "data/legal_archive/current/current.xlsx"},
            ) as excel,
            patch.object(pipeline, "approve_latest_observation") as law_approve,
            patch.object(pipeline, "approve_candidate") as db_approve,
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            result = pipeline.refresh_all_legal_assets()

        self.assertEqual(result["status"], "CURRENT")
        excel.assert_called_once()
        law_approve.assert_not_called()
        db_approve.assert_not_called()


if __name__ == "__main__":
    unittest.main()
