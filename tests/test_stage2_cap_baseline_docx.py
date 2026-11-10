from __future__ import annotations

import json
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import unittest

from docx import Document

from engine.stage2.project import Stage2Project
from engine.stage2.cap_baseline_docx import (
    form_table_index_for,
    build_cap_baseline_draft,
    cap_baseline_filename,
    load_cap_baseline_bytes,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project() -> Stage2Project:
    project = Stage2Project(
        project_id="CAP-BASELINE-TEST",
        company_name="세계화학(주) 충주공장",
        psm_required=False,
        cap_required=True,
        cap_group="1군",
    )
    project.set_authoring_scope(psm_selected=False, cap_selected=True)
    return project


def _set(project: Stage2Project, key: str, value, label: str | None = None) -> None:
    project.set_field(key, label or key, value, "USER_CONFIRMED")


class CAPBaselineDocxTests(unittest.TestCase):
    def test_only_replacement_260409_template_is_installed(self):
        template_dir = PROJECT_ROOT / "data" / "templates" / "cap"
        self.assertFalse(list(template_dir.glob("cap_statutory_forms_baseline.docx.b64.*")))
        self.assertFalse((template_dir / "cap_statutory_forms_baseline.json").exists())
        meta = json.loads((template_dir / "cap_statutory_forms_260409.json").read_text(encoding="utf-8"))
        data = load_cap_baseline_bytes()
        self.assertEqual(sha256(data).hexdigest(), meta["sha256"])
        self.assertEqual(meta["required_table_count"], 38)
        doc = Document(BytesIO(data))
        self.assertEqual(len(doc.tables), 38)
        text = "\n".join(p.text for p in doc.paragraphs)
        for marker in ("별지 제1호서식", "별지 제6호서식", "별지 제9호서식", "별지 제16호서식"):
            self.assertIn(marker, text)
        # The separate reference tables (previous indexes 0..5) were deleted.
        self.assertIn("단위공장", doc.tables[0].rows[0].cells[0].text)

    def test_missing_new_source_never_falls_back_to_deleted_baseline(self):
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from engine.stage2 import cap_baseline_docx as renderer

        with TemporaryDirectory() as temp:
            with patch.object(renderer, "NEW_TEMPLATE_DIRECT", Path(temp) / "missing_260409.docx"):
                with self.assertRaisesRegex(FileNotFoundError, "이전 서식으로 대체하지 않습니다"):
                    renderer.load_cap_baseline_bytes()

    def test_confirmed_business_and_chemical_values_are_written_into_existing_forms(self):
        project = _project()
        _set(project, "cap.business.representative", "홍길동")
        _set(project, "cap.business.registration_no", "123-45-67890")
        _set(project, "business.address", "충청북도 충주시 테스트로 1")
        _set(project, "inventory.chemicals", [
            {
                "물질명": "Methyl isocyanate",
                "CAS 번호": "624-83-9",
                "물질구분": "사고대비물질",
                "물리적 상태": "액체",
                "함량(%)": "99",
                "최대보유량": "500",
            }
        ])
        _set(project, "psm.psi.equipment_specs", [
            {
                "설비번호": "TK-101",
                "설비명": "MIC 저장탱크",
                "취급물질": "Methyl isocyanate",
                "설계용량": "20",
            }
        ])

        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        self.assertEqual(len(doc.tables), 38)
        text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)

        self.assertIn("홍길동", text)
        self.assertIn("123-45-67890", text)
        self.assertIn("Methyl isocyanate", text)
        self.assertIn("624-83-9", text)
        self.assertIn("TK-101", text)
        self.assertIn("MIC 저장탱크", text)

    def test_unconfirmed_values_stay_blank_and_static_tables_are_untouched(self):
        project = _project()
        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        text = "\n".join(cell.text for table in doc.tables for row in table.rows for cell in row.cells)

        self.assertNotIn("[확인 필요]", text)
        self.assertIn("사업장명", text)

        # First table is now Annex Form 1. No old static reference tables remain.
        first_table = doc.tables[0]
        self.assertIn("단위공장", first_table.rows[0].cells[0].text)

        # Annex Form 2's worked example (index 5) remains untouched.
        example_table = doc.tables[5]
        example_text = "\n".join(cell.text for row in example_table.rows for cell in row.cells)
        self.assertIn("홍길동", example_text)
        self.assertIn("장치 설비 목록 및 명세", example_text)

    def test_form2_initial_submission_does_not_render_change_log_rows(self):
        project = _project()
        _set(project, "cap.business.submission_type", "신규제출")
        _set(project, "cap.business.submission_reason", "최초")
        _set(project, "cap.prevention.change_log", [{
            "일자": "2026-09-18",
            "변경항목": "테스트 변경항목",
            "변경의 종류": "테스트 변경",
            "변경 내용(변경전 → 변경후)": "OLD → NEW",
            "후속조치": "테스트 후속조치",
            "담당자": "테스트담당자",
        }])

        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        log_table = doc.tables[form_table_index_for(Document(BytesIO(load_cap_baseline_bytes())))["2"][1]]
        text = "\n".join(cell.text for row in log_table.rows for cell in row.cells)

        self.assertNotIn("테스트 변경항목", text)
        self.assertNotIn("OLD → NEW", text)

    def test_form2_change_submission_renders_confirmed_change_log_rows(self):
        project = _project()
        _set(project, "cap.business.submission_type", "변경제출")
        _set(project, "cap.prevention.change_log", [{
            "일자": "2026-09-18",
            "변경항목": "장치 설비 목록 및 명세",
            "변경의 종류": "설비변경",
            "변경 내용(변경전 → 변경후)": "TK-101 → TK-101A",
            "후속조치": "관련 도면 및 명세 갱신",
            "담당자": "홍길동",
        }])

        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        log_table = doc.tables[form_table_index_for(Document(BytesIO(load_cap_baseline_bytes())))["2"][1]]
        text = "\n".join(cell.text for row in log_table.rows for cell in row.cells)

        self.assertIn("장치 설비 목록 및 명세", text)
        self.assertIn("TK-101 → TK-101A", text)
        self.assertIn("관련 도면 및 명세 갱신", text)

    def test_form2_site_name_label_and_value_are_ten_point(self):
        project = _project()
        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        context_table = doc.tables[form_table_index_for(Document(BytesIO(load_cap_baseline_bytes())))["2"][0]]
        site_name_cells = context_table.rows[0].cells[:2]
        runs = [run for cell in site_name_cells for paragraph in cell.paragraphs for run in paragraph.runs]

        self.assertIn("1. 사업장명", "".join(run.text for run in runs))
        self.assertTrue(any(project.company_name in run.text for run in runs))
        self.assertTrue(all(run.font.size is not None and run.font.size.pt == 10 for run in runs))

    def test_form6_does_not_use_kosha_reference_in_company_sds_only_mode(self):
        project = _project()
        _set(project, "inventory.chemicals", [
            {
                "물질명": "톨루엔",
                "CAS 번호": "108-88-3",
                "물질구분": "사고대비물질",
                # 회사가 확인한 비중만 사용하고 미확인 물질상태는 공란 유지.
                "비중": "0.87 (회사 확인값)",
            }
        ])
        project.set_field(
            "reference.kosha_msds.108883",
            "KOSHA MSDS 참고자료 · 108-88-3",
            {
                "cas": "108-88-3",
                "chemical_name": "톨루엔",
                "sections": {
                    "9": {"items": [["성상", "액체"], ["비중", "1.0 (KOSHA 값 · 회사값과 다름)"]]},
                },
            },
            "HOLD",
        )

        out = build_cap_baseline_draft(project)
        doc = Document(BytesIO(out))
        form6_idx = form_table_index_for(Document(BytesIO(load_cap_baseline_bytes())))["6"][0]
        form6_text = "\n".join(cell.text for row in doc.tables[form6_idx].rows for cell in row.cells)

        self.assertIn("0.87 (회사 확인값)", form6_text)
        self.assertNotIn("KOSHA 참고값", form6_text)
        self.assertNotIn("1.0 (KOSHA 값", form6_text)

    def test_cap_regulation_filename_is_distinct_from_internal_review(self):
        name = cap_baseline_filename(_project())
        self.assertTrue(name.endswith("_화학사고예방관리계획서_규정서식_작성본.docx"))
        self.assertNotIn("내부", name)


if __name__ == "__main__":
    unittest.main()
