from __future__ import annotations

"""Final-output hardening for CAP statutory forms.

The official annex files contain many checkbox/choice cells.  Those cells must
remain recognizable as the statutory form: a confirmed company value selects
an option, but it must not replace the option set with a short free-text value.

This module intentionally performs only deterministic formatting from confirmed
project data.  It does not infer an unconfirmed sub-choice and does not call AI.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
import re
from typing import Any

from . import cap_hwpx
from . import statutory_report as report
from .project import CONFIRMED_STATUSES, Stage2Project


_INSTALL_MARKER = "_cap_final_form_runtime_installed"


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", str(value or "")).lower()


def _checked(selected: bool, label: str) -> str:
    return f"{'☒' if selected else '☐'} {label}"


def _truth_state(value: object) -> bool | None:
    n = _norm(value)
    if n in {"예", "yes", "y", "true", "1", "있음", "해당", "유", "사용", "수립"}:
        return True
    if n in {"아니오", "아니요", "no", "n", "false", "0", "없음", "미해당", "무", "미사용", "미수립"}:
        return False
    return None


def render_submission_type(value: object) -> str:
    """Render all Annex 3 submission choices, selecting only explicit facts."""
    raw = str(value or "").strip()
    n = _norm(raw)
    primary = ""
    if "이행점검" in n and "불이행" in n:
        primary = "이행점검불이행"
    elif "변경제출" in n or ("변경" in n and "재제출" not in n):
        primary = "변경제출"
    elif "재제출" in n:
        primary = "재제출"
    elif "신규제출" in n or "신규" in n:
        primary = "신규제출"

    # A parent choice such as "신규" never proves the nested reason.
    first = "최초" in n
    unsuitable = "부적합" in n
    rows = []
    for key, label in (
        ("신규제출", "신규제출"),
        ("변경제출", "변경제출"),
        ("재제출", "재제출"),
        ("이행점검불이행", "이행점검 불이행"),
    ):
        nested_first = primary == key and first
        nested_unsuitable = primary == key and unsuitable
        rows.append(
            f"{_checked(primary == key, label)} "
            f"( {_checked(nested_first, '최초')}   {_checked(nested_unsuitable, '부적합')} )"
        )
    return "\n".join(rows)


def render_writing_level(value: object) -> str:
    n = _norm(value)
    return f"{_checked('1군' in n, '1군')}   {_checked('2군' in n, '2군')}"


def render_joint_emergency(value: object) -> str:
    n = _norm(value)
    joint = "공동제출" in n or n == "공동"
    single = "단독제출" in n or n == "단독"
    # Generic yes/no answers do not establish which statutory submission mode.
    return f"{_checked(joint, '공동제출')}   {_checked(single, '단독제출')}"


def render_other_system_review(value: object) -> str:
    n = _norm(value)
    explicit_no = _truth_state(value) is False or "미해당" in n
    psm = "공정안전보고서" in n
    safety = "안전성향상계획" in n
    explicit_yes = (_truth_state(value) is True or "해당" in n or psm or safety) and not explicit_no
    return (
        f"{_checked(explicit_yes, '해당')}"
        f"( {_checked(psm, '공정안전보고서')}   {_checked(safety, '안전성향상계획')} )\n"
        f"{_checked(explicit_no, '미해당')}"
    )


def render_yes_no(value: object, *, yes_label: str = "있음", no_label: str = "없음") -> str:
    state = _truth_state(value)
    return f"{_checked(state is True, yes_label)}   {_checked(state is False, no_label)}"


_FACILITY_CHOICES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("저장탱크", ("저장탱크", "storagetank", "tank")),
    ("저장·보관시설", ("저장보관시설", "보관시설", "창고")),
    ("혼합시설", ("혼합시설", "혼합기", "믹서", "mixer")),
    ("고압시설", ("고압시설", "고압설비")),
    ("반응시설", ("반응시설", "반응기", "reactor")),
    ("탑조류(증류탑 등)", ("탑조류", "증류탑", "column", "tower")),
    ("열교환기", ("열교환기", "heatexchanger")),
    ("사외배관", ("사외배관",)),
    ("기타", ()),
)


def _facility_choice_key(value: object) -> str:
    n = _norm(value)
    if not n:
        return "기타"
    # More specific storage-tank check precedes general storage/facility terms.
    for label, aliases in _FACILITY_CHOICES[:-1]:
        if any(_norm(alias) and _norm(alias) in n for alias in aliases):
            return label
    return "기타"


def render_facility_type_counts(project: Stage2Project) -> str:
    rows = cap_hwpx._confirmed_rows(project, "inventory.facilities", "cap.facility.equipment_specs")
    counts: Counter[str] = Counter()
    for row in rows:
        name = cap_hwpx._row_value(row, "설비종류", "설비형태", "장치·설비 종류", "설비명")
        if name:
            counts[_facility_choice_key(name)] += 1
    rendered = []
    for label, _aliases in _FACILITY_CHOICES:
        count = counts.get(label, 0)
        rendered.append(f"{_checked(count > 0, label)} ({count if count else ' '})기")
    return "\n".join(rendered)


def _extract_count(raw: str, *tokens: str) -> int | None:
    for token in tokens:
        pattern = rf"{re.escape(token)}[^0-9]{{0,12}}([0-9]+)\s*기?"
        m = re.search(pattern, raw, flags=re.I)
        if m:
            return int(m.group(1))
    return None


def render_loading_transport(value: object) -> str:
    raw = str(value or "").strip()
    n = _norm(raw)
    loading = any(token in n for token in ("입출하", "출하시설", "입하시설"))
    tank_lorry = "탱크로리" in n or "tanklorry" in n or "tanktruck" in n
    loading_n = _extract_count(raw, "입·출하", "입출하", "출하시설", "입하시설")
    lorry_n = _extract_count(raw, "탱크로리", "tank lorry", "tank truck")
    return (
        f"{_checked(loading, '입·출하 시설')} ({loading_n if loading_n is not None else ' '})기   "
        f"{_checked(tank_lorry, '보유 탱크로리')} ({lorry_n if lorry_n is not None else ' '})기"
    )


_PROTECTED_A = (
    "문화·집회시설", "종교시설", "판매시설", "운수시설", "의료시설", "교육·연구시설",
    "노유자시설", "숙박시설", "관광휴게시설", "수련시설", "주택",
)
_PROTECTED_B = ("주택·업무시설", "근린 생활시설", "위험물 저장 및 처리시설", "기타 건축물", "공업시설")
_ENV_RECEPTORS = (
    "생태·경관보호지역", "하천", "자연공원", "산림지 및 유적지", "습지보호지역",
    "상수원 및 취수원", "농경지", "기타 환경수용체",
)


def _selected_value_text(value: object) -> str:
    """Flatten selected values without treating every mapping key as selected."""
    parts: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if isinstance(item, bool):
                if item:
                    parts.append(str(key))
                continue
            state = _truth_state(item) if isinstance(item, (str, int, float)) else None
            if state is True:
                parts.append(str(key))
                continue
            if state is False:
                continue
            parts.append(_selected_value_text(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts.extend(_selected_value_text(item) for item in value)
    elif value not in (None, ""):
        parts.append(str(value))
    return " ".join(part for part in parts if part)


def _confirmed_selected_text(project: Stage2Project, *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        rec = project.get_field(key)
        if rec is None or rec.status not in CONFIRMED_STATUSES:
            continue
        parts.append(_selected_value_text(rec.value))
    return " ".join(parts)


def _render_option_group(title: str, options: Sequence[str], selected_text: str) -> str:
    n = _norm(selected_text)
    rendered = [_checked(_norm(option) in n, option) for option in options]
    return f"{title}\n" + "   ".join(rendered)


def render_protected_target_groups(selected_text: str) -> tuple[str, str, str]:
    return (
        _render_option_group("갑종 보호대상 (적용되는 모든 것에 표시)", _PROTECTED_A, selected_text),
        _render_option_group("을종 보호대상 (적용되는 모든 것에 표시)", _PROTECTED_B, selected_text),
        _render_option_group("환경수용체 (적용되는 모든 것에 표시)", _ENV_RECEPTORS, selected_text),
    )


def _docx_form3(doc, project: Stage2Project) -> None:
    level = project.cap_group or report._text(project, "cap.business.writing_level", default=report.MISSING)
    submission = report._text(project, "cap.business.submission_type", default="")
    joint = report._text(project, "cap.business.joint_emergency_plan", default="")
    other_review = report._text(project, "cap.business.other_system_review", default="")
    residents = report._text(project, "cap.business.residents_in_overall_range", default="")
    accident = report._text(project, "cap.business.recent_accident", default="")
    rows = (
        ("사업장명", project.company_name or report.MISSING),
        ("단위공장명", report._text(project, "cap.business.unit_plant_name", default=report.MISSING)),
        ("사업자 등록번호", report._text(project, "cap.business.registration_no", default=report.MISSING)),
        ("대표자", report._text(project, "cap.business.representative", default=report.MISSING)),
        ("우편번호/주소", report._text(project, "business.address", default=report.MISSING)),
        ("산업단지", report._text(project, "cap.business.industrial_complex", default=report.MISSING)),
        ("대표전화", report._text(project, "cap.business.contact", default=report.MISSING)),
        ("제출구분", render_submission_type(submission)),
        ("작성수준", render_writing_level(level)),
        ("공동비상대응계획 수립 여부", render_joint_emergency(joint)),
        ("유사제도 심사결과 활용", render_other_system_review(other_review)),
        ("총괄영향범위내 주민여부", render_yes_no(residents)),
        ("최근 3년간 화학사고 발생 여부", render_yes_no(accident)),
        ("화학사고예방관리계획서 작성자", report._text(project, "cap.business.writer_info", default=report.MISSING)),
        ("담당자 연락처", report._text(project, "cap.business.writer_contact", default=report.MISSING)),
        ("담당자 메일주소", report._text(project, "cap.business.writer_email", default=report.MISSING)),
    )
    report._add_key_value_form(doc, "별지 제3호서식", "사업장 일반정보", rows)


def _docx_facility_overview(doc, project: Stage2Project, *, detailed: bool) -> None:
    chemicals = report._chemical_rows(project)
    chem_lines = []
    for row in chemicals[:12]:
        chem_lines.append(
            f"{report._row_value(row, '물질명', '유해화학물질명')} / "
            f"{report._row_value(row, 'CAS 번호', '화학물질식별번호')} / "
            f"{report._row_value(row, '최대보유량', '최대보유량(kg)')}"
        )
    loading = report._text(project, "cap.basic.loading_transport", default="")
    rows = (
        ("단위공장 구성", report._text(project, "cap.basic.unit_facility_overview", default=report.MISSING)),
        ("공정개요", report._text(project, "process.description", default=report.MISSING)),
        ("장치·설비 종류 및 수량", render_facility_type_counts(project)),
        ("입·출하 및 운반시설", render_loading_transport(loading)),
        ("유해화학물질 및 취급량", "\n".join(chem_lines) if chem_lines else report.MISSING),
    )
    reference = "별지 제5호서식" if detailed else "별지 제4호서식"
    title = "세부 취급시설 개요" if detailed else "총괄 취급시설 개요"
    report._add_key_value_form(doc, reference, title, rows)


def _docx_protected_blocks(doc, selected_text: str) -> None:
    for block in render_protected_target_groups(selected_text):
        doc.add_paragraph(block)


def _docx_form8(doc, project: Stage2Project) -> None:
    report._add_form_heading(doc, "별지 제8호서식", "사업장 주변 환경 정보")
    doc.add_paragraph("1. 사업장 입지현황")
    selected = _confirmed_selected_text(project, "cap.site.surrounding_environment", "cap.offsite.population_and_protected_targets")
    _docx_protected_blocks(doc, selected)
    spec = report.FormSpec("", "", ("일련번호", "보호대상 종류", "보호대상 명칭", "거리(m)"))
    rows = report._generic_form_rows(
        project,
        "cap.site.surrounding_environment",
        spec,
        (("일련번호", "연번"), ("보호대상 종류", "종류"), ("보호대상 명칭", "명칭"), ("거리", "거리(m)")),
    )
    report._add_form_table(doc, spec, rows)
    report._add_attachment_line(doc, "보호대상 위치도", report._doc_value(project, "cap.site.surrounding_map"))


def _industrial_location_value(project: Stage2Project) -> str:
    # Only an explicit inside/outside statement may select this checkbox.
    explicit = _confirmed_selected_text(project, "cap.offsite.business_location", "cap.offsite.site_location")
    n = _norm(explicit)
    inside = "산업단지내" in n
    outside = "산업단지외" in n
    return f"{_checked(inside, '산업단지 내')}   {_checked(outside, '산업단지 외')}"


def _docx_form12(doc, project: Stage2Project) -> None:
    report._add_form_heading(doc, "별지 제12호서식", "사고시나리오 사업장 주변지역 영향 평가")
    rows = (
        ("사고시나리오", report._text(project, "cap.offsite.target_facility_selection", default=report.MISSING)),
        ("영향범위", report._text(project, "cap.offsite.impact_range_result", default=report.MISSING)),
        ("영향범위 내 주민의 수", report._text(project, "cap.offsite.population_and_protected_targets", default=report.MISSING)),
        ("사업장 위치", _industrial_location_value(project)),
    )
    table = doc.add_table(rows=len(rows), cols=2)
    report._set_table_borders(table)
    for i, (label, value) in enumerate(rows):
        report._set_cell_text(table.rows[i].cells[0], label, bold=True, size=8)
        report._set_cell_text(table.rows[i].cells[1], value, size=8)
    selected = _confirmed_selected_text(project, "cap.offsite.population_and_protected_targets", "cap.offsite.surrounding_impact_result")
    _docx_protected_blocks(doc, selected)
    report._add_attachment_line(doc, "주요 보호대상 위치", report._doc_value(project, "cap.offsite.protected_target_map"))
    p = doc.add_paragraph()
    p.add_run("사고원점의 좌표: ").bold = True
    p.add_run(report._text(project, "cap.offsite.accident_origin_coordinate", default=report.MISSING))


def _docx_form13(doc, project: Stage2Project) -> None:
    report._add_form_heading(doc, "별지 제13호서식", "총괄영향범위 사업장 주변지역 영향 평가")
    selected = _confirmed_selected_text(project, "cap.offsite.population_and_protected_targets", "cap.offsite.surrounding_impact_result")
    _docx_protected_blocks(doc, selected)
    report._add_attachment_line(doc, "주요 보호대상 위치", report._doc_value(project, "cap.offsite.protected_target_map"))
    spec = report.FormSpec("", "", ("일련번호", "보호대상 명칭", "보호대상 종류"))
    rows = report._generic_form_rows(
        project,
        "cap.offsite.population_and_protected_targets",
        spec,
        (("일련번호", "연번"), ("보호대상 명칭", "명칭"), ("보호대상 종류", "종류")),
    )
    report._add_form_table(doc, spec, rows)


def _choice_scalar_value(label: str, value: object) -> str:
    if label == "제출구분":
        return render_submission_type(value)
    if label == "작성수준":
        return render_writing_level(value)
    if label == "공동비상대응계획 수립 여부":
        return render_joint_emergency(value)
    if label == "유사제도 심사결과 활용":
        return render_other_system_review(value)
    if label in {"총괄영향범위내 주민여부", "최근 3년간 화학사고 발생 여부"}:
        return render_yes_no(value)
    if label == "입·출하 및 운반시설":
        return render_loading_transport(value)
    return str(value or "")


def install_cap_final_form_runtime() -> None:
    if getattr(cap_hwpx, _INSTALL_MARKER, False):
        return

    original_fill_scalar_batch = cap_hwpx._fill_scalar_batch
    original_review_appendix = report._add_review_appendix

    def fill_scalar_batch_with_statutory_choices(source: bytes, specs):
        normalized = []
        for table_anchor, label, value in specs:
            if label in {
                "제출구분", "작성수준", "공동비상대응계획 수립 여부", "유사제도 심사결과 활용",
                "총괄영향범위내 주민여부", "최근 3년간 화학사고 발생 여부", "입·출하 및 운반시설",
            }:
                value = _choice_scalar_value(label, value)
            normalized.append((table_anchor, label, value))
        return original_fill_scalar_batch(source, normalized)

    def review_appendix_final_output(doc, project, system: str, status) -> None:
        if str(system or "").strip().upper() == "CAP":
            return
        original_review_appendix(doc, project, system, status)

    cap_hwpx._fill_scalar_batch = fill_scalar_batch_with_statutory_choices
    cap_hwpx._facility_count_text = render_facility_type_counts

    # v2 CAP renderer calls these helpers from this module dynamically.
    report._cap_form3 = _docx_form3
    report._cap_facility_overview = _docx_facility_overview
    report._cap_form8 = _docx_form8
    report._cap_form12 = _docx_form12
    report._cap_form13 = _docx_form13
    report._add_review_appendix = review_appendix_final_output

    setattr(cap_hwpx, _INSTALL_MARKER, True)
