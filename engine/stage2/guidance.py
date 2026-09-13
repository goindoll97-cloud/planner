from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from .intake import IntakeRequirement, extract_form_references, selected_requirement_specs
from .project import Stage2Project
from .requirements import COMMON_REQUIREMENTS, RequirementSpec, cap_requirement_specs, psm_requirement_specs


ACTION_EXCEL = "통합 Excel 추가작성 필요"
ACTION_FILE = "파일 업로드 필요"
ACTION_REVIEW = "사람 확인 필요"
ACTION_PROGRAM = "프로그램 처리 예정"

ACTION_ORDER = (ACTION_EXCEL, ACTION_FILE, ACTION_REVIEW, ACTION_PROGRAM)

ATTACHMENT_INPUT_KINDS = {
    "DOCUMENT_SET",
    "DRAWING",
    "DRAWING_SET",
    "DRAWING_AND_DATA",
    "DRAWING_AND_TABLE",
    "ANALYSIS_DOCUMENT",
    "CALCULATION_AND_DRAWING",
    "CALCULATION_AND_MODEL",
}

STATIC_WORKBOOK_LOCATIONS = {
    "business.company_name": "01_사업장정보",
    "business.site_name": "01_사업장정보",
    "business.address": "01_사업장정보",
    "cap.business.representative": "01_사업장정보",
    "cap.business.registration_no": "01_사업장정보",
    "cap.business.contact": "01_사업장정보",
    "cap.business.submission_type": "01_사업장정보",
    "cap.business.writing_level": "01_사업장정보",
    "cap.business.other_system_review": "01_사업장정보",
    "cap.business.writer_info": "01_사업장정보",
    "inventory.chemicals": "02_화학물질정보",
    "cap.chemical.details": "02_화학물질정보",
    "inventory.facilities": "03_설비정보",
    "psm.psi.equipment_specs": "03_설비정보",
    "cap.facility.equipment_specs": "03_설비정보",
    "psm.psi.relief_device_specs": "04_안전밸브_파열판",
    "cap.safety.relief_device_specs": "04_안전밸브_파열판",
    "psm.psi.gas_detection": "05_가스누출감지_경보장치",
    "cap.safety.gas_detection": "05_가스누출감지_경보장치",
    "process.description": "06_공정정보",
    "psm.psi.machinery_list": "10_동력기계",
    "psm.psi.piping_gasket_specs": "11_배관_개스킷",
    "cap.safety.waste_treatment": "20_배출물질_처리시설",
}


@dataclass(frozen=True)
class BasisEntry:
    system: str
    section: str
    label: str
    text: str


@dataclass(frozen=True)
class GuidanceReference:
    title: str
    pages: tuple[int, ...]


@dataclass(frozen=True)
class RequirementGuidance:
    requirement_key: str
    action_type: str
    action_text: str
    workbook_locations: tuple[str, ...]
    current_gap: str
    statutory_bases: tuple[BasisEntry, ...]
    detailed_bases: tuple[BasisEntry, ...]
    references: tuple[GuidanceReference, ...]
    form_references: tuple[str, ...]


def _safe_sheet_name(name: str) -> str:
    text = re.sub(r"[\\/*?:\[\]]", "_", str(name))
    return text[:31]


def _dynamic_sheet_name(spec: RequirementSpec) -> str:
    if spec.system == "PSM":
        return _safe_sheet_name(f"공정안전보고서_{spec.section}")
    if spec.system == "CAP":
        section = re.sub(r"^3\.\d+\s*", "", spec.section).strip()
        return _safe_sheet_name(f"화학사고예방관리계획서_{section or '작성정보'}")
    return _safe_sheet_name("공통_추가정보")


