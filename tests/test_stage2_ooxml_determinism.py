from __future__ import annotations

from io import BytesIO
import unittest
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from engine.stage2.ooxml_determinism import (
    FIXED_ZIP_DATETIME,
    canonicalize_docx_zip,
)


class OOXMLDeterminismTests(unittest.TestCase):
    @staticmethod
    def _docx(order: tuple[str, ...], timestamp: tuple[int, int, int, int, int, int]) -> bytes:
        payloads = {
            "[Content_Types].xml": b"<Types/>",
            "word/document.xml": b"<document><body>same</body></document>",
            "word/styles.xml": b"<styles/>",
        }
        out = BytesIO()
        with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
            for name in order:
                info = ZipInfo(name, timestamp)
                info.compress_type = ZIP_DEFLATED
                archive.writestr(info, payloads[name])
        return out.getvalue()

    def test_different_zip_metadata_converges_to_identical_bytes(self):
        names = (
            "[Content_Types].xml",
            "word/document.xml",
            "word/styles.xml",
        )
        first = self._docx(names, (2026, 9, 18, 12, 0, 0))
        second = self._docx(tuple(reversed(names)), (2026, 9, 18, 13, 5, 2))
        self.assertNotEqual(first, second)

        canonical_first = canonicalize_docx_zip(first)
        canonical_second = canonicalize_docx_zip(second)

        self.assertEqual(canonical_first, canonical_second)
        self.assertEqual(canonicalize_docx_zip(canonical_first), canonical_first)

        with ZipFile(BytesIO(canonical_first), "r") as archive:
            self.assertEqual(archive.namelist(), sorted(names))
            self.assertTrue(all(info.date_time == FIXED_ZIP_DATETIME for info in archive.infolist()))
            self.assertEqual(archive.read("word/document.xml"), b"<document><body>same</body></document>")

    def test_missing_required_docx_member_fails_closed(self):
        out = BytesIO()
        with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", b"<Types/>")

        with self.assertRaisesRegex(ValueError, "word/document.xml"):
            canonicalize_docx_zip(out.getvalue())

    def test_invalid_zip_fails_closed(self):
        with self.assertRaises(ValueError):
            canonicalize_docx_zip(b"not-a-docx")


if __name__ == "__main__":
    unittest.main()
