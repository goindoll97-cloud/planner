from __future__ import annotations

"""Prepare the CAP emergency-response summary (Annex Form 16) for DOCX output.

The summary is assembled only from confirmed company facts plus deterministic
results already produced by Forms 1 and 12-15. It never invents accident types,
population, response resources, contacts or external-response arrangements.
"""

from dataclasses import dataclass
from collections.abc import Mapping, Sequence
from datetime import datetime
import re
from typing import Any
from zoneinfo import ZoneInfo

from .cap_form1_engine import build_cap_form1_data
from .cap_impact_engine import build_cap_form12_data
from .cap_risk_engine import build_cap_form15_data
from .project import CONFIRMED_STATUSES, Stage2Project


@dataclass(frozen=True)
class CAPForm16Data:
    business: dict[str, Any]
    chemical_rows: tuple[dict[str, Any], ...]
    scenario_rows: tuple[dict[str, Any], ...]
    internal_summary: tuple[tuple[str, str], ...]
    external_summary: tuple[tuple[str, str], ...]
    company_blockers: tuple[str, ...]
    dependency_blockers: tuple[str, ...]
    messages: tuple[str, ...]

    @property
    def blockers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(self.company_blockers + self.dependency_blockers))

    @property
    def ready(self) -> bool:
        return not self.blockers


def _clean(value: object) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null", "<na>"} else text


def _norm(value: object) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", _clean(value)).lower()


def _row_value(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = {_norm(key): value for key, value in row.items()}
    for alias in aliases:
        value = normalized.get(_norm(alias))
        if value not in (None, "") and _clean(value):
            return value
    return ""


def _confirmed_value(project: Stage2Project, key: str) -> object:
    rec = project.get_field(key)
    if rec is None or rec.status not in CONFIRMED_STATUSES:
        return ""
    return rec.value


def _flatten(value: object) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, Mapping):
        parts: list[str] = []
        for key, item in value.items():
            if item in (None, "", False):
                continue
            if item is True:
                parts.append(str(key))
                continue
            rendered = _flatten(item)
            if rendered:
                parts.append(f"{key}: {rendered}")
        return " / ".join(parts)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        parts = [_flatten(item) for item in value]
        return " / ".join(part for part in parts if part)
    return _clean(value)


