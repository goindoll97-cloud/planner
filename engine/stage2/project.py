from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping
import re
import uuid


EVIDENCE_STATUSES = (
    "VERIFIED",
    "USER_CONFIRMED",
    "CALCULATED",
    "AI_DRAFT",
    "HOLD",
)

CONFIRMED_STATUSES = {"VERIFIED", "USER_CONFIRMED", "CALCULATED"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _business_value(business: Mapping[str, object], *candidates: str) -> str:
    normalized = {re.sub(r"\s+", "", str(k)): v for k, v in business.items()}
    for candidate in candidates:
        key = re.sub(r"\s+", "", candidate)
        if key in normalized:
            return _text(normalized[key])
    return ""


def _subject_from_status(status: object) -> bool | None:
    """Map existing company-facing Stage-1 labels without re-deciding applicability."""
    text = _text(status).replace(" ", "")
    if not text:
        return None
    if any(token in text for token in ("비대상", "미해당", "면제", "의무없음", "제외설비")):
        return False
    if "1군" in text or "2군" in text:
        return True
    if "대상" in text:
        return True
    return None


def _cap_group_from_status(status: object) -> str:
    text = _text(status).replace(" ", "")
    if "1군" in text:
        return "1군"
    if "2군" in text:
        return "2군"
    return ""


@dataclass
class EvidenceRef:
    source_type: str
    source_name: str
    sha256: str = ""
    page: str = ""
    location: str = ""
    note: str = ""


@dataclass
class FieldRecord:
    key: str
    label: str
    value: Any = None
    status: str = "HOLD"
    evidence: list[EvidenceRef] = field(default_factory=list)
    note: str = ""
    updated_at: str = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.status not in EVIDENCE_STATUSES:
            raise ValueError(f"지원하지 않는 field status입니다: {self.status}")

    @property
    def confirmed(self) -> bool:
        return self.status in CONFIRMED_STATUSES

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "FieldRecord":
        evidence = [EvidenceRef(**item) for item in raw.get("evidence", [])]
        return cls(
            key=str(raw.get("key") or ""),
            label=str(raw.get("label") or raw.get("key") or ""),
            value=raw.get("value"),
            status=str(raw.get("status") or "HOLD"),
            evidence=evidence,
            note=str(raw.get("note") or ""),
            updated_at=str(raw.get("updated_at") or _utc_now()),
        )


@dataclass
class Stage2Project:
    project_id: str
    company_name: str
    site_name: str = ""
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)

    # Stage 1 legal applicability. These values must never be changed merely
    # because a user chooses not to author a document in this project.
    psm_required: bool | None = None
    cap_required: bool | None = None
    cap_group: str = ""

    # Stage 2 authoring scope. The authoring choice is operational only and
    # does not alter the Stage 1 legal decision.
    scope_confirmed: bool = False
    psm_selected: bool = False
    cap_selected: bool = False

    stage1_source_fingerprint: str = ""
    stage1_snapshot: dict[str, Any] = field(default_factory=dict)
    fields: dict[str, FieldRecord] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    schema_version: str = "stage2-project-v2"

    @property
    def psm_in_scope(self) -> bool:
        return bool(self.scope_confirmed and self.psm_selected and self.psm_required is True)

    @property
    def cap_in_scope(self) -> bool:
        return bool(self.scope_confirmed and self.cap_selected and self.cap_required is True)

    def set_authoring_scope(self, *, psm_selected: bool, cap_selected: bool) -> None:
        """Set the Stage 2 authoring scope without altering legal applicability."""
        if psm_selected and self.psm_required is not True:
            raise ValueError("Stage 1에서 공정안전보고서 제출 대상으로 확정되지 않은 프로젝트는 작성범위로 선택할 수 없습니다.")
        if cap_selected and self.cap_required is not True:
            raise ValueError("Stage 1에서 화학사고예방관리계획서 작성·제출 대상으로 확정되지 않은 프로젝트는 작성범위로 선택할 수 없습니다.")
        if not psm_selected and not cap_selected:
            raise ValueError("이번 프로젝트에서 작성할 문서를 하나 이상 선택해야 합니다.")
        self.psm_selected = bool(psm_selected)
        self.cap_selected = bool(cap_selected)
        self.scope_confirmed = True
        self.touch()

    def set_field(
        self,
        key: str,
        label: str,
        value: Any,
        status: str,
        evidence: list[EvidenceRef] | None = None,
        note: str = "",
    ) -> FieldRecord:
        if status not in EVIDENCE_STATUSES:
            raise ValueError(f"지원하지 않는 field status입니다: {status}")
        record = FieldRecord(
            key=key,
            label=label,
            value=value,
            status=status,
            evidence=list(evidence or []),
            note=note,
        )
        self.fields[key] = record
        self.touch()
        return record

    def get_field(self, key: str) -> FieldRecord | None:
        return self.fields.get(key)

    def touch(self) -> None:
        self.updated_at = _utc_now()

    def to_dict(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["fields"] = {key: value.to_dict() for key, value in self.fields.items()}
        return raw

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "Stage2Project":
        fields = {
            str(key): FieldRecord.from_dict(value)
            for key, value in dict(raw.get("fields") or {}).items()
        }

        # Backward compatibility: projects created before scope selection was
        # introduced are treated as having selected every legally applicable
        # document so existing work does not silently disappear.
        has_scope_fields = "scope_confirmed" in raw or "psm_selected" in raw or "cap_selected" in raw
        psm_required = raw.get("psm_required")
        cap_required = raw.get("cap_required")
        if has_scope_fields:
            scope_confirmed = bool(raw.get("scope_confirmed", False))
            psm_selected = bool(raw.get("psm_selected", False))
            cap_selected = bool(raw.get("cap_selected", False))
        else:
            scope_confirmed = True
            psm_selected = psm_required is True
            cap_selected = cap_required is True

        return cls(
            project_id=str(raw.get("project_id") or ""),
            company_name=str(raw.get("company_name") or ""),
            site_name=str(raw.get("site_name") or ""),
            created_at=str(raw.get("created_at") or _utc_now()),
            updated_at=str(raw.get("updated_at") or _utc_now()),
            psm_required=psm_required,
            cap_required=cap_required,
            cap_group=str(raw.get("cap_group") or ""),
            scope_confirmed=scope_confirmed,
            psm_selected=psm_selected,
            cap_selected=cap_selected,
            stage1_source_fingerprint=str(raw.get("stage1_source_fingerprint") or ""),
            stage1_snapshot=dict(raw.get("stage1_snapshot") or {}),
            fields=fields,
            notes=list(raw.get("notes") or []),
            schema_version=str(raw.get("schema_version") or "stage2-project-v2"),
        )


def create_project_from_stage1_snapshot(snapshot: Mapping[str, Any]) -> Stage2Project:
    """Create a Stage-2 project from the last completed Stage-1 decision.

    The snapshot contains only facts already supplied in the company workbook
    plus the Stage-1 rule-engine decision. Stage 2 does not re-decide legal
    applicability. A newly created project deliberately has no authoring scope
    until the user selects which legally applicable document(s) to prepare.
    """
    business = dict(snapshot.get("business") or {})
    decision = dict(snapshot.get("decision") or {})

    company_name = _business_value(
        business,
        "회사명",
        "사업장명",
        "업체명",
        "법인명",
    ) or "미지정 사업장"
    site_name = _business_value(
        business,
        "사업장명",
        "공장명",
        "사업소명",
    )

    project = Stage2Project(
        project_id=f"S2-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}",
        company_name=company_name,
        site_name=site_name,
        psm_required=_subject_from_status(decision.get("psm_status")),
        cap_required=_subject_from_status(decision.get("cap_status")),
        cap_group=_cap_group_from_status(decision.get("cap_status")),
        scope_confirmed=False,
        psm_selected=False,
        cap_selected=False,
        stage1_source_fingerprint=str(snapshot.get("source_fingerprint") or ""),
        stage1_snapshot={
            "decision": decision,
            "business": business,
            "documents": dict(snapshot.get("documents") or {}),
            "chemicals": list(snapshot.get("chemicals") or []),
            "facilities": list(snapshot.get("facilities") or []),
        },
    )

    source = project.stage1_source_fingerprint
    source_note = "Stage 1 회사 입력 Excel에서 승계"
    base_evidence = [
        EvidenceRef(
            source_type="STAGE1_WORKBOOK",
            source_name="회사 입력 Excel",
            sha256=source,
            note=source_note,
        )
    ] if source else []

    if company_name and company_name != "미지정 사업장":
        project.set_field(
            "business.company_name",
            "회사명",
            company_name,
            "VERIFIED" if source else "USER_CONFIRMED",
            evidence=base_evidence,
        )
    else:
        project.set_field("business.company_name", "회사명", company_name, "HOLD")

    if site_name:
        project.set_field(
            "business.site_name",
            "사업장명",
            site_name,
            "VERIFIED" if source else "USER_CONFIRMED",
            evidence=base_evidence,
        )

    address = _business_value(business, "사업장 소재지", "사업장주소", "주소", "소재지")
    if address:
        project.set_field(
            "business.address",
            "사업장 소재지",
            address,
            "VERIFIED" if source else "USER_CONFIRMED",
            evidence=base_evidence,
        )

    project.set_field(
        "inventory.chemicals",
        "화학물질 목록",
        list(snapshot.get("chemicals") or []),
        "VERIFIED" if snapshot.get("chemicals") else "HOLD",
        evidence=base_evidence if snapshot.get("chemicals") else [],
    )

    project.set_field(
        "inventory.facilities",
        "시설별 최대보유량 자료",
        list(snapshot.get("facilities") or []),
        "VERIFIED" if snapshot.get("facilities") else "HOLD",
        evidence=base_evidence if snapshot.get("facilities") else [],
    )

    return project
