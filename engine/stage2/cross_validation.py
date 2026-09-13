from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from typing import Any, Iterable, Mapping

from engine.legal_terminology import psm_field_label, psm_section_name

from .project import CONFIRMED_STATUSES, EvidenceRef, FieldRecord, Stage2Project
from .requirements import cap_field_labels, psm_field_labels, requirement_specs_for_project


PROGRAM_STATUS_LABELS = {
    "HOLD": "검증 보류",
    "REVIEW_REQUIRED": "사람 확인 필요",
    "PASS": "확인 완료",
    "NOT_APPLICABLE": "해당 없음",
}


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    status: str
    system: str
    section: str
    legal_item: str
    message: str
    field_keys: tuple[str, ...] = ()
    legal_basis: str = ""
    details: str = ""

    @property
    def status_label(self) -> str:
        return PROGRAM_STATUS_LABELS.get(self.status, self.status)

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["status_label"] = self.status_label
        return raw


@dataclass(frozen=True)
class CrossValidationReport:
    issues: tuple[ValidationIssue, ...]
    checked_rules: int

    @property
    def hold_count(self) -> int:
        return sum(issue.status == "HOLD" for issue in self.issues)

    @property
    def review_count(self) -> int:
        return sum(issue.status == "REVIEW_REQUIRED" for issue in self.issues)

    @property
    def pass_count(self) -> int:
        return sum(issue.status == "PASS" for issue in self.issues)

    @property
    def final_export_allowed(self) -> bool:
        return self.hold_count == 0 and self.review_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_rules": self.checked_rules,
            "hold_count": self.hold_count,
            "review_count": self.review_count,
            "pass_count": self.pass_count,
            "final_export_allowed": self.final_export_allowed,
            "program_status_note": (
                "검증 보류/사람 확인 필요/확인 완료는 프로그램의 검증상태이며 법령상의 판정용어가 아닙니다."
            ),
            "issues": [issue.to_dict() for issue in self.issues],
        }


TAG_ALIASES = (
    "tag",
    "tagno",
    "tag번호",
    "설비번호",
    "기기번호",
    "장치번호",
    "시설번호",
    "equipmentid",
    "equipmenttag",
)
PROTECTED_TAG_ALIASES = (
    "보호대상",
    "보호대상설비",
    "보호대상기기번호",
    "보호대상설비번호",
    "protectedequipmenttag",
    "equipmenttag",
    "설비번호",
    "기기번호",
)
CAS_ALIASES = (
    "cas",
    "casno",
    "cas번호",
    "casnumber",
)

TECHNICAL_EVIDENCE_INPUT_KINDS = {
    "DOCUMENT_SET",
    "DRAWING",
    "DRAWING_SET",
    "DRAWING_AND_DATA",
    "DRAWING_AND_TABLE",
    "ANALYSIS_DOCUMENT",
    "CALCULATION_AND_DRAWING",
    "STRUCTURED_TABLE_AND_CALCULATION",
    "CALCULATION_AND_MODEL",
}


# Cross-checks that are useful before semantic document parsing exists.
# The current engine checks availability/provenance and, when both values are
# structured tables, performs deterministic identifier-set comparisons.
CORE_CROSSCHECK_PAIRS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "inventory.facilities",
        "psm.psi.equipment_specs",
        "PSM-FACILITY-EQUIPMENT",
        "공정안전자료",
        "유해하거나 위험한 설비의 목록 및 사양",
    ),
    (
        "psm.psi.equipment_specs",
        "psm.psi.relief_device_specs",
        "PSM-EQUIPMENT-RELIEF",
        "공정안전자료",
        "유해하거나 위험한 설비의 목록 및 사양 / 안전밸브 및 파열판 관련 자료",
    ),
    (
        "inventory.chemicals",
        "cap.chemical.details",
        "CAP-CHEMICAL-INVENTORY",
        "기본정보",
        "유해화학물질 목록 및 명세",
    ),
    (
        "inventory.facilities",
        "cap.facility.equipment_specs",
        "CAP-FACILITY-EQUIPMENT",
        "시설정보",
        "장치·설비 목록 및 명세",
    ),
)


