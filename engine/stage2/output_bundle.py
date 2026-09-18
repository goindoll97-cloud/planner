from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from .output_provenance import (
    OutputProvenance,
    output_provenance_filename,
    output_provenance_json_bytes,
)


def verified_bundle_filename(file_name: str) -> str:
    path = Path(str(file_name or "output.docx"))
    return f"{path.stem}_검증묶음.zip"


def build_verified_output_bundle(
    data: bytes,
    provenance: OutputProvenance,
) -> bytes:
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("출력물 bytes가 비어 있어 검증 묶음을 만들 수 없습니다.")

    payload = bytes(data)
    digest = sha256(payload).hexdigest()
    if digest != provenance.sha256:
        raise ValueError(
            "출력물 bytes의 SHA-256이 검증정보와 일치하지 않아 검증 묶음 생성을 중단했습니다."
        )

    file_name = Path(str(provenance.file_name or "")).name
    if not file_name:
        raise ValueError("검증정보의 출력 파일명이 비어 있습니다.")

    manifest_name = output_provenance_filename(file_name)
    guide = (
        "Stage 2 규정서식 출력물 검증 묶음\n"
        f"문서: {provenance.system_label}\n"
        f"상태: {provenance.state}\n"
        f"출력파일: {file_name}\n"
        f"SHA-256: {provenance.sha256}\n"
        f"규정서식 baseline SHA-256: {provenance.baseline_sha256}\n"
        f"규정서식 baseline schema: {provenance.baseline_schema_version}\n"
        f"생성시점(UTC): {provenance.generated_at_utc}\n"
        "검증정보 JSON의 SHA-256 값은 이 ZIP 안의 DOCX bytes를 기준으로 계산되었습니다.\n"
    )

    out = BytesIO()
    with ZipFile(out, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(file_name, payload)
        archive.writestr(manifest_name, output_provenance_json_bytes(provenance))
        archive.writestr("검증안내.txt", guide.encode("utf-8"))
    return out.getvalue()
