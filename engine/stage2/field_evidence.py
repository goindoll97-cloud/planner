from __future__ import annotations

from .project import CONFIRMED_STATUSES, EvidenceRef, Stage2Project


def attach_evidence_to_confirmed_field(
    project: Stage2Project,
    field_key: str,
    evidence: EvidenceRef,
    *,
    note: str = "",
) -> bool:
    """Attach one evidence file to an already-confirmed fact without changing its value.

    This is used when a company fact is stored as a scalar choice (for example
    공동제출 or 타 제도 심사결과 활용) but the final submission gate also needs
    the supporting company document. The function never creates or confirms a
    missing fact merely because a file was uploaded.
    """
    record = project.get_field(field_key)
    if record is None:
        raise ValueError(f"증빙을 연결할 확인값이 없습니다: {field_key}")
    if record.status not in CONFIRMED_STATUSES:
        raise ValueError(f"확인되지 않은 값에는 증빙파일을 완료 근거로 연결할 수 없습니다: {field_key}")
    if record.value in (None, "", [], {}):
        raise ValueError(f"빈 값에는 증빙파일을 연결할 수 없습니다: {field_key}")

    refs = list(record.evidence)
    if any(ref.sha256 == evidence.sha256 for ref in refs):
        return False
    refs.append(evidence)

    combined_note = str(record.note or "").strip()
    evidence_note = str(note or "").strip()
    if evidence_note and evidence_note not in combined_note:
        combined_note = " / ".join(part for part in (combined_note, evidence_note) if part)

    project.set_field(
        field_key,
        record.label,
        record.value,
        record.status,
        evidence=refs,
        note=combined_note,
    )
    return True