def workbook_locations_for_fields(project: Stage2Project, field_keys: Iterable[str]) -> tuple[str, ...]:
    locations: list[str] = []
    specs = selected_requirement_specs(project)
    for key in field_keys:
        if key in STATIC_WORKBOOK_LOCATIONS:
            location = STATIC_WORKBOOK_LOCATIONS[key]
            if location not in locations:
                locations.append(location)
            continue
        if key.startswith("documents.") or key == "psm.psi.msds":
            if "07_도면_첨부자료목록" not in locations:
                locations.append("07_도면_첨부자료목록")
            continue
        related = next((spec for spec in specs if key in spec.field_keys), None)
        if related is None:
            continue
        if related.input_kind in ATTACHMENT_INPUT_KINDS:
            location = "07_도면_첨부자료목록"
        else:
            location = _dynamic_sheet_name(related)
        if location not in locations:
            locations.append(location)
    return tuple(locations)


def _related_specs(project: Stage2Project, item: IntakeRequirement) -> list[RequirementSpec]:
    target_fields = set(item.confirmed_fields) | set(item.received_unconfirmed_fields) | set(item.missing_fields)
    rows: list[RequirementSpec] = []
    for spec in selected_requirement_specs(project):
        if spec.key == item.requirement_key or (target_fields and target_fields.intersection(spec.field_keys)):
            rows.append(spec)
    return rows


def _basis_entry(spec: RequirementSpec) -> BasisEntry:
    return BasisEntry(
        system={"PSM": "공정안전보고서", "CAP": "화학사고예방관리계획서", "COMMON": "공통자료"}.get(spec.system, spec.system),
        section=spec.section,
        label=spec.label,
        text=spec.legal_basis.strip(),
    )


def _is_statutory_basis(text: str) -> bool:
    return any(token in text for token in ("법 제", "시행령", "시행규칙", "산업안전보건법", "화학물질관리법"))


def _is_detailed_basis(spec: RequirementSpec, text: str) -> bool:
    return bool(
        spec.legal_status == "DETAIL_OF_STATUTORY_ITEM"
        or any(token in text for token in ("고시", "작성규정", "별표", "별지"))
    )


def _reference_for_spec(spec: RequirementSpec) -> GuidanceReference | None:
    if not spec.manual_pages:
        return None
    if spec.system == "CAP":
        title = "화학사고예방관리계획서 작성 매뉴얼"
    elif spec.system == "PSM":
        title = "공정안전보고서 지원시스템 작성예시집(형식 참고)"
    else:
        return None
    return GuidanceReference(title=title, pages=tuple(spec.manual_pages))


def _dedupe_basis(entries: Iterable[BasisEntry]) -> tuple[BasisEntry, ...]:
    seen: set[tuple[str, str, str]] = set()
    out: list[BasisEntry] = []
    for entry in entries:
        token = (entry.system, entry.label, entry.text)
        if not entry.text or token in seen:
            continue
        seen.add(token)
        out.append(entry)
    return tuple(out)


def _dedupe_refs(entries: Iterable[GuidanceReference]) -> tuple[GuidanceReference, ...]:
    seen: set[tuple[str, tuple[int, ...]]] = set()
    out: list[GuidanceReference] = []
    for entry in entries:
        token = (entry.title, entry.pages)
        if token in seen:
            continue
        seen.add(token)
        out.append(entry)
    return tuple(out)


def _classify_action(item: IntakeRequirement) -> str:
    fields = set(item.missing_fields)
    if fields:
        if (
            item.input_kind in ATTACHMENT_INPUT_KINDS
            or all(key.startswith("documents.") or key == "psm.psi.msds" for key in fields)
        ):
            return ACTION_FILE
        return ACTION_EXCEL
    if item.received_unconfirmed_fields:
        return ACTION_REVIEW
    automation = str(item.automation or "").upper()
    if any(token in automation for token in ("CALCULATE", "GENERATE", "DRAFT")):
        return ACTION_PROGRAM
    return ACTION_REVIEW