def _confirmed_text(project: Stage2Project, *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        rendered = _flatten(_confirmed_value(project, key))
        if rendered and rendered not in parts:
            parts.append(rendered)
    return " / ".join(parts)


def _report_date(project: Stage2Project, override: str | None) -> tuple[str, str]:
    explicit = _clean(_confirmed_value(project, "cap.business.report_date"))
    if explicit:
        return explicit, "회사 확정 작성일"
    if override:
        return _clean(override), "DOCX 생성일"
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d"), "DOCX 생성일"


def _chemical_sources(project: Stage2Project) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_cas: dict[str, dict[str, Any]] = {}
    rec = project.get_field("inventory.chemicals")
    rows = rec.value if rec is not None and rec.status in CONFIRMED_STATUSES and isinstance(rec.value, list) else []
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        name = _clean(_row_value(row, "물질명", "유해화학물질명", "제품명"))
        cas = _clean(_row_value(row, "CAS 번호", "CAS No.", "CAS", "화학물질식별번호"))
        if name:
            by_name.setdefault(_norm(name), row)
        if cas:
            by_cas.setdefault(cas, row)
    return by_name, by_cas


def _form1_sources(project: Stage2Project) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    prepared = build_cap_form1_data(project)
    by_name: dict[str, dict[str, Any]] = {}
    by_cas: dict[str, dict[str, Any]] = {}
    for row in prepared.chemical_rows:
        item = dict(row)
        name = _clean(item.get("물질명"))
        cas = _clean(item.get("CAS No."))
        if name:
            by_name.setdefault(_norm(name), item)
        if cas:
            by_cas.setdefault(cas, item)
    return by_name, by_cas


def _summary_block(
    project: Stage2Project,
    specs: Sequence[tuple[str, tuple[str, ...]]],
    *,
    blocker_prefix: str,
) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    rows: list[tuple[str, str]] = []
    blockers: list[str] = []
    for label, keys in specs:
        value = _confirmed_text(project, *keys)
        rows.append((label, value))
        if not value:
            blockers.append(f"{blocker_prefix}: {label}의 회사 확정자료가 없습니다.")
    return tuple(rows), tuple(blockers)


def build_cap_form16_data(
    project: Stage2Project,
    *,
    report_date: str | None = None,
) -> CAPForm16Data:
    company_blockers: list[str] = []
    dependency_blockers: list[str] = []
    messages: list[str] = []

    date_value, date_basis = _report_date(project, report_date)
    writer_name = _clean(_confirmed_value(project, "cap.business.writer_name"))
    writer_department = _clean(_confirmed_value(project, "cap.business.writer_department"))
    writer_contact = _clean(_confirmed_value(project, "cap.business.writer_contact"))
    writer_email = _clean(_confirmed_value(project, "cap.business.writer_email"))
    representative = _clean(_confirmed_value(project, "cap.business.representative"))
    registration_no = _clean(_confirmed_value(project, "cap.business.registration_no"))
    address = _clean(_confirmed_value(project, "business.address"))

    business = {
        "사업장명": project.company_name,
        "대표자": representative,
        "우편번호/주소": address,
        "사업자 등록번호": registration_no,
        "담당자": " ".join(part for part in (writer_department, writer_name) if part),
        "담당자 연락처": writer_contact,
        "담당자 메일주소": writer_email,
        "작성일": date_value,
        "작성일 기준": date_basis,
    }
    for label in ("사업장명", "대표자", "우편번호/주소", "사업자 등록번호", "담당자", "담당자 연락처", "담당자 메일주소"):
        if not _clean(business.get(label)):
            company_blockers.append(f"별지 제16호 사업장 일반정보: {label}이 비어 있습니다.")

    form12 = build_cap_form12_data(project)
    form15 = build_cap_form15_data(project)
    if form12.blockers:
        dependency_blockers.extend(f"별지 제12호 연계: {item}" for item in form12.blockers)
    if form15.blockers:
        dependency_blockers.extend(f"별지 제15호 연계: {item}" for item in form15.blockers)

    raw_by_name, raw_by_cas = _chemical_sources(project)
    form1_by_name, form1_by_cas = _form1_sources(project)
    chemical_rows: list[dict[str, Any]] = []
    seen_chemicals: set[tuple[str, str]] = set()

    for scenario in form12.rows:
        chemical = _clean(scenario.get("유해화학물질명"))
        accident_type = _clean(scenario.get("사고유형"))
        if not chemical:
            continue
        raw = raw_by_name.get(_norm(chemical), {})
        cas = _clean(_row_value(raw, "CAS 번호", "CAS No.", "CAS", "화학물질식별번호"))
        legal = form1_by_cas.get(cas) if cas else None
        if legal is None:
            legal = form1_by_name.get(_norm(chemical), {})
        if not cas:
            cas = _clean((legal or {}).get("CAS No."))
        key = (cas or _norm(chemical), accident_type)
        if key in seen_chemicals:
            continue
        seen_chemicals.add(key)

        content = _clean(_row_value(raw, "함량(%)", "함량", "농도(%)"))
        holding = _clean((legal or {}).get("사업장 내 최대보유량(ton)"))
        row = {
            "연번": len(chemical_rows) + 1,
            "유해화학물질명": chemical,
            "화학물질식별번호(CAS 번호)": cas,
            "최대함량(%)": content,
            "최대보유량(ton)": holding,
            "사고유형": accident_type,
        }
        chemical_rows.append(row)
        for label in ("화학물질식별번호(CAS 번호)", "최대함량(%)", "최대보유량(ton)", "사고유형"):
            if not _clean(row.get(label)):
                company_blockers.append(f"별지 제16호 사고시나리오 물질 '{chemical}': {label}이 비어 있습니다.")

    if not form15.no_offsite_scenario and not chemical_rows:
        dependency_blockers.append("별지 제16호 사고시나리오 선정 유해화학물질 목록을 구성할 수 없습니다.")

    form15_by_name = {
        _clean(row.get("사고시나리오 명")): dict(row)
        for row in form15.scenario_rows
        if _clean(row.get("사고시나리오 명"))
    }
    scenario_rows: list[dict[str, Any]] = []
    for row in form12.rows:
        name = _clean(row.get("사고시나리오명"))
        risk = form15_by_name.get(name, {})
        scenario_rows.append({
            "연번": len(scenario_rows) + 1,
            "사고시나리오명": name,
            "유해화학물질명": _clean(row.get("유해화학물질명")),
            "대상 설비번호": _clean(row.get("대상 설비번호")),
            "사고유형": _clean(row.get("사고유형")),
            "시설빈도(/연)": _clean(risk.get("사고시나리오 시설빈도")),
            "장외거리(m)": row.get("장외거리(m)", ""),
            "위험도 주민수": risk.get("위험도 주민수", ""),
            "KORA/GIS 근거": _clean(row.get("KORA/GIS 근거")),
        })

    internal_specs = (
        ("비상연락체계", ("cap.prevention.emergency_contact_system",)),
        ("비상대응조직·임무", ("cap.prevention.emergency_org_chart", "cap.prevention.emergency_roles")),
        ("가동중지 권한·절차", ("cap.internal.shutdown_authority", "cap.internal.shutdown_procedure")),
        ("방재 인력·장비·물품", ("cap.internal.response_personnel", "cap.internal.response_equipment", "cap.internal.response_operations")),
        ("사업장 내부 정보전달", ("cap.internal.communication_system",)),
        ("취급시설 유형별 응급조치", ("cap.internal.facility_response_plan",)),
        ("사고원인 조사·재발방지", ("cap.internal.investigation_plan", "cap.internal.recurrence_prevention")),
        ("사고복구", ("cap.internal.recovery_plan",)),
    )
    internal_summary, internal_blockers = _summary_block(
        project, internal_specs, blocker_prefix="별지 제16호 내부 비상대응"
    )
    company_blockers.extend(internal_blockers)

    external_summary: tuple[tuple[str, str], ...] = ()
    if project.cap_group == "1군":
        external_specs = (
            ("지역사회 소통", ("cap.external.communication_plan", "cap.external.stakeholders", "cap.external.communication_schedule")),
            ("지역비상대응기관·인근사업장 공조", ("cap.external.mutual_aid_contacts", "cap.external.resource_support", "cap.external.joint_drill_plan")),
            ("주민 경보·대피", ("cap.external.warning_system", "cap.external.evacuation_routes", "cap.external.shelters")),
            ("응급의료", ("cap.external.medical_contacts",)),
            ("지역사회 고지", ("cap.external.notice_targets", "cap.external.notice_method", "cap.external.notice_content")),
        )
        external_summary, external_blockers = _summary_block(
            project, external_specs, blocker_prefix="별지 제16호 외부 비상대응"
        )
        company_blockers.extend(external_blockers)

    messages.append(f"별지 제16호 작성일은 {date_basis}({date_value})을 사용합니다.")
    if form15.no_offsite_scenario:
        messages.append("장외 사고시나리오 없음 확정으로 사고시나리오 연계 표는 작성대상 없음으로 처리합니다.")
    else:
        messages.append("사고시나리오 물질·사고유형은 별지 제12호, 시설빈도·위험도 주민수는 별지 제15호 결과를 재사용합니다.")

    return CAPForm16Data(
        business=business,
        chemical_rows=tuple(chemical_rows),
        scenario_rows=tuple(scenario_rows),
        internal_summary=internal_summary,
        external_summary=external_summary,
        company_blockers=tuple(dict.fromkeys(company_blockers)),
        dependency_blockers=tuple(dict.fromkeys(dependency_blockers)),
        messages=tuple(dict.fromkeys(messages)),
    )
