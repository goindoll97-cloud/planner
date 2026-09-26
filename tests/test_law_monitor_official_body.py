from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import engine.law_attachment_archive as archive
import engine.law_monitor as monitor
import engine.legal_update_pipeline as pipeline
import engine.law_api as law_api


class OfficialBodyTests(unittest.TestCase):
    def test_official_html_response_must_contain_expected_title_and_article(self):
        title = "유해화학물질의 영업허가 등에 관한 규정"
        valid = ("<html><body>" + title + " 제1조(목적) " + "본문 내용 " * 50 + "</body></html>").encode("utf-8")
        class Response:
            content = valid
            def raise_for_status(self):
                pass
        with patch.object(law_api, "get_api_credential", return_value=("test", "test")), patch.object(law_api.requests, "get", return_value=Response(), create=True):
            self.assertEqual(law_api.fetch_source_body_html({"api_status": "FOUND", "serial": "2100000278914"}, title), valid)
            with self.assertRaises(ValueError):
                law_api.fetch_source_body_html({"api_status": "FOUND", "serial": "2100000278914"}, "다른 고시")

    def test_no_appendix_notice_archives_body_and_detects_later_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "data" / "runtime"
            observed = runtime / "law_monitor_last_observed.json"
            approved = runtime / "law_monitor_approved.json"
            (root / "data").mkdir(exist_ok=True)
            (root / "data" / "law_registry.json").write_text(json.dumps([{
                "key": "CAP_BUSINESS_NOTICE", "title": "유해화학물질의 영업허가 등에 관한 규정",
                "regime": "화학사고예방관리계획서", "target": "admrul", "body_required": True,
            }], ensure_ascii=False), encoding="utf-8")
            source = monitor.LawSource(
                key="CAP_BUSINESS_NOTICE", regime="화학사고예방관리계획서",
                title="유해화학물질의 영업허가 등에 관한 규정", target="admrul", body_required=True,
            )
            found = {
                "api_status": "FOUND", "serial": "2100000278914", "effective_date": "20260511",
                "issue_date": "20260511", "issue_number": "제2026-113호",
            }
            body = b"<html><body>official regulation version one</body></html>"
            with (
                patch.object(monitor, "PROJECT_ROOT", root),
                patch.object(monitor, "OBSERVED_FILE", observed),
                patch.object(monitor, "APPROVED_FILE", approved),
                patch.object(monitor, "load_registry", return_value=(source,)),
                patch.object(monitor, "search_current_source", return_value=found),
                patch.object(monitor, "fetch_source_payload", return_value={}),
                patch.object(monitor, "fetch_source_body_html", return_value=body) as fetch_body,
                patch.object(monitor, "credential_status", return_value={}),
                patch.object(archive, "PROJECT_ROOT", root),
                patch.object(archive, "PENDING_ATTACHMENT_DIR", runtime / "law_pending"),
                patch.object(archive, "APPROVED_SOURCE_ROOT", root / "data" / "legal_archive" / "sources"),
                patch.object(archive, "APPROVED_MONITOR_FILE", approved),
                patch.object(archive, "OBSERVED_MONITOR_FILE", observed),
            ):
                first = monitor.run_law_monitor()[0]
                self.assertTrue(first["observation_valid"])
                self.assertEqual(first["monitor_status"], "BASELINE_UNAPPROVED")
                self.assertEqual(first["attachment_hashes"]["본문::HTML"], archive.bytes_sha256(body))
                self.assertEqual(first["attachment_files"][0]["format"], "HTML")
                self.assertEqual(monitor.approve_latest_observation([source.key])["status"], "APPROVED")
                library = archive.approved_source_library()
                self.assertEqual(library[0]["status"], "최신 확인")
                self.assertEqual(len(library[0]["files"]), 1)
                self.assertEqual((root / library[0]["files"][0]["path"]).read_bytes(), body)
                self.assertEqual(monitor.run_law_monitor()[0]["monitor_status"], "CURRENT")
                fetch_body.return_value = b"<html><body>official regulation version two</body></html>"
                changed = monitor.run_law_monitor()[0]
                self.assertEqual(changed["monitor_status"], "UPDATE_PENDING")
                self.assertIn("본문::HTML", " ".join(changed["change_reason"]))
                self.assertFalse(archive.approved_source_is_current(source.key))

    def test_failed_body_never_becomes_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = monitor.LawSource(
                key="CAP_BUSINESS_NOTICE", regime="CAP", title="영업허가 규정",
                target="admrul", body_required=True,
            )
            with (
                patch.object(monitor, "OBSERVED_FILE", root / "observed.json"),
                patch.object(monitor, "APPROVED_FILE", root / "approved.json"),
                patch.object(monitor, "load_registry", return_value=(source,)),
                patch.object(monitor, "search_current_source", return_value={"api_status": "FOUND", "serial": "1"}),
                patch.object(monitor, "fetch_source_payload", return_value={}),
                patch.object(monitor, "fetch_source_body_html", side_effect=ValueError("본문 확인 실패")),
                patch.object(monitor, "credential_status", return_value={}),
            ):
                row = monitor.run_law_monitor()[0]
                self.assertFalse(row["observation_valid"])
                self.assertEqual(row["monitor_status"], "UNVERIFIED")

    def test_adding_body_to_same_approved_version_is_migration_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "approved.json"
            baseline.write_text(json.dumps({"sources": {"CAP_BUSINESS_NOTICE": {
                "attachment_hashes": {}, "serial": "2100000278914",
            }}}), encoding="utf-8")
            with patch.object(pipeline, "APPROVED_FILE", baseline):
                row = {
                    "key": "CAP_BUSINESS_NOTICE", "monitor_status": "UPDATE_PENDING",
                    "attachment_hashes": {"본문::HTML": "official-hash"},
                    "change_reason": ["첨부파일 추가: 본문::HTML"],
                }
                self.assertFalse(pipeline._requires_rule_mapping_review(row))
                row["change_reason"] = ["첨부파일 변경: 본문::HTML"]
                self.assertTrue(pipeline._requires_rule_mapping_review(row))
                row["change_reason"] = ["법령/행정규칙 일련번호: old → new", "첨부파일 추가: 본문::HTML"]
                self.assertTrue(pipeline._requires_rule_mapping_review(row))


if __name__ == "__main__":
    unittest.main()
