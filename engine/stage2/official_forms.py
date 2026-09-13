from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
from typing import Iterable

from engine.regulatory_tables import PROJECT_ROOT, observed_pdf_paths, observed_source


@dataclass(frozen=True)
class OfficialFormFile:
    law_key: str
    source_title: str
    effective_date: str
    issue_number: str
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

    matched: list[Path] = []
    patterns = (
        re.compile(rf"별지0*{re.escape(number)}(?:호)?(?:서식)?(?:_|$)"),
        re.compile(rf"별지제?0*{re.escape(number)}호?서식"),
    )
    for path in observed_pdf_paths(law_key):
        logical = _normalize(path.stem.split("__", 1)[0])
        if any(pattern.search(logical) for pattern in patterns):
            matched.append(path)
    return matched


def resolve_official_form(
    form_reference: str,
    *,
    candidate_law_keys: Iterable[str] = ("CAP_DRAFT", "CAP_RULE", "PSM_RULE", "PSM_NOTICE"),
) -> list[OfficialFormFile]:
    """Resolve a 법정 별지서식 only from current official observed PDFs.

    The law monitor downloads the official PDF attachments into the runtime
    pending store. This resolver never creates or reconstructs a statutory form.
    If more than one source matches, callers must present the ambiguity instead
    of choosing one automatically.
    """
    results: list[OfficialFormFile] = []
    for law_key in candidate_law_keys:
        source = observed_source(law_key) or {}
        for path in _matching_pdf_paths(law_key, form_reference):
            try:
                rel = str(path.relative_to(PROJECT_ROOT))
            except ValueError:
                continue
            results.append(
                OfficialFormFile(
                    law_key=law_key,
                    source_title=str(source.get("title") or law_key),
                    effective_date=str(source.get("effective_date") or ""),
                    issue_number=str(source.get("issue_number") or ""),
                    form_reference=form_reference,
                    file_name=path.name,
                    relative_path=rel,
                    sha256=_sha256(path),
                )
            )
    return results


def unique_official_form(form_reference: str) -> OfficialFormFile | None:
    rows = resolve_official_form(form_reference)
    return rows[0] if len(rows) == 1 and rows[0].full_path.exists() else None


def official_form_bytes(form: OfficialFormFile) -> bytes:
    return form.full_path.read_bytes()