def _compact_key(value: object) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(value).strip().lower())


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).upper()


def _as_rows(value: Any) -> list[Mapping[str, Any]] | None:
    if not isinstance(value, list):
        return None
    if not value:
        return []
    if not all(isinstance(row, Mapping) for row in value):
        return None
    return [dict(row) for row in value]


def _extract_values(rows: Iterable[Mapping[str, Any]], aliases: Iterable[str]) -> list[str]:
    alias_set = {_compact_key(alias) for alias in aliases}
    values: list[str] = []
    for row in rows:
        normalized = {_compact_key(key): value for key, value in row.items()}
        for alias in alias_set:
            if alias not in normalized:
                continue
            value = _normalized_text(normalized[alias])
            if value:
                values.append(value)
            break
    return values


def _duplicates(values: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    dup: set[str] = set()
    for value in values:
        if value in seen:
            dup.add(value)
        seen.add(value)
    return dup


def _field_label(key: str) -> str:
    psm_labels = psm_field_labels()
    cap_labels = cap_field_labels()
    fallback = psm_labels.get(key) or cap_labels.get(key) or key
    return psm_field_label(key, fallback)


def _record(project: Stage2Project, key: str) -> FieldRecord | None:
    return project.get_field(key)


def _confirmed(project: Stage2Project, key: str) -> bool:
    record = _record(project, key)
    return bool(record and record.status in CONFIRMED_STATUSES)


def _valid_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "")))


def _technical_evidence_issues(project: Stage2Project) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for spec in requirement_specs_for_project(project):
        if spec.input_kind not in TECHNICAL_EVIDENCE_INPUT_KINDS:
            continue
        if not spec.field_keys:
            continue

        confirmed_records = [
            project.get_field(key)
            for key in spec.field_keys
            if _confirmed(project, key)
        ]
        confirmed_records = [record for record in confirmed_records if record is not None]
        if not confirmed_records:
            continue

        for record in confirmed_records:
            if record.evidence:
                continue
            section = psm_section_name(spec.key, spec.section) if spec.system == "PSM" else spec.section
            issues.append(
                ValidationIssue(
                    code="EVIDENCE-MISSING",
                    status="HOLD",
                    system=spec.system,
                    section=section,
                    legal_item=spec.label,
                    message=(
                        f"{_field_label(record.key)} 항목이 확인 상태이지만 연결된 근거자료가 없습니다. "
                        "기술자료는 근거파일 또는 출처가 확인되기 전까지 최종본에 사용할 수 없습니다."
                    ),
                    field_keys=(record.key,),
                    legal_basis=spec.legal_basis,
                )
            )
    return issues


def _evidence_hash_issues(project: Stage2Project) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for key, record in project.fields.items():
        for evidence in record.evidence:
            if evidence.source_type != "ATTACHMENT":
                continue
            if _valid_sha256(evidence.sha256):
                continue
            issues.append(
                ValidationIssue(
                    code="EVIDENCE-HASH-INVALID",
                    status="HOLD",
                    system="COMMON",
                    section="근거자료 관리",
                    legal_item=_field_label(key),
                    message="첨부 근거자료의 SHA-256이 없거나 형식이 올바르지 않습니다.",
                    field_keys=(key,),
                    details=evidence.source_name,
                )
            )
    return issues


def _crosscheck_availability_issues(project: Stage2Project) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for spec in requirement_specs_for_project(project):
        if not spec.cross_checks or not spec.field_keys:
            continue
        if not any(_confirmed(project, key) for key in spec.field_keys):
            continue

        missing = [key for key in spec.cross_checks if not _confirmed(project, key)]
        if not missing:
            continue

        section = psm_section_name(spec.key, spec.section) if spec.system == "PSM" else spec.section
        issues.append(
            ValidationIssue(
                code="CROSSCHECK-SOURCE-MISSING",
                status="REVIEW_REQUIRED",
                system=spec.system,
                section=section,
                legal_item=spec.label,
                message=(
                    "등록된 자료의 상호 일치 여부를 확인하려면 추가 자료 확인이 필요합니다: "
                    + ", ".join(_field_label(key) for key in missing)
                ),
                field_keys=tuple(spec.field_keys) + tuple(missing),
                legal_basis=spec.legal_basis,
            )
        )
    return issues


