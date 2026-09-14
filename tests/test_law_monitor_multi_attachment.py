from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

import engine.law_attachment_archive as archive
import engine.law_monitor as monitor


class LawMonitorMultiAttachmentTests(unittest.TestCase):
    @staticmethod
    def _hwpx() -> bytes:
        buf = BytesIO()
        with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/hwp+zip")
            zf.writestr("Contents/section0.xml", "<hp:t>별지 제1호서식</hp:t>")
        return buf.getvalue()

    def test_monitor_downloads_pdf_and_hwp_representation_and_approval_archives_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "data" / "runtime"
            pending = runtime / "law_pending"
            approved_root = root / "data" / "legal_archive" / "sources"
            observed_file = runtime / "law_monitor_last_observed.json"
            approved_file = runtime / "law_monitor_approved.json"

            source = monitor.LawSource(
                key="CAP_DRAFT",
                regime="화학사고예방관리계획서",
                title="화학사고예방관리계획서 작성 등에 관한 규정",
                target="admrul",
                attachment_required=True,
                attachment_selector={"mode": "all"},
            )
            found = {
                "api_status": "FOUND",
                "title": source.title,
                "serial": "100",
                "stable_id": "CAP-X",
                "issue_date": "20260409",
                "issue_number": "제2026-7호",
                "effective_date": "20260422",
                "revision_type": "일부개정",
                "ministry": "화학물질안전원",
            }
            attachments = [{
                "appendix_no": "1",
                "appendix_branch": "",
                "appendix_kind": "별지",
                "appendix_title": "사업장의 작성수준 구분",
                "pdf_url": "https://www.law.go.kr/form.pdf",
                # API field name is historically HWP, but bytes may be HWPX.
                "hwp_url": "https://www.law.go.kr/form-file",
            }]

            def download(url: str, timeout: int = 90) -> bytes:
                return b"%PDF-1.7 official" if url.endswith(".pdf") else self._hwpx()

            with (
                patch.object(monitor, "PROJECT_ROOT", root),
                patch.object(monitor, "OBSERVED_FILE", observed_file),
                patch.object(monitor, "APPROVED_FILE", approved_file),
                patch.object(monitor, "load_registry", return_value=(source,)),
                patch.object(monitor, "search_current_source", return_value=found),
                patch.object(monitor, "fetch_source_payload", return_value={"ok": True}),
                patch.object(monitor, "extract_attachments", return_value=attachments),
                patch.object(monitor, "download_binary", side_effect=download),
                patch.object(monitor, "credential_status", return_value={"status": "READY"}),
                patch.object(archive, "PROJECT_ROOT", root),
                patch.object(archive, "PENDING_ATTACHMENT_DIR", pending),
                patch.object(archive, "APPROVED_SOURCE_ROOT", approved_root),
                patch.object(archive, "APPROVED_MONITOR_FILE", approved_file),
                patch.object(archive, "OBSERVED_MONITOR_FILE", observed_file),
            ):
                rows = monitor.run_law_monitor()
                self.assertEqual(len(rows), 1)
                row = rows[0]
                self.assertTrue(row["observation_valid"])
                self.assertEqual(row["monitor_status"], "BASELINE_UNAPPROVED")
                self.assertEqual(row["attachment_file_count"], 2)
                self.assertEqual({x["format"] for x in row["attachment_files"]}, {"PDF", "HWPX"})
                self.assertEqual(len(row["pending_pdf_files"]), 1)

                approval = monitor.approve_latest_observation(["CAP_DRAFT"])
                self.assertEqual(approval["status"], "APPROVED")
                self.assertEqual(approval["archived_sources"], 1)
                snapshot = json.loads(approved_file.read_text(encoding="utf-8"))["sources"]["CAP_DRAFT"]
                self.assertEqual(snapshot["approved_archive"]["status"], "ARCHIVED")
                self.assertEqual(
                    {x["format"] for x in snapshot["approved_archive"]["files"]},
                    {"PDF", "HWPX"},
                )


if __name__ == "__main__":
    unittest.main()
