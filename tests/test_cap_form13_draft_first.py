"""Form 13 §3 protective-target details: draft-first end-to-end regressions."""
from __future__ import annotations

from io import BytesIO

from docx import Document

from engine.stage2 import cap_form8_workspace as form8
from engine.stage2 import cap_impact_engine as impact
from engine.stage2 import cap_baseline_docx as baseline
from engine.stage2 import cap_catalog_docx as catalog
from engine.stage2.project import Stage2Project


def _project() -> Stage2Project:
    project = Stage2Project(project_id="F13-DRAFT-FIRST", company_name="가상 사업장", cap_required=True)
    project.set_authoring_scope(psm_selected=False, cap_selected=True)
    return project


def _form8_targets(count=20):
    types = (("갑종", "교육·연구시설"), ("을종", "주택·업무시설"),
             ("환경수용체", "하천"))
    return [
        {
            "보호대상 명칭": f"가상 보호시설 {index:02d}",
            "보호대상 구분": types[index % 3][0],
            "세부유형": types[index % 3][1],
            "주소·위치": "가상 광주광역시",
            "사업장 경계와 거리(m)": 12 + index * 7,
            "GIS/현장 근거": "GIS 지도 조회 원자료",
            "인원수": "",  # No actual target occupancy was surveyed.
        }
        for index in range(count)
    ]


def _draft_detail(project, *, via_catalog=True):
    output = catalog.build_cap_draft(project) if via_catalog else baseline.build_cap_baseline_draft(project)
    document = Document(BytesIO(output))
    index = baseline.form_table_index_for(document)["13"][-1]
    return document.tables[index], output


def _text(table):
    return "\n".join(cell.text for row in table.rows for cell in row.cells)


def test_form13_section3_displays_twenty_unreviewed_form8_targets_even_without_overall_summary():
    project = _project()
    form8.save(project, _form8_targets(), no_target=False, scope_reviewed=False, status="PROPOSED")

    strict = impact.build_cap_form13_data(project)
    assert strict.protected_targets == ()
    draft = impact.build_cap_form13_data(project, for_draft=True)
    assert len(draft.protected_targets) == 20
    assert not draft.ready
    assert all("공간중첩 미확인" in item["공간중첩 상태"] for item in draft.protected_targets)

    for via_catalog in (True, False):
        detail, _ = _draft_detail(project, via_catalog=via_catalog)
        text = _text(detail)
        assert "☒ 갑종 보호대상" in text
        assert "☒ 을종 보호대상" in text
        assert "☒ 환경수용체" in text
        for index in range(20):
            assert f"가상 보호시설 {index:02d}" in text
        assert "가상 보호시설 00" in detail.rows[3].cells[1].text
        assert "12" in detail.rows[3].cells[2].text
        assert detail.rows[3].cells[3].text.strip() == ""
        # Target candidates are not automatically counted as *confirmed*
        # accident-footprint receptors.
        assert all("0명" not in cell.text for row in detail.rows[3:23] for cell in row.cells)


def test_form13_section3_uses_overall_sgis_people_for_resident_worker_checkboxes_not_per_target_people():
    project = _project()
    form8.save(project, _form8_targets(2), no_target=False, scope_reviewed=False, status="HOLD")
    project.set_field("cap.offsite.overall_impact_summary", "SGIS 기반 총괄영향범위", [{
        "총괄영향범위 산출방법": "시나리오 원형 영향범위 합집합",
        "총괄영향범위 결과 요약": "전체 통계 추정",
        "GIS/KORA 근거": "SGIS 통계 및 자체 영향범위 분석",
        "보호대상 없음 여부": "미확인",
        "총괄영향범위 내 거주민수": 120,
        "총괄영향범위 내 근로자수": 35,
    }], "CALCULATED")

    detail, _ = _draft_detail(project)
    assert "☒ 거주민" in _text(detail)
    assert "☒ 근로자" in _text(detail)
    assert "가상 보호시설 00" in _text(detail)
    assert detail.rows[3].cells[3].text == ""


def test_form13_draft_does_not_duplicate_preexisting_overall_receptor():
    project = _project()
    form8.save(project, _form8_targets(2), no_target=False, scope_reviewed=False, status="PROPOSED")
    project.set_field("cap.offsite.population_and_protected_targets", "GIS 전체 영향범위 포함 대상", [{
        "보호대상 명칭": "가상 보호시설 00",
        "보호대상 구분": "갑종",
        "세부유형": "교육·연구시설",
        "주소·위치": "공간중첩 확인된 위치",
        "사업장 경계와 거리(m)": 10,
        "인원수": 42,
        "GIS 근거": "확인된 공간중첩 자료",
    }], "USER_CONFIRMED")

    draft = impact.build_cap_form13_data(project, for_draft=True)
    assert len(draft.protected_targets) == 2
    included = next(x for x in draft.protected_targets if x["보호대상 명칭"] == "가상 보호시설 00")
    assert included["인원수"] == 42
    assert included["사업장 경계와 거리(m)"] == 10
    assert included["공간중첩 상태"] == ""
    detail, _ = _draft_detail(project)
    assert _text(detail).count("가상 보호시설 00") == 1
    assert "가상 보호시설 01" in _text(detail)


def test_legacy_calculated_boundary_candidates_are_not_mistaken_for_verified_overall_targets():
    project = _project()
    project.set_field("cap.offsite.population_and_protected_targets", "프로그램이 별지8에서 만든 목록", [{
        "보호대상 명칭": "거리 기반 추정 대상",
        "보호대상 구분": "갑종",
        "세부유형": "교육·연구시설",
        "사업장 경계와 거리(m)": 180,
        "인원수": "",
    }], "CALCULATED", note="별지 제8호 목록에서 집계")
    result = impact.build_cap_form13_data(project, for_draft=True)
    assert len(result.protected_targets) == 1
    assert "공간중첩 미확인" in result.protected_targets[0]["공간중첩 상태"]
    detail, _ = _draft_detail(project)
    assert "거리 기반 추정 대상" in _text(detail)
    # Draft disclosure is added after the table; an unchecked geographic
    # overlap must never silently become a certified resident population.


def test_form13_explicit_no_target_is_not_overridden_by_unreviewed_form8_candidates():
    project = _project()
    form8.save(project, _form8_targets(2), no_target=False, scope_reviewed=False, status="PROPOSED")
    project.set_field("cap.offsite.overall_impact_summary", "전체 영향범위 확인", [{
        "총괄영향범위 산출방법": "GIS 공간중첩",
        "총괄영향범위 결과 요약": "보호대상 없음",
        "GIS/KORA 근거": "GIS 도형 확인",
        "보호대상 없음 여부": "예",
        "총괄영향범위 내 거주민수": 0,
        "총괄영향범위 내 근로자수": 0,
    }], "USER_CONFIRMED")

    prepared = impact.build_cap_form13_data(project, for_draft=True)
    assert prepared.no_protected_targets
    assert prepared.protected_targets == ()
    detail, _ = _draft_detail(project)
    assert "해당 없음" in _text(detail)
    assert "가상 보호시설 00" not in _text(detail)


def test_form13_section3_does_not_invent_missing_distance_or_occupancy():
    project = _project()
    record = _form8_targets(1)[0]
    record["사업장 경계와 거리(m)"] = ""
    form8.save(project, [record], no_target=False, scope_reviewed=False, status="PROPOSED")
    detail, _ = _draft_detail(project)
    assert "가상 보호시설 00" in _text(detail)
    assert detail.rows[3].cells[2].text.strip() == ""
    assert detail.rows[3].cells[3].text.strip() == ""
