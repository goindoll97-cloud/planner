from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Iterable

from engine.regulatory_tables import PROJECT_ROOT, observed_pdf_paths, observed_source


PROGRAM_FORM_SOURCES = {
    "공정안전보고서": ("PSM_NOTICE",),
    "화학사고예방관리계획서": ("CAP_DRAFT",),
}


@dataclass(frozen=True)
class OfficialFormFile:
    law_key: str
    source_title: str
    effective_date: str
    issue_number: str
    monitor_status: str
    form_reference: str
    file_name: str
    relative_path: str
    sha256: str

    @property
    def full_path(self) -> Path:
        return PROJECT_ROOT / self.relative_path


def _normalize(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _form_number(reference: str) -> str:
    text = _normalize(reference)
    match = re.search(r"별지(?:제)?(\d+)(?:호)?서식", text)
    if match:
        return match.group(1)
    match = re.search(r"별지(?:제)?(\d+)", text)
    return match.group(1) if match else ""


def _reference_from_path(path: Path) -> str:
    logical = _normalize(path.stem.split("__", 1)[0])
    match = re.search(r"별지(?:제)?0*(\d+)(?:호)?(?:서식)?", logical)
    return f"별지 제{int(match.group(1))}호서식" if match else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matching_pdf_paths(law_key: str, form_reference: str) -> list[Path]:
    number = _form_number(form_reference)
    if not number:
        return []
    return [path for path in observed_pdf_paths(law_key) if _form_number(_reference_from_path(path)) == number]


def _row(law_key: str, path: Path, form_reference: str) -> OfficialFormFile | None:
    source = observed_source(law_key) or {}
    if str(source.get("monitor_status") or "") != "CURRENT":
        return None
    try:
        rel = str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return None
    return OfficialFormFile(
        law_key=law_key,
        source_title=str(source.get("title") or law_key),
        effective_date=str(source.get("effective_date") or ""),
        issue_number=str(source.get("issue_number") or ""),
        monitor_status=str(source.get("monitor_status") or ""),
        form_reference=form_reference,
        file_name=path.name,
        relative_path=rel,
        sha256=_sha256(path),
    )


def resolve_official_form(
    form_reference: str,
    *,
    candidate_law_keys: Iterable[str],
) -> list[OfficialFormFile]:
    """Resolve a statutory 별지서식 only from CURRENT official observed PDFs."""
    results: list[OfficialFormFile] = []
    for law_key in candidate_law_keys:
        for path in _matching_pdf_paths(law_key, form_reference):
            item = _row(law_key, path, form_reference)
            if item is not None:
                results.append(item)
    return results


def resolve_official_form_for_program(form_reference: str, program_label: str) -> list[OfficialFormFile]:
    """Resolve a form only within the selected legal regime.

    Form numbers may overlap across regulations, so cross-regime number-only
    matching is intentionally prohibited.
    """
    return resolve_official_form(
        form_reference,
        candidate_law_keys=PROGRAM_FORM_SOURCES.get(program_label, ()),
    )


def list_official_forms_for_program(program_label: str) -> list[OfficialFormFile]:
    results: list[OfficialFormFile] = []
    for law_key in PROGRAM_FORM_SOURCES.get(program_label, ()):
        for path in observed_pdf_paths(law_key):
            reference = _reference_from_path(path)
            if not reference:
                continue
            item = _row(law_key, path, reference)
            if item is not None:
                results.append(item)
    results.sort(key=lambda item: int(_form_number(item.form_reference) or 9999))
    return results


def unique_official_form_for_program(form_reference: str, program_label: str) -> OfficialFormFile | None:
    rows = resolve_official_form_for_program(form_reference, program_label)
    return rows[0] if len(rows) == 1 and rows[0].full_path.exists() else None


def official_form_bytes(form: OfficialFormFile) -> bytes:
    return form.full_path.read_bytes()
