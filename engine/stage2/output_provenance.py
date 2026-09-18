from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .project import Stage2Project
from .workflow import validation_confirmed, validation_fingerprint


SCHEMA_VERSION = "stage2-output-provenance-v1"
SYSTEM_LABELS = {
    "PSM": "공정안전보고서",
    "CAP": "화학사고예방관리계획서",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_system(system: str) -> str:
    value = str(system or "").strip().upper()
    if value not in SYSTEM_LABELS:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")
    return value


@dataclass(frozen=True)
class OutputProvenance:
    schema_version: str
    system: str
    system_label: str
    output_kind: str
    project_id: str
    company_name: str
    site_name: str
    generated_at_utc: str
    project_updated_at: str
    stage1_source_fingerprint: str
    validation_fingerprint: str
    validation_confirmed: bool
    final_ready: bool
    file_name: str
    mime_type: str
    sha256: str
    size_bytes: int

    @property
    def state(self) -> str:
        return "AUTHORING_READY" if self.final_ready else "REVIEW_ONLY"

    def to_dict(self) -> dict[str, object]:
        raw = asdict(self)
        raw["state"] = self.state
        return raw


def build_output_provenance(
    project: Stage2Project,
    system: str,
    data: bytes,
    *,
    file_name: str,
    final_ready: bool,
    output_kind: str = "STATUTORY_FORM_DOCX",
    mime_type: str = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
) -> OutputProvenance:
    system = _normalize_system(system)
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("출력물 bytes가 비어 있어 검증정보를 만들 수 없습니다.")
    if not str(file_name or "").strip():
        raise ValueError("출력 파일명이 비어 있습니다.")

    return OutputProvenance(
        schema_version=SCHEMA_VERSION,
        system=system,
        system_label=SYSTEM_LABELS[system],
        output_kind=str(output_kind or "STATUTORY_FORM_DOCX"),
        project_id=project.project_id,
        company_name=project.company_name,
        site_name=project.site_name,
        generated_at_utc=_utc_now(),
        project_updated_at=project.updated_at,
        stage1_source_fingerprint=str(project.stage1_source_fingerprint or ""),
        validation_fingerprint=validation_fingerprint(project),
        validation_confirmed=validation_confirmed(project),
        final_ready=bool(final_ready),
        file_name=Path(file_name).name,
        mime_type=str(mime_type),
        sha256=sha256(bytes(data)).hexdigest(),
        size_bytes=len(data),
    )


def output_provenance_json_bytes(provenance: OutputProvenance) -> bytes:
    return json.dumps(
        provenance.to_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ).encode("utf-8")


def output_provenance_filename(file_name: str) -> str:
    path = Path(str(file_name or "output.docx"))
    return f"{path.stem}_검증정보.json"