def build_requirement_guidance(project: Stage2Project, item: IntakeRequirement) -> RequirementGuidance:
    action_type = _classify_action(item)
    unresolved_fields = tuple(item.missing_fields + item.received_unconfirmed_fields)
    locations = workbook_locations_for_fields(project, unresolved_fields)
    related = _related_specs(project, item)

    statutory: list[BasisEntry] = []
    detailed: list[BasisEntry] = []
    references: list[GuidanceReference] = []
    forms: list[str] = []

    for spec in related:
        basis = str(spec.legal_basis or "").strip()
        if basis:
            entry = _basis_entry(spec)
            if _is_statutory_basis(basis):
                statutory.append(entry)
            if _is_detailed_basis(spec, basis):
                detailed.append(entry)
            for form in extract_form_references(basis):
                if form not in forms:
                    forms.append(form)
        ref = _reference_for_spec(spec)
        if ref is not None:
            references.append(ref)

    # Common requirements intentionally carry little or no legal wording. The
    # report-specific requirements that use the same field supply the legal
    # connection. If that connection is absent, keep the gap visible rather
    # than inventing a citation.
    if not statutory and item.legal_basis and _is_statutory_basis(item.legal_basis):
        statutory.append(BasisEntry(item.system_label, item.section, item.label, item.legal_basis))
    if not detailed and item.legal_basis and any(token in item.legal_basis for token in ("고시", "작성규정", "별표", "별지")):
        detailed.append(BasisEntry(item.system_label, item.section, item.label, item.legal_basis))

    if item.form_references:
        for form in item.form_references:
            if form not in forms:
                forms.append(form)

    missing_labels = list(item.missing_labels)
    review_labels = list(item.received_unconfirmed_labels)
    gap_parts: list[str] = []
    if missing_labels:
        gap_parts.append("미작성·미등록: " + ", ".join(missing_labels))
    if review_labels:
        gap_parts.append("접수 후 확인 필요: " + ", ".join(review_labels))
    current_gap = " / ".join(gap_parts) if gap_parts else item.label

    if action_type == ACTION_FILE:
        where = ", ".join(locations) if locations else "통합 작성자료의 도면·첨부자료 목록"
        action_text = f"{where}에 파일명·도면번호를 적고, 실제 파일을 아래 첨부자료 업로드에서 제출하세요."
    elif action_type == ACTION_REVIEW:
        action_text = "자료는 접수되어 있으나 내용이 확정되지 않았습니다. 원본 자료와 사업장 담당자 확인 후 확정하세요."
    elif action_type == ACTION_PROGRAM:
        action_text = "필요한 선행자료가 확인되면 프로그램이 계산 또는 초안 작성을 수행합니다. 결과는 사람이 검토해야 합니다."
    else:
        where = ", ".join(locations) if locations else "통합 작성자료의 해당 질문 시트"
        action_text = f"{where}에서 사업장 실제 내용을 추가 작성한 뒤 통합 작성자료를 다시 업로드하세요."

    return RequirementGuidance(
        requirement_key=item.requirement_key,
        action_type=action_type,
        action_text=action_text,
        workbook_locations=locations,
        current_gap=current_gap,
        statutory_bases=_dedupe_basis(statutory),
        detailed_bases=_dedupe_basis(detailed),
        references=_dedupe_refs(references),
        form_references=tuple(forms),
    )


def all_requirement_specs_for_library() -> list[RequirementSpec]:
    rows: list[RequirementSpec] = list(COMMON_REQUIREMENTS)
    rows.extend(psm_requirement_specs())
    rows.extend(cap_requirement_specs("1군"))
    seen: set[str] = set()
    out: list[RequirementSpec] = []
    for spec in rows:
        if spec.key in seen:
            continue
        seen.add(spec.key)
        out.append(spec)
    return out


def requirement_library_search_text(spec: RequirementSpec) -> str:
    return " ".join(
        [
            spec.key,
            spec.system,
            spec.section,
            spec.label,
            spec.description,
            spec.legal_basis,
            " ".join(spec.field_keys),
            " ".join(spec.suggested_evidence),
        ]
    ).lower()
