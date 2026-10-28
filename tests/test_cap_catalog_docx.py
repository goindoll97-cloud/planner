"""카탈로그 조립기(cap_catalog_docx)가 예전 렌더러(cap_baseline_docx)와 같은 규정서식 초안을 만드는지 비교합니다."""
from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from docx import Document

from engine.stage2 import cap_catalog_docx as cd
from engine.stage2 import cap_fact_catalog as catalog
from engine.stage2 import demo_full_company as d
from engine.stage2 import evidence_workspace as ew
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, load_cap_baseline_bytes
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.project import Stage2Project


def _set(project, key, value):
    project.set_field(key, key, value, "USER_CONFIRMED")


def _scoped(name="가상 사업장", group="1군"):
    project = Stage2Project(project_id="CATALOG-DOCX-" + name, company_name=name, psm_required=False,
                            cap_required=True, cap_group=group)
    project.set_authoring_scope(psm_selected=False, cap_selected=True)
    return project


def _hand_entered():
    """예전 별지 작성대에서 사람이 적은 것처럼 작성자료를 직접 넣은 사업장(서식 칸이 고루 채워짐)."""
    p = _scoped("세계화학(주) 충주공장")
    for key, value in {
        "cap.business.representative": "홍길동", "cap.business.registration_no": "123-45-67890",
        "business.address": "충청북도 충주시 테스트로 1", "cap.business.submission_type": "변경제출",
        "cap.business.submission_reason": "부적합", "cap.business.joint_emergency_plan": "공동제출",
        "cap.business.other_system_review": "해당(공정안전보고서)", "cap.business.recent_accident": "있음",
        "cap.business.writer_info": "안전팀 김담당", "cap.business.writer_contact": "043-000-0000",
        "cap.basic.total_facility_overview": "제1·2공장", "process.description": "혼합 후 충전",
        "cap.basic.loading_transport": "입·출하 시설 2기, 보유 탱크로리 1기",
        "cap.prevention.change_log": [{"일자": "2026-09-18", "변경항목": "설비", "변경의 종류": "설비변경",
                                       "변경 내용(변경전 → 변경후)": "A → B", "후속조치": "도면 갱신", "담당자": "홍길동"}],
    }.items():
        _set(p, key, value)
    _set(p, "inventory.chemicals", [{"물질명": "Methyl isocyanate", "CAS 번호": "624-83-9", "물질구분": "사고대비물질",
                                     "물리적 상태": "액체", "함량(%)": "99", "최대보유량": "500", "폭발한계 하한": "5.3"}])
    _set(p, "psm.psi.equipment_specs", [{"설비번호": "TK-101", "설비명": "MIC 저장탱크", "취급물질": "Methyl isocyanate",
                                         "설계용량": "20"}])
    _set(p, "cap.safety.gas_detection", [{"감지기 번호": "GD-1", "검출대상 물질": "MIC", "설치위치": "TK-101"}])
    return p


def _files_only():
    files = d.files()
    p = create_direct_cap_project(d.COMPANY, address=d.DATA["company"]["주소"], cap_group="2군")
    for name in ("01_제품목록.xlsx", "02_설비대장.xlsx", "03_사업장_일반정보.docx", "04_공정설명서.docx",
                 "05_SDS_물성표.xlsx", "06_설비사양_안전설비.xlsx"):
        ew.ingest(p, name, files[name], ew.classify_document(name, files[name]))
    ew.publish(p, replace_existing=True)
    return p


def _evidence_demo():
    p = create_direct_cap_project("가상 사업장", address="서울", cap_group="")
    with ZipFile(BytesIO(ew.demo_zip())) as z:
        for name in z.namelist():
            if name.endswith((".csv", ".xlsx")):
                ew.ingest(p, name, z.read(name), ew.classify_document(name, z.read(name)))
    ew.publish(p, replace_existing=True)
    return p


def _document_xml(content: bytes) -> bytes:
    with ZipFile(BytesIO(content)) as z:
        return z.read("word/document.xml")


class CellMapTests(unittest.TestCase):
    def test_cell_map_is_valid(self):
        self.assertEqual(cd.validate(), [])

    def test_cells_cover_the_migrated_forms_and_point_at_catalog_facts(self):
        facts = cd.referenced_facts()
        for form in (1, 3, 4, 5, 6, 9, 10, 11):
            self.assertTrue(facts[form], form)
            for fact_id in facts[form]:
                self.assertIn(form, catalog.get(fact_id).forms, fact_id)
        self.assertIn("site.representative", facts[3])
        self.assertIn("facility.connection_size", facts[9])


class SameOutputTests(unittest.TestCase):
    """두 조립 방식의 결과가 바이트 단위로 같아야 합니다(같은 작성자료를 같은 칸에 씀)."""

    def assertSameDraft(self, project):
        new, previous = cd.build_cap_catalog_draft(project), build_cap_baseline_draft(project)
        self.assertEqual(_document_xml(new), _document_xml(previous))
        self.assertEqual(new, previous)

    def test_empty_project(self):
        self.assertSameDraft(_scoped())

    def test_values_entered_by_hand(self):
        self.assertSameDraft(_hand_entered())

    def test_values_read_from_company_files(self):
        project = _files_only()
        self.assertSameDraft(project)
        doc = Document(BytesIO(load_cap_baseline_bytes()))
        self.assertEqual(cd.fill(doc, project), [2, 7, 8, 12, 13, 15, 16])   # 옮긴 별지는 조립기가 채움

    def test_files_with_conflicts(self):
        self.assertSameDraft(_evidence_demo())

    def test_form_engine_project(self):
        from tests.test_stage2_cap_form1_engine import CAPForm1EngineTests

        self.assertSameDraft(CAPForm1EngineTests()._project())

    def test_full_practice_walk(self):
        from tests.test_demo_full_company import scenarios, walk

        project, _ = walk()
        scenarios(project)
        self.assertSameDraft(project)

    def test_empty_sources_fall_back_to_the_previous_renderer(self):
        doc = Document(BytesIO(load_cap_baseline_bytes()))
        delegated = cd.fill(doc, _scoped())
        self.assertTrue({1, 9, 10, 11} <= set(delegated))      # 기준 행이 없으면 예전 렌더러의 대체 경로


class FallbackTests(unittest.TestCase):
    def test_previous_renderer_is_used_when_the_assembler_fails(self):
        project = _hand_entered()
        with patch.object(cd, "_fill_section", side_effect=RuntimeError("고장")):
            self.assertEqual(cd.build_cap_draft(project), build_cap_baseline_draft(project))

    def test_export_uses_the_catalog_assembler(self):
        from engine.stage2 import report_export as rx

        project = _hand_entered()
        with patch.object(cd, "build_cap_catalog_draft", wraps=cd.build_cap_catalog_draft) as spy:
            outputs = rx.build_outputs(project, "CAP")
        self.assertTrue(spy.called)
        self.assertTrue(outputs.regulation_name.endswith("_규정서식_초안.docx"))


if __name__ == "__main__":
    unittest.main()
