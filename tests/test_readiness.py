from __future__ import annotations

import unittest
from unittest.mock import patch

from engine.readiness import evaluate_decision_readiness


class DecisionReadinessTests(unittest.TestCase):
    def _law_rows(self):
        return [
            {
                "key": "PSM_DECREE",
                "monitor_status": "CURRENT",
                "attachment_hashes": {"별표13": "psmhash"},
            },
            {
                "key": "CAP_QTY",
                "monitor_status": "CURRENT",
                "attachment_hashes": {
                    "별표1": "cap1hash",
                    "별표2": "cap2hash",
                    "별표3": "cap3hash",
                    "별표4": "cap4hash",
                },
            },
        ]

    def test_all_current_and_hash_matched_allows_decision(self):
        provenance = [
            {"key": "PSM_ANNEX13", "label": "PSM 별표13", "law_key": "PSM_DECREE", "approved_exists": True, "source_hash": "psmhash", "audit_hash": "psmhash", "evidence_hash": ""},
            {"key": "CAP_QTY_APP1", "label": "CAP 별표1", "law_key": "CAP_QTY", "approved_exists": True, "source_hash": "cap1hash", "audit_hash": "cap1hash", "evidence_hash": ""},
        ]
        result = evaluate_decision_readiness(self._law_rows(), provenance)
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["blockers"], [])

    def test_just_approved_identical_observation_is_effectively_current_without_second_api_run(self):
        law_rows = [
            {
                "key": "CAP_QTY",
                "monitor_status": "UPDATE_PENDING",
                "monitor_status_ko": "변경 감지·재반영 필요",
                "observation_valid": True,
                "attachment_hashes": {"별표1::PDF": "cap1hash"},
            }
        ]
        provenance = [
            {"key": "CAP_QTY_APP1", "label": "CAP 별표1", "law_key": "CAP_QTY", "approved_exists": True, "source_hash": "cap1hash", "audit_hash": "cap1hash", "evidence_hash": ""},
        ]
        with patch("engine.readiness.approved_source_is_current", return_value=True):
            result = evaluate_decision_readiness(law_rows, provenance)
        self.assertEqual(result["decision"], "ALLOW")
        self.assertEqual(result["blockers"], [])

    def test_source_hash_mismatch_holds(self):
        provenance = [
            {"key": "PSM_ANNEX13", "label": "PSM 별표13", "law_key": "PSM_DECREE", "approved_exists": True, "source_hash": "oldhash", "audit_hash": "oldhash", "evidence_hash": ""},
        ]
        result = evaluate_decision_readiness(self._law_rows(), provenance)
        self.assertEqual(result["decision"], "HOLD")
        self.assertTrue(any("일치하지 않습니다" in value for value in result["blockers"]))

    def test_missing_approved_db_holds(self):
        provenance = [
            {"key": "CAP_QTY_APP4", "label": "CAP 별표4", "law_key": "CAP_QTY", "approved_exists": False, "source_hash": "", "audit_hash": "", "evidence_hash": ""},
        ]
        result = evaluate_decision_readiness(self._law_rows(), provenance)
        self.assertEqual(result["decision"], "HOLD")
        self.assertTrue(any("승인 DB가 없습니다" in value for value in result["blockers"]))

    def test_audit_and_archive_hash_disagreement_holds(self):
        provenance = [
            {"key": "CAP_QTY_APP2", "label": "CAP 별표2", "law_key": "CAP_QTY", "approved_exists": True, "source_hash": "cap2hash", "audit_hash": "cap2hash", "evidence_hash": "different"},
        ]
        result = evaluate_decision_readiness(self._law_rows(), provenance)
        self.assertEqual(result["decision"], "HOLD")
        self.assertTrue(any("서로 다릅니다" in value for value in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
