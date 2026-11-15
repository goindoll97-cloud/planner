"""Planner principle: draft first, inspect the generated statutory form afterwards."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

from docx import Document

from engine.stage2 import cap_target_review
from engine.stage2 import scenario_survey
from engine.stage2 import cap_form8_workspace as form8
from engine.stage2.cap_form8_engine import build_cap_form8_data
from engine.stage2.cap_catalog_docx import build_cap_draft
from engine.stage2.cap_baseline_docx import form_table_index_for
from engine.stage2.project import Stage2Project


def project():
    p = Stage2Project(project_id="DRAFT-FIRST-F8", company_name="가상 사업장", cap_required=True)
    p.set_authoring_scope(psm_selected=False, cap_selected=True)
    return p


def candidates(n=20):
    return [
        {
            "보호대상 명칭": f"주변시설 {i:02d}",
            "보호대상 구분": "갑종" if i % 2 == 0 else "",
            "세부유형": "교육·연구시설" if i % 2 == 0 else "",
            "주소·위치": "광주광역시 지도 조회 위치",
            "사업장 경계와 거리(m)": 20 + i * 10,
            "GIS/현장 근거": "GIS 조회 후보 · 2026-11-15",
            "거주민수": "", "근로자수": "",
        }
        for i in range(n)
    ]


def _form8_document(project):
    doc = Document(BytesIO(build_cap_draft(project)))
    first, second = (doc.tables[i] for i in form_table_index_for(doc)["8"])
    return doc, first, second


def test_first_save_even_without_dropdown_changes_populates_twenty_draft_rows():
    p = project()
    found = candidates()
    # Before the user touches any menu, only the GIS-proposed values exist.
    edited = [
        {key: row[key] for key in ("보호대상 명칭", "보호대상 구분",
                                  "세부유형", "사업장 경계와 거리(m)")}
        for row in cap_target_review.candidate_review_rows(p, found)
    ]
    changed, warnings = cap_target_review.apply_candidate_edits(p, edited, found)
    assert changed
    assert not warnings
    assert p.get_field(form8.SITE_KEY).status == "PROPOSED"

    prepared = build_cap_form8_data(p, for_draft=True)
    assert len(prepared.rows) == 20
    assert not prepared.ready  # Quality checks remain available AFTER the draft.
    assert any("500m 범위 전체" in message for message in prepared.blockers)

    _, first, second = _form8_document(p)
    text = "\n".join(cell.text for row in second.rows for cell in row.cells)
    for i in range(20):
        assert f"주변시설 {i:02d}" in text
    assert second.cell(1, 0).text == "1"
    assert second.cell(20, 0).text == "20"
    assert second.cell(1, 1).text == "교육·연구시설"
    assert second.cell(2, 1).text == "[확인 필요: 세부유형]"  # Unknown classification is not invented.
    assert "세부유형 미확인 10건" in first.rows[1].cells[0].text
    assert float(second.cell(2, 3).text) == 30.0
    assert "초안" in first.rows[1].cells[0].text
    assert "☒ 교육·연구시설" in " ".join(
        cell.text for row in first.rows for cell in row.cells
    )

    # Editing the same form twice must not add duplicates.
    changed, _ = cap_target_review.apply_candidate_edits(p, edited, found)
    assert not changed
    assert len(form8.saved_rows(p)) == 20


def test_legacy_hold_rows_are_visible_in_draft_but_not_misrepresented_as_approved():
    p = project()
    form8.save(p, candidates(2), no_target=False, scope_reviewed=False, status="HOLD")
    draft = build_cap_form8_data(p, for_draft=True)
    strict = build_cap_form8_data(p)
    assert len(draft.rows) == 2
    assert not draft.ready
    assert not strict.rows
    _, first, second = _form8_document(p)
    assert "보호대상 후보 2건" in first.rows[1].cells[0].text
    assert "주변시설 00" in second.cell(1, 2).text
    assert "주변시설 01" in second.cell(2, 2).text



def test_existing_legacy_subtype_aliases_check_euljong_and_environment_in_both_drafts():
    p = project()
    # Legacy intake names were already normalized for the itemized table,
    # but checkbox selection formerly read only the raw canonical keys.
    p.set_field(form8.SITE_KEY, "주변 보호대상", [
        {"보호대상 명칭": "한빛초등학교", "보호대상 구분": "갑종",
         "세부유형": "교육·연구시설", "주소·위치": "광주", "사업장 경계와 거리(m)": 50},
        {"명칭": "시청앞 근린시설", "구분": "을종",
         "종류": "근린생활시설", "주소": "광주", "거리(m)": 120},
        {"보호대상 명칭": "하천구역", "보호대상 구분": "환경수용체",
         "보호대상 종류": "하천", "주소·위치": "광주", "사업장 경계와 거리(m)": 150},
        {"보호대상 명칭": "미확인 일반건물", "보호대상 구분": "을종",
         "세부유형": "", "주소·위치": "광주", "사업장 경계와 거리(m)": 160},
    ], "HOLD")

    from engine.stage2.cap_baseline_docx import build_cap_baseline_draft
    for build in (build_cap_draft, build_cap_baseline_draft):
        doc = Document(BytesIO(build(p)))
        first, listing = (doc.tables[i] for i in form_table_index_for(doc)["8"])
        choices = " ".join(cell.text for row in first.rows[2:] for cell in row.cells)
        assert "☒ 교육·연구시설" in choices
        assert "☒ 근린 생활시설" in choices
        assert "☒ 하천" in choices
        assert "☐ 공업시설" in choices
        assert listing.cell(2, 1).text == "근린생활시설"
        assert listing.cell(3, 1).text == "하천"
        assert listing.cell(4, 1).text == "[확인 필요: 세부유형]"
        assert "세부유형 미확인 1건" in first.rows[1].cells[0].text


def test_official_vworld_environment_layer_is_a_draft_suggestion_not_a_legal_approval():
    p = project()
    candidates = [
        {"name": "인근 하천", "relation": "OUTSIDE", "boundary_distance_m": 110,
         "source": "브이월드 2D 데이터 API · 하천망 (지도 객체 후보, 법정 분류 미확인)",
         "object_id": "vworld:LT_C_WKMSTRM:river-1", "address": "브이월드 하천망"},
        {"name": "건물 한 동", "relation": "OUTSIDE", "boundary_distance_m": 200,
         "source": "브이월드 2D 데이터 API · 도로명주소 건물 (지도 객체 후보, 법정 분류 미확인)",
         "object_id": "vworld:LT_C_SPBD:building-1", "address": "브이월드 건물"},
    ]
    with patch.object(scenario_survey.survey, "boundary", return_value=object()), \
         patch.object(scenario_survey.survey, "is_current", return_value=True), \
         patch.object(scenario_survey.survey, "survey", return_value={"checked_at": "2026-11-15"}), \
         patch.object(scenario_survey.survey, "annotate", return_value=candidates):
        rows = scenario_survey.candidate_rows(p)

    assert rows[0]["보호대상 구분"] == "환경수용체"
    assert rows[0]["세부유형"] == "하천"
    assert "법정 해당 여부 확인 필요" in rows[0]["GIS/현장 근거"]
    assert rows[1]["보호대상 구분"] == ""
    assert rows[1]["세부유형"] == ""

    # A manufactured source string with no official layer ID may not confer
    # legal subtype even when the word '하천망' appears in the description.
    assert scenario_survey._vworld_draft_type({
        "source": candidates[0]["source"], "object_id": "other-source:river-1"
    }) == ("", "")
    form8.save(p, rows, no_target=False, status="HOLD")
    _, first, listing = _form8_document(p)
    choices = " ".join(cell.text for row in first.rows[2:] for cell in row.cells)
    assert "☒ 하천" in choices
    assert listing.cell(1, 1).text == "하천"
    assert listing.cell(2, 1).text == "[확인 필요: 세부유형]"


def test_missing_distance_is_not_invented_as_zero_for_draft():
    p = project()
    row = candidates(1)[0]
    row["사업장 경계와 거리(m)"] = ""
    form8.save(p, [row], no_target=False, scope_reviewed=False, status="PROPOSED")
    _, _, listing = _form8_document(p)
    assert listing.cell(1, 3).text == ""  # Unknown distance is not a fabricated zero.
