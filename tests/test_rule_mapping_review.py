from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine.legal_update_pipeline as pipeline
from engine import rule_mapping_review as rmr
from engine.regulatory_tables import CandidateResult


def _row(**changes):
    row = {
        "key": "CAP_DECREE", "title": "화학물질관리법 시행령", "monitor_status": "UPDATE_PENDING",
        "observation_valid": True, "serial": "290837", "effective_date": "20261008",
        "issue_date": "20261006", "issue_number": "36744", "attachment_hashes": {"본문::HTML": "h1"},
        "change_reason": ["시행일: 20251223 → 20261008"],
    }
    row.update(changes)
    return row


class ReviewRecordTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "reviews.json"
        self.addCleanup(self._tmp.cleanup)

    def test_review_applies_only_to_the_exact_reviewed_edition(self):
        row = _row()
        self.assertFalse(rmr.is_reviewed(row, self.path))
        result = rmr.record_reviews([row], reviewer="홍길동", memo="조문 대조", path=self.path, now="2026-10-19")
        self.assertEqual((result["status"], result["recorded"]), ("RECORDED", 1))
        self.assertTrue(rmr.is_reviewed(row, self.path))
        saved = json.loads(self.path.read_text(encoding="utf-8"))["reviews"]["CAP_DECREE"]
        self.assertEqual((saved["reviewer"], saved["memo"], saved["reviewed_at_utc"]), ("홍길동", "조문 대조", "2026-10-19"))
        # 다음 개정(일련번호·시행일 변경)이나 첨부 해시 변경은 다시 검토해야 한다
        self.assertFalse(rmr.is_reviewed(_row(serial="291000"), self.path))
        self.assertFalse(rmr.is_reviewed(_row(effective_date="20270101"), self.path))
        self.assertFalse(rmr.is_reviewed(_row(attachment_hashes={"본문::HTML": "h2"}), self.path))
        self.assertFalse(rmr.is_reviewed(_row(key="CAP_RULE"), self.path))

    def test_reviewer_name_is_required(self):
        result = rmr.record_reviews([_row()], reviewer="  ", path=self.path)
        self.assertEqual((result["status"], result["recorded"]), ("REVIEWER_REQUIRED", 0))
        self.assertFalse(self.path.exists())

    def test_record_without_reviewer_in_file_is_not_trusted(self):
        row = _row()
        rmr.record_reviews([row], reviewer="홍길동", path=self.path)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["reviews"]["CAP_DECREE"]["reviewer"] = ""
        self.path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertFalse(rmr.is_reviewed(row, self.path))

    def test_corrupt_file_means_not_reviewed(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertFalse(rmr.is_reviewed(_row(), self.path))


class PipelineUsesReviewTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "reviews.json"
        self.addCleanup(self._tmp.cleanup)

    @staticmethod
    def _builders():
        def build_for(key):
            return lambda: CandidateResult(key=key, status="REVIEW_REQUIRED", row_count=1, source_file="s",
                                           candidate_file="c", messages=["ok"], checks={"ok": True})
        return tuple((k, l, s, build_for(k)) for k, l, s, _b in pipeline.REGULATORY_BUILDERS)

    def test_requirement_clears_only_after_review_is_recorded(self):
        row = _row()
        with patch.object(rmr, "REVIEW_FILE", self.path):
            self.assertTrue(pipeline.requires_rule_mapping_review(row))
            rmr.record_reviews([row], reviewer="홍길동")
            self.assertFalse(pipeline.requires_rule_mapping_review(row))
            self.assertTrue(pipeline.requires_rule_mapping_review(_row(serial="999")))

    def test_reviewed_revision_goes_through_normal_approval_and_is_audited(self):
        row = _row()
        approvals = {k: {"status": "APPROVED", "message": "ok"} for k, *_ in pipeline.REGULATORY_BUILDERS}
        with (
            patch.object(rmr, "REVIEW_FILE", self.path),
            patch.object(pipeline, "REGULATORY_BUILDERS", self._builders()),
            patch.object(pipeline, "run_law_monitor", return_value=[row]),
            patch.object(pipeline, "decision_readiness_gate",
                         side_effect=[{"decision": "HOLD", "blockers": []}] * 2 + [{"decision": "ALLOW", "blockers": []}]),
            patch.object(pipeline, "approve_latest_observation",
                         return_value={"status": "APPROVED", "approved": 1, "message": "ok"}) as law_approve,
            patch.object(pipeline, "approve_candidate", side_effect=lambda key: approvals[key]),
            patch.object(pipeline, "sync_approved_evidence", return_value=[{"status": "ARCHIVED"}] * 5),
            patch.object(pipeline, "_build_current_excel_snapshot", return_value={"status": "WRITTEN", "file": "x"}),
            patch.object(pipeline, "_write_report", side_effect=lambda payload: payload),
        ):
            blocked = pipeline.refresh_all_legal_assets()
            self.assertEqual(blocked["status"], "HOLD")
            law_approve.assert_not_called()
            rmr.record_reviews([row], reviewer="홍길동", memo="대조 완료")
            result = pipeline.refresh_all_legal_assets()
        self.assertEqual(result["status"], "UPDATED")
        law_approve.assert_called_once_with(["CAP_DECREE"])
        self.assertEqual(result["rule_mapping_reviews"][0]["reviewer"], "홍길동")


class ReviewPanelTests(unittest.TestCase):
    def test_update_page_offers_review_form_for_pending_amendments(self):
        source = (Path(__file__).resolve().parents[1] / "ui/regdb_page.py").read_text(encoding="utf-8")
        self.assertIn("규칙 매핑 검토가 필요한 개정", source)
        self.assertIn("record_reviews", source)
        self.assertIn("확인자 이름", source)


if __name__ == "__main__":
    unittest.main()
