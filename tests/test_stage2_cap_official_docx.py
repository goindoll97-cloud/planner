from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from engine.stage2 import cap_hwpx
from engine.stage2.cap_official_docx import (
    _convert_one_hwpx_to_docx,
    _is_hwpx,
    build_cap_official_word,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fake_hwpx() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("Contents/section0.xml", "<section><t>별지</t></section>")
        zf.writestr("mimetype", "application/hwp+zip")
    return out.getvalue()


def _fake_docx() -> bytes:
    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<document/>")
    return out.getvalue()


class _Project:
    project_id = "CAP-WORD-TEST"
    company_name = "테스트화학"


class CAPOfficialWordTests(unittest.TestCase):
    def test_hwpx_is_distinguished_from_outer_bundle_zip(self):
        self.assertTrue(_is_hwpx(_fake_hwpx()))
        outer = BytesIO()
        with ZipFile(outer, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("별지1_작성본.hwpx", _fake_hwpx())
        self.assertFalse(_is_hwpx(outer.getvalue()))

    def test_hancom_export_uses_ooxml_docx_format(self):
        calls: dict[str, object] = {}

        class FakeHwp:
            def __init__(self, visible=False):
                calls["visible"] = visible

            def open(self, path, format=""):
                calls["open_format"] = format
                return True

            def save_as(self, path, format="", arg=""):
                calls["save_format"] = format
                calls["save_arg"] = arg
                Path(path).write_bytes(_fake_docx())
                return True

            def quit(self):
                calls["quit"] = True

        fake_module = types.SimpleNamespace(Hwp=FakeHwp)
        with patch("engine.stage2.cap_official_docx.platform.system", return_value="Windows"), patch.dict(
            sys.modules, {"pyhwpx": fake_module}
        ):
            data = _convert_one_hwpx_to_docx(_fake_hwpx(), "별지1")

        self.assertTrue(data.startswith(b"PK"))
        self.assertEqual(calls["open_format"], "HWPX")
        self.assertEqual(calls["save_format"], "OOXML")
        self.assertIn("export", str(calls["save_arg"]))
        self.assertTrue(calls["quit"])

    def test_split_official_forms_become_docx_zip_without_redrawing(self):
        outer = BytesIO()
        with ZipFile(outer, "w", compression=ZIP_DEFLATED) as zf:
            zf.writestr("별지1_작성본.hwpx", _fake_hwpx())
            zf.writestr("별지3_작성본.hwpx", _fake_hwpx())
            zf.writestr("원본서식_자동작성_안내.txt", "official")
        written = cap_hwpx.CAPHwpxBuildResult(
            data=outer.getvalue(),
            applied_count=2,
            warnings=(),
            template_sha256="0" * 64,
        )
        with patch.object(cap_hwpx, "build_cap_hwpx_draft", return_value=written), patch(
            "engine.stage2.cap_official_docx._convert_one_hwpx_to_docx", return_value=_fake_docx()
        ):
            result = build_cap_official_word(_Project())

        self.assertTrue(result.file_name.endswith(".zip"))
        self.assertEqual(result.form_count, 2)
        with ZipFile(BytesIO(result.data), "r") as zf:
            names = set(zf.namelist())
        self.assertIn("별지1_작성본.docx", names)
        self.assertIn("별지3_작성본.docx", names)
        self.assertIn("Word변환본_안내.txt", names)

    def test_cap_official_docx_module_no_longer_exposes_word_conversion_ui(self):
        # The Word-conversion helpers (build_cap_official_word etc.) are kept
        # for internal/explicit use, but Stage 5's own review-DOCX labeling now
        # lives directly in ui/stage2_review_page.py instead of a st.markdown/
        # st.download_button monkeypatch installed from this module.
        text = (PROJECT_ROOT / "engine/stage2/cap_official_docx.py").read_text(encoding="utf-8")
        self.assertNotIn("법제처 원본서식 Word 변환본 만들기", text)
        self.assertNotIn("render_official_word_ui", text)
        self.assertNotIn("install_cap_official_word_runtime", text)

    def test_stage5_uses_cap_docx_as_final_facing_output(self):
        text = (PROJECT_ROOT / "ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn("### 화학사고예방관리계획서 · 규정서식 작성본", text)
        self.assertIn("### 화학사고예방관리계획서 · 내부 검토용", text)
        self.assertIn("### 공정안전보고서 · 내부 검토용", text)
        self.assertIn("화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드", text)
        self.assertIn("내부 검토용 DOCX 다운로드", text)
        self.assertIn("build_cap_baseline_draft", text)
        self.assertIn("AI 문장 검토용 내부 DOCX", text)
        self.assertNotIn("법제처 원본서식 HWPX", text)


if __name__ == "__main__":
    unittest.main()
