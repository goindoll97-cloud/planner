from __future__ import annotations

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docx import Document

from engine.kosha_msds import KOSHAFullMSDSResult, KOSHAMSDSSection
from engine.stage2.msds_reference import (
    build_msds_reference_docx,
    compare_supplier_sds,
    inventory_chemicals,
    refresh_msds_references,
    reference_field_key,
)
from engine.stage2.project import EvidenceRef, Stage2Project


class Stage2MSDSReferenceTests(unittest.TestCase):
    def _project(self) -> Stage2Project:
        project = Stage2Project(
            project_id="S2-MSDS-TEST",
            company_name="테스트화학",
            psm_required=True,
            cap_required=True,
            cap_group="2군",
            scope_confirmed=True,
            psm_selected=True,
            cap_selected=True,
        )
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [
                {"물질명": "톨루엔", "CAS 번호": "108-88-3", "함량(%)": 99.5},
                {"물질명": "메탄올", "CAS 번호": "67-56-1", "함량(%)": 30},
            ],
            "VERIFIED",
        )
        return project

    def test_inventory_extracts_unique_cas(self):
        rows = inventory_chemicals(self._project())
        self.assertEqual([row.cas for row in rows], ["108-88-3", "67-56-1"])
        self.assertEqual(rows[0].chemical_name, "톨루엔")

    def test_kosha_reference_is_stored_as_hold_not_supplier_msds(self):
        project = self._project()

        def fake_lookup(cas: str) -> KOSHAFullMSDSResult:
            return KOSHAFullMSDSResult(
                status="REFERENCE_READY",
                cas=cas,
                message="reference",
                chem_id="C001",
                chemical_name="Toluene" if cas == "108-88-3" else "Methanol",
                sections={
                    1: KOSHAMSDSSection(1, "화학제품과 회사에 관한 정보", (("가. 제품명", "참고물질"),), "가. 제품명: 참고물질"),
                    2: KOSHAMSDSSection(2, "유해성·위험성", (("분류", "인화성 액체 : 구분 2"),), "분류: 인화성 액체 : 구분 2"),
                },
                checked_at_utc="2026-09-13T00:00:00+00:00",
            )

        results = refresh_msds_references(project, cas_numbers=["108-88-3"], lookup=fake_lookup)
        self.assertEqual(results[0].status, "REFERENCE_READY")
        record = project.get_field(reference_field_key("108-88-3"))
        self.assertIsNotNone(record)
        self.assertEqual(record.status, "HOLD")
        self.assertEqual(record.value["source_dataset_id"], "15157612")
        self.assertIsNone(project.get_field("psm.psi.msds"))

    def test_reference_docx_has_all_16_standard_sections_and_warning(self):
        project = self._project()

        def fake_lookup(cas: str) -> KOSHAFullMSDSResult:
            return KOSHAFullMSDSResult(
                status="PARTIAL_REFERENCE",
                cas=cas,
                message="partial",
                chem_id="C001",
                chemical_name="톨루엔",
                sections={2: KOSHAMSDSSection(2, "유해성·위험성", (("분류", "인화성 액체 : 구분 2"),), "")},
                checked_at_utc="2026-09-13T00:00:00+00:00",
            )

        refresh_msds_references(project, cas_numbers=["108-88-3"], lookup=fake_lookup)
        data = build_msds_reference_docx(project, "108-88-3")
        doc = Document(BytesIO(data))
        text = "\n".join(p.text for p in doc.paragraphs)
        self.assertIn("법정 제품 MSDS 아님", text)
        self.assertIn("1. 화학제품과 회사에 관한 정보", text)
        self.assertIn("16. 그 밖의 참고사항", text)
        self.assertIn("실제 제품 MSDS를 대체하지 않으며", text)

    def test_supplier_sds_cas_comparison_runs_locally_and_supports_mixture(self):
        project = self._project()
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "혼합제품_MSDS.txt"
            path.write_text(
                "3. 구성성분의 명칭 및 함유량\n톨루엔 108-88-3 60%\n메탄올 67-56-1 30%\n",
                encoding="utf-8",
            )
            evidence = EvidenceRef(
                source_type="ATTACHMENT",
                source_name=path.name,
                location=str(path),
                sha256="a" * 64,
            )
            project.set_field(
                "psm.psi.msds",
                "물질안전보건자료",
                {"file_name": path.name},
                "HOLD",
                evidence=[evidence],
            )
            result = compare_supplier_sds(project)

        self.assertEqual(result.status, "CAS_COVERED")
        self.assertEqual(set(result.matched_cas), {"108-88-3", "67-56-1"})
        self.assertEqual(result.missing_cas, ())

    def test_stage2_ui_defers_kosha_lookup_and_keeps_company_sds_msds(self):
        source = Path("ui/stage2_intake_page.py").read_text(encoding="utf-8")
        self.assertNotIn("KOSHA MSDS 16개 항목 조회", source)
        self.assertNotIn("CAS 번호만", source)
        self.assertNotIn("refresh_msds_references", source)
        self.assertIn("회사 보유 SDS/MSDS·도면·첨부자료", source)
        self.assertIn("제품 SDS/MSDS", source)


if __name__ == "__main__":
    unittest.main()