def _duplicate_identifier_issue(
    *,
    system: str,
    section: str,
    legal_item: str,
    field_key: str,
    values: list[str],
) -> ValidationIssue | None:
    duplicates = sorted(_duplicates(values))
    if not duplicates:
        return None
    return ValidationIssue(
        code="DUPLICATE-IDENTIFIER",
        status="HOLD",
        system=system,
        section=section,
        legal_item=legal_item,
        message="동일한 설비 식별번호가 중복되어 자료 간 일치 여부를 확정할 수 없습니다.",
        field_keys=(field_key,),
        details=", ".join(duplicates),
    )


def _structured_identifier_issues(project: Stage2Project) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    structured_fields = (
        ("inventory.facilities", "COMMON", "공통 시설정보", "시설·설비 목록"),
        ("psm.psi.equipment_specs", "PSM", "공정안전자료", "유해하거나 위험한 설비의 목록 및 사양"),
        ("psm.psi.relief_device_specs", "PSM", "공정안전자료", "안전밸브 및 파열판 관련 자료"),
        ("cap.facility.equipment_specs", "CAP", "시설정보", "장치·설비 목록 및 명세"),
    )
    for key, system, section, legal_item in structured_fields:
        record = _record(project, key)
        if not record or record.status not in CONFIRMED_STATUSES:
            continue
        rows = _as_rows(record.value)
        if rows is None:
            continue
        aliases = PROTECTED_TAG_ALIASES if key == "psm.psi.relief_device_specs" else TAG_ALIASES
        values = _extract_values(rows, aliases)
        issue = _duplicate_identifier_issue(
            system=system,
            section=section,
            legal_item=legal_item,
            field_key=key,
            values=values,
        )
        if issue:
            issues.append(issue)

    return issues


def _compare_tag_sets(
    project: Stage2Project,
    left_key: str,
    right_key: str,
    code: str,
    section: str,
    legal_item: str,
) -> ValidationIssue | None:
    left = _record(project, left_key)
    right = _record(project, right_key)
    if not left or not right:
        return None
    if left.status not in CONFIRMED_STATUSES or right.status not in CONFIRMED_STATUSES:
        return None
    left_rows = _as_rows(left.value)
    right_rows = _as_rows(right.value)
    if left_rows is None or right_rows is None:
        return None

    left_tags = set(_extract_values(left_rows, TAG_ALIASES))
    right_aliases = PROTECTED_TAG_ALIASES if right_key == "psm.psi.relief_device_specs" else TAG_ALIASES
    right_tags = set(_extract_values(right_rows, right_aliases))
    if not left_tags or not right_tags:
        return None

    if right_key == "psm.psi.relief_device_specs":
        unknown = sorted(right_tags - left_tags)
        if not unknown:
            return ValidationIssue(
                code=code,
                status="PASS",
                system="PSM",
                section=section,
                legal_item=legal_item,
                message="안전밸브 및 파열판 자료의 보호대상 설비 식별번호가 설비명세에서 확인됩니다.",
                field_keys=(left_key, right_key),
            )
        return ValidationIssue(
            code=code,
            status="HOLD",
            system="PSM",
            section=section,
            legal_item=legal_item,
            message="안전밸브 및 파열판 자료의 보호대상 중 설비명세에서 확인되지 않는 식별번호가 있습니다.",
            field_keys=(left_key, right_key),
            details=", ".join(unknown),
        )

    only_left = sorted(left_tags - right_tags)
    only_right = sorted(right_tags - left_tags)
    if not only_left and not only_right:
        return ValidationIssue(
            code=code,
            status="PASS",
            system="PSM" if code.startswith("PSM") else "CAP",
            section=section,
            legal_item=legal_item,
            message="두 구조화 자료에서 확인 가능한 설비 식별번호 집합이 일치합니다.",
            field_keys=(left_key, right_key),
        )

    details: list[str] = []
    if only_left:
        details.append(f"첫 번째 자료에만 있음: {', '.join(only_left)}")
    if only_right:
        details.append(f"두 번째 자료에만 있음: {', '.join(only_right)}")
    return ValidationIssue(
        code=code,
        status="REVIEW_REQUIRED",
        system="PSM" if code.startswith("PSM") else "CAP",
        section=section,
        legal_item=legal_item,
        message="두 구조화 자료의 설비 식별번호가 완전히 일치하지 않아 범위 확인이 필요합니다.",
        field_keys=(left_key, right_key),
        details=" / ".join(details),
    )


