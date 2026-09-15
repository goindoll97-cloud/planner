from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2.project import Stage2Project
from engine.stage2.psm_baseline_docx import (
    build_psm_baseline_draft,
    load_psm_baseline_bytes,
    psm_baseline_filename,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = "7432f9b266c5e8ea0e5c02fe0e5ce74ffdbfd3774c16e8be58c7b1f8546c1419"


def _project() -> Stage2Project:
    project = Stage2Project(
        project_id="PSM-BASELINE-TEST",
        company_name="세계화학(주) 충주공장",
        psm_required=True,
        cap_required=False,
    )
    project.set_authoring_scope(psm_selected=True, cap_selected=False)
    return project


def _set(project: Stage2Project, key: str, value, label: str | None = None) -> None:
    project.set_field(key, label or key, value, "USER_CONFIRMED")


class PSMBaselineDocxTests(unittest.TestCase):
    def test_baseline_bytes_match_uploaded_layout_snapshot(self):
        template_dir = PROJECT_ROOT / "data" / "templates" / "psm"
        encoded = "".join(
            path.read_text(encoding="ascii").strip()
            for path in sorted(template_dir.glob("psm_statutory_forms_baseline.docx.b64.*"))
        )
        raw = base64.b64decode(encoded, validate=True)
        self.assertEqual(
            sha256(raw).hexdigest(),
            EXPECTED_SHA256,
            msg=f"stored_base64_chars={len(encoded)} decoded_bytes={len(raw)}",
        )

        data = load_psm_baseline_bytes()
        self.assertEqual(sha256(data).hexdigest(), EXPECTED_SHA256)
        doc = Document(BytesIO(data))
        self.assertEqual(len(doc.tables), 15)
        text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        for marker in (
            "별지 제12호서식",
            "별지 제13호서식",
            "별지 제17호의2",
            "별지 제19호의2",
            "별지 제21호서식",
        ):
            self.assertIn(marker, text)

    def test_confirmed_business_and_chemical_values_are_written_into_existing_forms(self):
        project = _project()
        _set(project, "psm.business.project_type", "변경")
        _set(project, "business.registration_no", "123-45-67890")
        _set(project, "business.representative", "홍길동")
        _set(project, "psm.business.target_facility", "MIC 반응공정")
        _set(project, "inventory.chemicals", [
            {
                "물질명": "Methyl isocyanate",
                "CAS 번호": "624-83-9",
                "분자식": "C2H3NO",
                "폭발한계 하한": "5.3",
                "폭발한계 상한": "26",
                "인화점": "-7",
                "일일사용량": "100 kg/day",
                "저장량": "500 kg",
            }
        ])

        out = build_psm_baseline_draft(project)
        doc = Document(BytesIO(out))
        self.assertEqual(len(doc.tables), 15)

        form12 = "\n".join(cell.text for row in doc.tables[0].rows for cell in row.cells)
        self.assertIn("세계화학(주) 충주공장", form12)
        self.assertIn("123-45-67890", form12)
        self.assertIn("홍길동", form12)
        self.assertIn("MIC 반응공정", form12)
        self.assertIn("☒ 변경", form12)
        self.assertIn("☐ 설치·이전", form12)

        form13 = "\n".join(cell.text for row in doc.tables[1].rows for cell in row.cells)
        self.assertIn("Methyl isocyanate", form13)
        self.assertIn("624-83-9", form13)
        self.assertIn("C2H3NO", form13)
        self.assertIn("500 kg", form13)

    def test_unconfirmed_values_stay_blank_in_regulation_forms(self):
        project = _project()
        out = build_psm_baseline_draft(project)
        doc = Document(BytesIO(out))
        text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)
        self.assertNotIn("[확인 필요]", text)
        self.assertIn("사업장명:", text)
        self.assertIn("세계화학(주) 충주공장", text)

    def test_psm_regulation_filename_is_distinct_from_internal_review(self):
        name = psm_baseline_filename(_project())
        self.assertTrue(name.endswith("_공정안전보고서_규정서식_작성본.docx"))
        self.assertNotIn("내부", name)

    def test_app_installs_psm_baseline_after_cap_review_label_runtime(self):
        text = (PROJECT_ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_psm_baseline_runtime", text)
        self.assertGreater(
            text.index("install_psm_baseline_runtime()"),
            text.index("install_cap_official_word_runtime()"),
        )
        self.assertLess(
            text.index("install_psm_baseline_runtime()"),
            text.index("install_local_ai_resilience()"),
        )

    def test_stage5_runtime_inserts_regulation_form_before_psm_review_heading(self):
        text = (PROJECT_ROOT / "engine/stage2/psm_baseline_runtime.py").read_text(encoding="utf-8")
        self.assertIn("공정안전보고서 · 규정서식 작성본", text)
        self.assertIn('text == "### 공정안전보고서 · 내부 검토용"', text)
        self.assertIn("공정안전보고서 규정서식 작성본 DOCX 다운로드", text)


if __name__ == "__main__":
    unittest.main()
