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


class BodyFallbackTests(unittest.TestCase):
    """법제처 HTML 응답이 조문이 없는 껍데기일 때: 같은 사이트 프레임 → 공식 XML 순서로 받는다."""

    TITLE = "유해화학물질의 영업허가 등에 관한 규정"
    FOUND = {"api_status": "FOUND", "serial": "2100000278914"}

    @staticmethod
    def _resp(content: bytes):
        class Response:
            def __init__(self, body):
                self.content = body
            def raise_for_status(self):
                pass
        return Response(content)

    def _xml(self) -> bytes:
        return ('<?xml version="1.0" encoding="UTF-8"?><AdmRulService><행정규칙기본정보><행정규칙명>'
                + self.TITLE + "</행정규칙명></행정규칙기본정보><조문내용>제1조(목적) "
                + "이 규정은 " * 80 + "</조문내용></AdmRulService>").encode("utf-8")

    def _get(self, responses):
        calls = []
        def fake_get(url, params=None, timeout=None):
            calls.append((url, dict(params or {})))
            return self._resp(responses.pop(0))
        return fake_get, calls

    def test_wrapper_html_falls_back_to_official_xml(self):
        wrapper = ("<html><head><script>load()</script></head><body>" + " " * 600 + "</body></html>").encode()
        fake_get, calls = self._get([wrapper, self._xml()])
        with patch.object(law_api, "get_api_credential", return_value=("k", "env")), \
             patch.object(law_api.requests, "get", side_effect=fake_get):
            body = law_api.fetch_source_body_html(self.FOUND, self.TITLE)
        self.assertEqual(body, self._xml())
        self.assertEqual([c[1].get("type") for c in calls], ["HTML", "XML"])
        self.assertEqual(law_api.official_body_kind(body), "xml")

    def test_same_site_frame_is_followed_before_xml(self):
        wrapper = ('<html><body><iframe src="/LSW/admRulInfoP.do?admRulSeq=2100000278914&amp;x=1"></iframe>'
                   + " " * 600 + "</body></html>").encode()
        inner = ("<html><body>" + self.TITLE + " 제1조(목적) " + "본문 " * 100 + "</body></html>").encode()
        fake_get, calls = self._get([wrapper, inner])
        with patch.object(law_api, "get_api_credential", return_value=("k", "env")), \
             patch.object(law_api.requests, "get", side_effect=fake_get):
            body = law_api.fetch_source_body_html(self.FOUND, self.TITLE)
        self.assertEqual(body, inner)
        self.assertEqual(calls[1][0], "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000278914&x=1")
        self.assertEqual(law_api.official_body_kind(body), "html")

    def test_other_site_frame_is_not_followed_and_wrong_rule_fails(self):
        wrapper = ('<html><body><iframe src="https://example.com/x"></iframe>' + " " * 600 + "</body></html>").encode()
        wrong_xml = self._xml().replace(self.TITLE.encode(), "다른 고시".encode())
        fake_get, calls = self._get([wrapper, wrong_xml])
        with patch.object(law_api, "get_api_credential", return_value=("k", "env")), \
             patch.object(law_api.requests, "get", side_effect=fake_get):
            with self.assertRaises(ValueError) as ctx:
                law_api.fetch_source_body_html(self.FOUND, self.TITLE)
        self.assertIn("HTML, XML", str(ctx.exception))
        self.assertEqual(len(calls), 2)

    def test_xml_body_is_archived_with_xml_hash_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "data" / "runtime"
            observed, approved = runtime / "law_monitor_last_observed.json", runtime / "law_monitor_approved.json"
            source = monitor.LawSource(key="CAP_BUSINESS_NOTICE", regime="화학사고예방관리계획서",
                                       title=self.TITLE, target="admrul", body_required=True)
            found = {"api_status": "FOUND", "serial": "2100000278914", "effective_date": "20260511",
                     "issue_date": "20260511", "issue_number": "제2026-113호"}
            with (
                patch.object(monitor, "PROJECT_ROOT", root),
                patch.object(monitor, "OBSERVED_FILE", observed),
                patch.object(monitor, "APPROVED_FILE", approved),
                patch.object(monitor, "load_registry", return_value=(source,)),
                patch.object(monitor, "search_current_source", return_value=found),
                patch.object(monitor, "fetch_source_payload", return_value={}),
                patch.object(monitor, "fetch_source_body_html", return_value=self._xml()),
                patch.object(monitor, "credential_status", return_value={}),
                patch.object(archive, "PROJECT_ROOT", root),
                patch.object(archive, "PENDING_ATTACHMENT_DIR", runtime / "law_pending"),
                patch.object(archive, "APPROVED_SOURCE_ROOT", root / "data" / "legal_archive" / "sources"),
                patch.object(archive, "APPROVED_MONITOR_FILE", approved),
                patch.object(archive, "OBSERVED_MONITOR_FILE", observed),
            ):
                row = monitor.run_law_monitor()[0]
        self.assertTrue(row["observation_valid"])
        self.assertIn("본문::XML", row["attachment_hashes"])
        self.assertEqual(row["attachment_files"][0]["format"], "XML")

    def test_switching_body_from_html_to_xml_for_same_version_is_migration_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            baseline = Path(tmp) / "approved.json"
            baseline.write_text(json.dumps({"sources": {"CAP_BUSINESS_NOTICE": {
                "attachment_hashes": {"본문::HTML": "old-html"}, "serial": "2100000278914",
            }}}), encoding="utf-8")
            with patch.object(pipeline, "APPROVED_FILE", baseline):
                row = {
                    "key": "CAP_BUSINESS_NOTICE", "monitor_status": "UPDATE_PENDING",
                    "attachment_hashes": {"본문::XML": "official-xml"},
                    "change_reason": ["첨부파일 삭제/미확인: 본문::HTML", "첨부파일 추가: 본문::XML"],
                }
                self.assertFalse(pipeline._requires_rule_mapping_review(row))
                # 같은 표현(XML)의 본문 내용이 바뀌면 사람 검토
                baseline.write_text(json.dumps({"sources": {"CAP_BUSINESS_NOTICE": {
                    "attachment_hashes": {"본문::XML": "old-xml"}, "serial": "2100000278914"}}}), encoding="utf-8")
                row["change_reason"] = ["첨부파일 내용 변경: 본문::XML (old-xml… → official-xml…)"]
                self.assertTrue(pipeline._requires_rule_mapping_review(row))
                # 실제 개정(발령정보 변경)은 형식 전환과 함께 와도 사람 검토
                row["change_reason"] = ["시행일: 20260511 → 20261201", "첨부파일 추가: 본문::XML"]
                self.assertTrue(pipeline._requires_rule_mapping_review(row))


if __name__ == "__main__":
    unittest.main()
