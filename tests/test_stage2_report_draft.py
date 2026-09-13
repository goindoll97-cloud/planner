from __future__ import annotations

from io import BytesIO
from pathlib import Path
import unittest
from zipfile import ZipFile

from docx import Document

from engine.stage2.project import EvidenceRef, Stage2Project
from engine.stage2.report_draft import (
    build_draft_bundle,
    build_report_draft,
    draft_filename,
    report_generation_status,
)


class Stage2ReportDraftTests(unittest.TestCase):
    def _project(self, *, psm=True, cap=True, cap_group="1군") -> Stage2Project:
        project = Stage2Project(
            project_id="S2-TEST-REPORT",
            company_name="테스트정밀화학",
            site_name="울산공장",
            psm_required=psm,
            cap_required=cap,
            cap_group=cap_group if cap else "",
            scope_confirmed=True,
            psm_selected=psm,
            cap_selected=cap,
        )
        project.set_field("business.company_name", "회사명", "테스트정밀화학", "VERIFIED")
        project.set_field("business.site_name", "사업장명", "울산공장", "VERIFIED")
        project.set_field("business.address", "사업장 소재지", "울산광역시 테스트로 1", "VERIFIED")
        project.set_field(
            "inventory.chemicals",
            "화학물질 목록",
            [{"물질명": "톨루엔", "CAS 번호": "108-88-3", "최대보유량": 15000, "단위": "kg"}],
            "VERIFIED",
        )
        project.set_field(
            "inventory.facilities",
            "시설·설비 목록",
            [{"설비번호": "TK-101", "설비명": "톨루엔 저장탱크", "최대보유량(kg)": 15000}],
            "VERIFIED",
        )
        project.set_field(
            "process.description",
            "공정설명서",
            "원료를 저장탱크에서 혼합공정으로 이송한 뒤 제품을 생산한다.",
            "USER_CONFIRMED",
        )
        project.set_field(
            "psm.psi.equipment_specs",
            "장치 및 설비명세",
            [{"설비번호": "TK-101", "설비명": "톨루엔 저장탱크", "설계압력": "0.49 MPa"}],
            "USER_CONFIRMED",
        )
        project.set_field(
            "cap.facility.equipment_specs",
            "장치·설비 상세 명세",
            [{"설비번호": "TK-101", "설비명": "톨루엔 저장탱크", "설계압력": "0.49 MPa"}],
            "USER_CONFIRMED",
        )
        project.set_field(
            "documents.pfd",
            "공정흐름도(PFD)",
            {"file_name": "PFD_Rev3.pdf", "reference_no": "PFD-001", "revision": "Rev.3"},
            "HOLD",
            evidence=[EvidenceRef(source_type="COMPANY_EVIDENCE", source_name="PFD_Rev3.pdf", sha256="a" * 64)],
            note="도면은 접수되었으나 내용 확인 전",
        )
        if cap:
            project.set_field("cap.business.representative", "대표자 성명", "김테스트", "USER_CONFIRMED")
        return project

    @staticmethod
    def _doc_text(data: bytes) -> str:
        doc = Document(BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.extend(cell.text for cell in row.cells)
        return "\n".join(parts)

    def test_psm_draft_uses_current_top_level_sections_and_company_facts(self):
        project = self._project(psm=True, cap=False)
        data = build_report_draft(project, "PSM")
        text = self._doc_text(data)

        self.assertIn("공정안전보고서", text)
        self.assertIn("검토용 자동작성 초안", text)
        self.assertIn("테스트정밀화학", text)
        self.assertIn("공정안전자료", text)
        self.assertIn("공정위험성평가서", text)
        self.assertIn("안전운전계획", text)
        self.assertIn("비상조치계획", text)
        self.assertIn("TK-101", text)
        self.assertIn("PFD_Rev3.pdf", text)
        self.assertIn("검증 보류", text)
        self.assertIn("확인 필요", text)
        self.assertIn("법정 제출용 최종본이 아니며", text)

    def test_cap_group2_draft_does_not_add_external_emergency_section(self):
        project = self._project(psm=False, cap=True, cap_group="2군")
        data = build_report_draft(project, "CAP")
        doc = Document(BytesIO(data))
        headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]

        self.assertIn("기본정보", headings)
        self.assertIn("시설정보", headings)
        self.assertIn("내부 비상대응계획", headings)
        self.assertNotIn("외부 비상대응계획", headings)

    def test_report_status_is_fail_closed_but_draft_is_still_buildable(self):
        project = self._project(psm=True, cap=False)
        status = report_generation_status(project, "PSM")
        self.assertFalse(status.final_ready)
        self.assertEqual(status.state, "HOLD")
        self.assertGreater(status.unresolved_n, 0)
        self.assertGreater(len(build_report_draft(project, "PSM")), 1000)

    def test_unselected_report_cannot_be_generated(self):
        project = self._project(psm=True, cap=False)
        with self.assertRaisesRegex(ValueError, "현재 작성범위"):
            build_report_draft(project, "CAP")

    def test_bundle_contains_only_selected_report_drafts_and_manifest(self):
        project = self._project(psm=True, cap=True)
        data = build_draft_bundle(project)
        with ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            self.assertIn(draft_filename(project, "PSM"), names)
            self.assertIn(draft_filename(project, "CAP"), names)
            self.assertIn("생성상태.txt", names)
            manifest = archive.read("생성상태.txt").decode("utf-8")
            self.assertIn("법정 제출용 최종본이 아닙니다", manifest)
            self.assertIn("공정안전보고서", manifest)
            self.assertIn("화학사고예방관리계획서", manifest)

    def test_review_page_exposes_docx_draft_generation_separately_from_final_export(self):
        source = Path("ui/stage2_review_page.py").read_text(encoding="utf-8")
        self.assertIn('"보고서 초안 생성"', source)
        self.assertIn("build_report_draft", source)
        self.assertIn("검토용 DOCX 초안 다운로드", source)
        self.assertIn("법정 제출용 최종본으로 사용할 수 없습니다", source)
        self.assertIn('"감사·검토자료"', source)


if __name__ == "__main__":
    unittest.main()
