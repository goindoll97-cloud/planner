from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO

import engine.law_attachment_archive as archive


class LegalAttachmentArchiveTests(unittest.TestCase):
    @staticmethod
    def _hwpx_bytes() -> bytes:
        buf = BytesIO()
        with ZipFile(buf, "w", ZIP_DEFLATED) as zf:
            zf.writestr("mimetype", "application/hwp+zip")
            zf.writestr("Contents/section0.xml", "<hp:t>별지 제1호서식</hp:t>")
        return buf.getvalue()

    def test_detects_pdf_hwp_and_hwpx_from_bytes(self):
        self.assertEqual(archive.detect_official_attachment_format(b"%PDF-1.7\n"), "pdf")
        self.assertEqual(
            archive.detect_official_attachment_format(bytes.fromhex("D0CF11E0A1B11AE1") + b"legacy"),
            "hwp",
        )
        self.assertEqual(archive.detect_official_attachment_format(self._hwpx_bytes()), "hwpx")

    def test_pending_save_keeps_actual_hwpx_even_when_api_field_is_hwp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = root / "data" / "runtime" / "law_pending"
            with patch.object(archive, "PROJECT_ROOT", root), patch.object(archive, "PENDING_ATTACHMENT_DIR", pending):
                meta = archive.save_pending_attachment(
                    source_key="CAP_DRAFT",
                    item_id="별지1 작성수준",
                    declared_kind="hwp",
                    url="https://www.law.go.kr/file.do?id=1",
                    content=self._hwpx_bytes(),
                )
                self.assertEqual(meta["format"], "HWPX")
                self.assertTrue(meta["pending_file"].endswith(".hwpx"))
                self.assertTrue((root / meta["pending_file"]).exists())

    def test_approved_source_archive_versions_exact_official_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pending = root / "data" / "runtime" / "law_pending"
            approved_root = root / "data" / "legal_archive" / "sources"
            monitor_file = root / "data" / "runtime" / "law_monitor_approved.json"
            with (
                patch.object(archive, "PROJECT_ROOT", root),
                patch.object(archive, "PENDING_ATTACHMENT_DIR", pending),
                patch.object(archive, "APPROVED_SOURCE_ROOT", approved_root),
                patch.object(archive, "APPROVED_MONITOR_FILE", monitor_file),
            ):
                pdf = archive.save_pending_attachment(
                    source_key="CAP_DRAFT",
                    item_id="별지1",
                    declared_kind="pdf",
                    url="https://www.law.go.kr/a.pdf",
                    content=b"%PDF-1.7 test",
                )
                hwpx = archive.save_pending_attachment(
                    source_key="CAP_DRAFT",
                    item_id="별지1",
                    declared_kind="hwp",
                    url="https://www.law.go.kr/a.hwpx",
                    content=self._hwpx_bytes(),
                )
                row = {
                    "key": "CAP_DRAFT",
                    "regime": "화학사고예방관리계획서",
                    "title": "화학사고예방관리계획서 작성 등에 관한 규정",
                    "target": "admrul",
                    "serial": "12345",
                    "effective_date": "2026-04-22",
                    "issue_number": "제2026-7호",
                    "attachment_required": True,
                    "attachment_files": [pdf, hwpx],
                }
                result = archive.archive_approved_source(row)
                self.assertEqual(result["status"], "ARCHIVED")
                self.assertEqual(len(result["files"]), 2)
                folder = root / result["archive_folder"]
                self.assertTrue((folder / "manifest.json").exists())
                manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
                self.assertEqual({x["format"] for x in manifest["attachment_files"]}, {"PDF", "HWPX"})

                # Once the approved monitor snapshot points to the archive, the
                # report/template layer can resolve the exact current HWPX.
                monitor_file.parent.mkdir(parents=True, exist_ok=True)
                monitor_file.write_text(
                    json.dumps({"sources": {"CAP_DRAFT": {"approved_archive": result}}}, ensure_ascii=False),
                    encoding="utf-8",
                )
                files = archive.approved_source_files("CAP_DRAFT", {".hwpx"})
                self.assertEqual(len(files), 1)
                self.assertTrue(files[0].exists())


if __name__ == "__main__":
    unittest.main()