def _structured_pair_issues(project: Stage2Project) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for left_key, right_key, code, section, legal_item in CORE_CROSSCHECK_PAIRS:
        issue = _compare_tag_sets(project, left_key, right_key, code, section, legal_item)
        if issue:
            issues.append(issue)
    return issues


def _cas_set_issue(project: Stage2Project) -> ValidationIssue | None:
    left = _record(project, "inventory.chemicals")
    right = _record(project, "cap.chemical.details")
    if not left or not right:
        return None
    if left.status not in CONFIRMED_STATUSES or right.status not in CONFIRMED_STATUSES:
        return None
    left_rows = _as_rows(left.value)
    right_rows = _as_rows(right.value)
    if left_rows is None or right_rows is None:
        return None
    left_cas = set(_extract_values(left_rows, CAS_ALIASES))
    right_cas = set(_extract_values(right_rows, CAS_ALIASES))
    if not left_cas or not right_cas:
        return None
    if left_cas == right_cas:
        return ValidationIssue(
            code="CAP-CAS-CONSISTENCY",
            status="PASS",
            system="CAP",
            section="기본정보",
            legal_item="유해화학물질 목록 및 명세",
            message="구조화 자료에서 확인 가능한 CAS 번호 집합이 화학물질 목록과 일치합니다.",
            field_keys=("inventory.chemicals", "cap.chemical.details"),
        )
    return ValidationIssue(
        code="CAP-CAS-CONSISTENCY",
        status="REVIEW_REQUIRED",
        system="CAP",
        section="기본정보",
        legal_item="유해화학물질 목록 및 명세",
        message="화학물질 목록과 유해화학물질 상세 명세의 CAS 번호 범위가 달라 작성대상 범위를 확인해야 합니다.",
        field_keys=("inventory.chemicals", "cap.chemical.details"),
        details=(
            f"화학물질 목록에만 있음: {', '.join(sorted(left_cas-right_cas)) or '-'} / "
            f"상세 명세에만 있음: {', '.join(sorted(right_cas-left_cas)) or '-'}"
        ),
    )


def validate_stage2_project(project: Stage2Project) -> CrossValidationReport:
    """Run conservative deterministic Stage-2 cross-validation.

    This function never interprets drawings, PDFs, or free-form prose. Content
    consistency is checked only when the compared values are confirmed and are
    supplied as structured ``list[dict]`` data. Missing evidence or unavailable
    comparison sources are surfaced for review instead of being guessed.
    """
    issues: list[ValidationIssue] = []
    checked_rules = 0

    for runner in (
        _evidence_hash_issues,
        _technical_evidence_issues,
        _crosscheck_availability_issues,
        _structured_identifier_issues,
        _structured_pair_issues,
    ):
        checked_rules += 1
        issues.extend(runner(project))

    checked_rules += 1
    cas_issue = _cas_set_issue(project)
    if cas_issue:
        issues.append(cas_issue)

    # Stable ordering: blocking issues first, then review items, then passes.
    order = {"HOLD": 0, "REVIEW_REQUIRED": 1, "PASS": 2, "NOT_APPLICABLE": 3}
    issues.sort(key=lambda issue: (order.get(issue.status, 9), issue.system, issue.section, issue.code))
    return CrossValidationReport(issues=tuple(issues), checked_rules=checked_rules)
