from __future__ import annotations

from dataclasses import dataclass
import base64
from hashlib import sha256
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CONFIG = {
    "PSM": (
        PROJECT_ROOT / "data" / "templates" / "psm",
        "psm_statutory_forms_baseline.json",
        "psm_statutory_forms_baseline.docx.b64.*",
    ),
    "CAP": (
        PROJECT_ROOT / "data" / "templates" / "cap",
        "cap_statutory_forms_baseline.json",
        "cap_statutory_forms_baseline.docx.b64.*",
    ),
}


@dataclass(frozen=True)
class StatutoryBaselineIdentity:
    system: str
    schema_version: str
    role: str
    sha256: str
    source_description: str
    authority_note: str


def statutory_baseline_identity(system: str) -> StatutoryBaselineIdentity:
    system = str(system or "").strip().upper()
    if system not in _CONFIG:
        raise ValueError(f"지원하지 않는 보고서 종류입니다: {system}")

    folder, metadata_name, parts_glob = _CONFIG[system]
    metadata_path = folder / metadata_name
    if not metadata_path.exists():
        raise FileNotFoundError(f"{system} 규정서식 baseline metadata가 없습니다.")

    with metadata_path.open("r", encoding="utf-8") as handle:
        meta = json.load(handle)

    registered_sha = str(meta.get("sha256") or "").strip().lower()
    if len(registered_sha) != 64 or any(ch not in "0123456789abcdef" for ch in registered_sha):
        raise ValueError(f"{system} 규정서식 baseline 등록 SHA-256이 유효하지 않습니다.")

    parts = sorted(folder.glob(parts_glob))
    if not parts:
        raise FileNotFoundError(f"{system} 규정서식 baseline 파일이 준비되지 않았습니다.")
    decoded_parts: list[bytes] = []
    for part in parts:
        encoded = "".join(part.read_text(encoding="ascii").split())
        try:
            decoded_parts.append(base64.b64decode(encoded, validate=True))
        except Exception as exc:
            raise ValueError(f"{system} 규정서식 baseline 인코딩을 읽지 못했습니다.") from exc

    actual_sha = sha256(b"".join(decoded_parts)).hexdigest()
    if actual_sha != registered_sha:
        raise ValueError(f"{system} 규정서식 baseline 해시가 등록값과 일치하지 않습니다.")

    return StatutoryBaselineIdentity(
        system=system,
        schema_version=str(meta.get("schema_version") or ""),
        role=str(meta.get("role") or ""),
        sha256=registered_sha,
        source_description=str(meta.get("source_description") or ""),
        authority_note=str(meta.get("authority_note") or ""),
    )
