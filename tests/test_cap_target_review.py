"""CAP stage-③ protection-target category selection tests."""
from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pytest
from openpyxl import load_workbook

from engine.stage2 import cap_form8_workspace as form8
from engine.stage2 import cap_target_review
from engine.stage2 import scenario_survey
from engine.stage2.project import Stage2Project


def _project():
    return Stage2Project(project_id="TARGET-DROPDOWN", company_name="가상회사", cap_required=True)


def _candidates():
    return [
        {"보호대상 명칭": "전남대학교", "보호대상 구분": "갑종", "세부유형": "교육·연구시설",
         "주소·위치": "광주", "사업장 경계와 거리(m)": 0,
         "GIS/현장 근거": "지도 이름 규칙 제안", "거주민수": "", "근로자수": ""},
        {"보호대상 명칭": "북구청", "보호대상 구분": "", "세부유형": "",
         "주소·위치": "광주광역시 북구", "사업장 경계와 거리(m)": 2,
         "GIS/현장 근거": "지도 위치 후보", "거주민수": "", "근로자수": ""},
        {"보호대상 명칭": "용봉동 대신아파트", "보호대상 구분": "", "세부유형": "",
         "주소·위치": "광주광역시 북구", "사업장 경계와 거리(m)": 15,
         "GIS/현장 근거": "지도 위치 후보", "거주민수": "", "근로자수": ""},
    ]


def test_choice_options_match_declared_legal_categories_and_subtypes():
    assert cap_target_review.LEGAL_CATEGORIES == ("", "갑종", "을종", "환경수용체")
    for category, subtypes in form8.SUBTYPES.items():
        assert category in cap_target_review.LEGAL_CATEGORIES
        assert set(subtypes) <= set(cap_target_review.LEGAL_SUBTYPES)


def test_changed_selection_is_saved_as_hold_not_falsely_legally_confirmed():
    p = _project()
    candidates = _candidates()
    # Initial map results are candidates, never legally verified facts.
    form8.save(p, candidates, no_target=False, status="HOLD")
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[1]["보호대상 구분"] = "을종"
    edited[1]["세부유형"] = "주택·업무시설"
    edited[1]["근로자수"] = 45
    edited[1]["사업장 경계와 거리(m)"] = 99999  # disabled GIS column tampered
    changed, warnings = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed and not warnings
    record = p.get_field(form8.SITE_KEY)
    assert record.status == "HOLD"
    rows = {r["보호대상 명칭"]: r for r in form8.saved_rows(p)}
    assert rows["북구청"]["보호대상 구분"] == "을종"
    assert rows["북구청"]["세부유형"] == "주택·업무시설"
    assert rows["북구청"]["근로자수"] == 45
    assert rows["북구청"]["사업장 경계와 거리(m)"] == 2
    assert rows["용봉동 대신아파트"]["보호대상 구분"] == ""
    assert rows["용봉동 대신아파트"]["거주민수"] == ""
    assert not cap_target_review.apply_candidate_edits(
        p, cap_target_review.candidate_review_rows(p, candidates), candidates
    )[0]


def test_batch_four_column_review_preserves_hidden_gis_provenance_and_unknown_counts():
    p = _project()
    candidates = _candidates()
    # Some separately verified people counts may already exist in the project.
    candidates[1]["거주민수"] = 78
    candidates[1]["근로자수"] = ""
    form8.save(p, candidates, no_target=False, status="HOLD")
    visible = ("보호대상 명칭", "보호대상 구분", "세부유형", "사업장 경계와 거리(m)")
    edited = [{key: row[key] for key in visible} for row in cap_target_review.candidate_review_rows(p, candidates)]
    edited[1]["보호대상 구분"] = "을종"
    edited[1]["세부유형"] = "주택·업무시설"
    changed, warnings = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed and not warnings
    saved = {r["보호대상 명칭"]: r for r in form8.saved_rows(p)}
    assert saved["북구청"]["보호대상 구분"] == "을종"
    assert saved["북구청"]["세부유형"] == "주택·업무시설"
    assert saved["북구청"]["주소·위치"] == "광주광역시 북구"
    assert saved["북구청"]["GIS/현장 근거"] == "지도 위치 후보"
    assert saved["북구청"]["사업장 경계와 거리(m)"] == 2
    assert saved["북구청"]["거주민수"] == 78
    assert saved["북구청"]["근로자수"] == ""
    assert saved["용봉동 대신아파트"]["거주민수"] == ""
    assert p.get_field(form8.SITE_KEY).status == "HOLD"


def test_category_change_clears_incompatible_subtype_and_warns():
    p = _project()
    candidates = _candidates()
    form8.save(p, candidates, no_target=False, status="HOLD")
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[0]["보호대상 구분"] = "을종"
    changed, warnings = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed and warnings
    stored = {r["보호대상 명칭"]: r for r in form8.saved_rows(p)}
    assert stored["전남대학교"]["보호대상 구분"] == "을종"
    assert stored["전남대학교"]["세부유형"] == ""
    # An explicitly cleared category cannot revert to the name-only heuristic.
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[0]["보호대상 구분"] = ""
    changed, _ = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed
    restored = cap_target_review.candidate_review_rows(p, candidates)
    assert restored[0]["보호대상 구분"] == ""
    assert restored[0]["세부유형"] == ""


def test_illegal_free_text_and_negative_counts_are_rejected():
    p = _project()
    candidates = _candidates()
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[0]["보호대상 구분"] = "갑종일 것 같음"
    with pytest.raises(ValueError, match="지원하지 않는 법정 구분"):
        cap_target_review.apply_candidate_edits(p, edited, candidates)
    edited[0]["보호대상 구분"] = "갑종"
    edited[0]["거주민수"] = -1
    with pytest.raises(ValueError, match="0 이상의 정수"):
        cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert p.get_field(form8.SITE_KEY) is None


def test_unrelated_existing_targets_survive_review_changes():
    p = _project()
    candidates = _candidates()
    extra = dict(candidates[2], **{"보호대상 명칭": "다른 현장 확인 보호대상"})
    form8.save(p, [*candidates, extra], no_target=False, status="HOLD")
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[1]["보호대상 구분"] = "을종"
    edited[1]["세부유형"] = "주택·업무시설"
    changed, _ = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed
    assert any(r["보호대상 명칭"] == "다른 현장 확인 보호대상" for r in form8.saved_rows(p))


def test_exported_gis_workbook_retains_screen_dropdown_choices():
    p = _project()
    candidates = _candidates()
    edited = cap_target_review.candidate_review_rows(p, candidates)
    edited[1]["보호대상 구분"] = "을종"
    edited[1]["세부유형"] = "주택·업무시설"
    changed, _ = cap_target_review.apply_candidate_edits(p, edited, candidates)
    assert changed
    with patch.object(scenario_survey, "candidate_rows", return_value=candidates):
        book = load_workbook(BytesIO(scenario_survey.company_workbook(p)))
    sheet = book["주변 보호대상"]
    columns = {c.value: c.column for c in sheet[1]}
    by_name = {
        sheet.cell(row, columns["보호대상 명칭"]).value: row
        for row in range(2, sheet.max_row + 1)
        if sheet.cell(row, columns["보호대상 명칭"]).value
    }
    assert sheet.cell(by_name["북구청"], columns["보호대상 구분"]).value == "을종"
    assert sheet.cell(by_name["북구청"], columns["세부유형"]).value == "주택·업무시설"
    assert any(v.type == "list" and "갑종" in (v.formula1 or "")
               for v in sheet.data_validations.dataValidation)
