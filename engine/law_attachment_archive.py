from __future__ import annotations

"""Local versioned storage for official law.go.kr attachment files.

The law monitor downloads every official attachment representation exposed by the
Open API (PDF and HWP/HWPX). Files first land in a pending area. Only after a
human approves the observed legal version are those exact bytes copied into the
approved source archive. Older approved versions are never overwritten.
"""

import json
import re
import shutil
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse
from zipfile import BadZipFile, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
PENDING_ATTACHMENT_DIR = RUNTIME_DIR / "law_pending"
APPROVED_SOURCE_ROOT = PROJECT_ROOT / "data" / "legal_archive" / "sources"
APPROVED_MONITOR_FILE = RUNTIME_DIR / "law_monitor_approved.json"
OBSERVED_MONITOR_FILE = RUNTIME_DIR / "law_monitor_last_observed.json"


def bytes_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", str(value or "")).strip("_.")
    return value[:120] or fallback


def _looks_like_hwpx(content: bytes) -> bool:
    if not content.startswith(b"PK"):
        return False
    try:
        with ZipFile(BytesIO(content), "r") as zf:
            names = set(zf.namelist())
            if "mimetype" in names:
                mime = zf.read("mimetype").decode("utf-8", errors="ignore").lower()
                if "hwp" in mime:
                    return True
            return any(name.startswith("Contents/section") and name.endswith(".xml") for name in names)
    except BadZipFile:
        return False


def detect_official_attachment_format(content: bytes, url: str = "", declared_kind: str = "") -> str:
    """Return pdf/hwpx/hwp/bin from bytes, never from a filename alone."""
    if content.startswith(b"%PDF"):
        return "pdf"
    if _looks_like_hwpx(content):
        return "hwpx"
    if content.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        return "hwp"

    suffix = Path(urlparse(str(url or "")).path).suffix.lower().lstrip(".")
    if suffix in {"pdf", "hwp", "hwpx"}:
        return suffix
    declared = str(declared_kind or "").lower()
    if declared in {"pdf", "hwp", "hwpx"}:
        return declared
    return "bin"


def save_pending_attachment(
    *,
    source_key: str,
    item_id: str,
    declared_kind: str,
    url: str,
    content: bytes,
) -> dict[str, str]:
    digest = bytes_sha256(content)
    detected = detect_official_attachment_format(content, url=url, declared_kind=declared_kind)
    target_dir = PENDING_ATTACHMENT_DIR / _safe_filename(source_key, "source")
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(item_id, "attachment")
    target = target_dir / f"{stem}__{declared_kind.upper()}__{digest[:16]}.{detected}"
    if not target.exists():
        target.write_bytes(content)
    return {
        "item_id": item_id,
        "declared_kind": declared_kind.upper(),
        "format": detected.upper(),
        "sha256": digest,
        "url": str(url or ""),
        "pending_file": str(target.relative_to(PROJECT_ROOT)),
        "file_name": target.name,
    }


def purge_deleted_placeholders(source_key: str) -> None:
    target_dir = PENDING_ATTACHMENT_DIR / _safe_filename(source_key, "source")
    if not target_dir.exists():
        return
    for path in target_dir.iterdir():
        if not path.is_file():
            continue
        if "삭제" in path.name or "폐지" in path.name:
            try:
                path.unlink()
            except OSError:
                pass


def prune_pending_source(source_key: str, keep_relative_paths: Iterable[str]) -> None:
    target_dir = PENDING_ATTACHMENT_DIR / _safe_filename(source_key, "source")
    if not target_dir.exists():
        return
    keep_names = {Path(str(value)).name for value in keep_relative_paths}
    for path in target_dir.iterdir():
        if path.is_file() and path.name not in keep_names:
            try:
                path.unlink()
            except OSError:
                pass


def _version_folder_name(row: dict[str, Any]) -> str:
    effective = re.sub(r"\D", "", str(row.get("effective_date") or ""))[:8] or "시행일미확인"
    issue = _safe_filename(str(row.get("issue_number") or ""), "발령번호미확인")
    serial = _safe_filename(str(row.get("serial") or ""), "일련번호미확인")
    return f"{effective}__{issue}__{serial}"


def archive_approved_source(row: dict[str, Any]) -> dict[str, Any]:
    """Copy one valid observed source's exact pending attachments into an immutable archive."""
    source_key = str(row.get("key") or "").strip()
    pending = row.get("attachment_files") or []
    if not source_key:
        return {"status": "INVALID", "message": "법령 source key가 없습니다."}
    if row.get("attachment_required") and not pending:
        return {"status": "MISSING_ATTACHMENTS", "message": f"{source_key}: 승인할 공식 첨부파일이 없습니다."}

    folder = APPROVED_SOURCE_ROOT / _safe_filename(source_key, "source") / _version_folder_name(row)
    folder.mkdir(parents=True, exist_ok=True)
    archived_files: list[dict[str, str]] = []

    for meta in pending:
        if not isinstance(meta, dict):
            continue
        raw = str(meta.get("pending_file") or "")
        src = PROJECT_ROOT / raw
        if not src.exists() or not src.is_file():
            return {"status": "SOURCE_NOT_FOUND", "message": f"승인 대상 첨부파일을 찾을 수 없습니다: {raw}"}
        actual = bytes_sha256(src.read_bytes())
        expected = str(meta.get("sha256") or "")
        if expected and actual != expected:
            return {"status": "HASH_MISMATCH", "message": f"승인 대상 첨부파일 해시가 달라졌습니다: {src.name}"}

        dst = folder / src.name
        if dst.exists() and bytes_sha256(dst.read_bytes()) != actual:
            dst = folder / f"{src.stem}__{actual[:12]}{src.suffix}"
        if not dst.exists():
            shutil.copy2(src, dst)
        archived = dict(meta)
        archived["archived_file"] = str(dst.relative_to(PROJECT_ROOT))
        archived_files.append(archived)

    manifest = {
        "schema_version": 1,
        "status": "APPROVED_OFFICIAL_SOURCE",
        "key": source_key,
        "regime": row.get("regime", ""),
        "title": row.get("title", ""),
        "target": row.get("target", ""),
        "serial": row.get("serial", ""),
        "stable_id": row.get("stable_id", ""),
        "issue_date": row.get("issue_date", ""),
        "issue_number": row.get("issue_number", ""),
        "effective_date": row.get("effective_date", ""),
        "revision_type": row.get("revision_type", ""),
        "ministry": row.get("ministry", ""),
        "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "attachment_files": archived_files,
    }
    manifest_path = folder / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "ARCHIVED",
        "archive_folder": str(folder.relative_to(PROJECT_ROOT)),
        "manifest_file": str(manifest_path.relative_to(PROJECT_ROOT)),
        "files": archived_files,
    }


def _load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _load_approved_monitor() -> dict[str, Any]:
    return _load_json_file(APPROVED_MONITOR_FILE)


def _source_identity_matches(observed: dict[str, Any], approved: dict[str, Any]) -> bool:
    """Compare the exact legal version and attachment hashes, ignoring stale UI status labels."""
    for key in ("serial", "effective_date", "issue_date", "issue_number"):
        if str(observed.get(key) or "").strip() != str(approved.get(key) or "").strip():
            return False
    return (observed.get("attachment_hashes") or {}) == (approved.get("attachment_hashes") or {})


def approved_source_is_current(source_key: str) -> bool:
    """True when the latest valid observation equals the approved local version.

    Immediately after a human approves a BASELINE_UNAPPROVED/UPDATE_PENDING row,
    the observation file may still carry that pre-approval label. Equality of
    official version metadata and attachment hashes is therefore authoritative;
    the user does not need to run the API check a second time just to unlock the
    newly approved HWPX.
    """
    observed_payload = _load_json_file(OBSERVED_MONITOR_FILE)
    rows = observed_payload.get("rows") or []
    approved = ((_load_approved_monitor().get("sources") or {}).get(source_key) or {})
    if not isinstance(rows, list) or not isinstance(approved, dict) or not approved:
        return False
    for row in rows:
        if not isinstance(row, dict) or str(row.get("key") or "") != source_key:
            continue
        if not row.get("observation_valid"):
            return False
        if str(row.get("monitor_status") or "") == "CURRENT":
            return True
        return _source_identity_matches(row, approved)
    return False


def approved_source_files(
    source_key: str,
    suffixes: Iterable[str] | None = None,
    *,
    require_current: bool = False,
) -> list[Path]:
    """Return exact archived files for the approved version of a law source.

    When ``require_current`` is true, no file is returned unless the latest
    valid official observation is identical to the approved local baseline.
    """
    if require_current and not approved_source_is_current(source_key):
        return []
    source = ((_load_approved_monitor().get("sources") or {}).get(source_key) or {})
    if not isinstance(source, dict):
        return []
    archive = source.get("approved_archive") or {}
    files = archive.get("files") or [] if isinstance(archive, dict) else []
    wanted = {str(v).lower() for v in suffixes} if suffixes is not None else None
    out: list[Path] = []
    for meta in files:
        if not isinstance(meta, dict):
            continue
        raw = str(meta.get("archived_file") or "")
        if not raw:
            continue
        path = PROJECT_ROOT / raw
        if not path.exists():
            continue
        if wanted is not None and path.suffix.lower() not in wanted:
            continue
        out.append(path)
    return out


def approved_source_archive_rows() -> list[dict[str, Any]]:
    payload = _load_approved_monitor()
    sources = payload.get("sources") or {}
    if not isinstance(sources, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key, source in sources.items():
        if not isinstance(source, dict):
            continue
        archive = source.get("approved_archive") or {}
        files = archive.get("files") or [] if isinstance(archive, dict) else []
        formats = sorted({str(item.get("format") or "") for item in files if isinstance(item, dict) and item.get("format")})
        rows.append({
            "key": key,
            "법령·규정": source.get("title", ""),
            "시행일": source.get("effective_date", ""),
            "발령번호": source.get("issue_number", ""),
            "최신확인": "CURRENT" if approved_source_is_current(str(key)) else "확인 필요",
            "첨부파일수": len(files),
            "보관형식": ", ".join(formats),
            "로컬보관폴더": archive.get("archive_folder", "") if isinstance(archive, dict) else "",
        })
    return rows


def approved_source_library() -> list[dict[str, Any]]:
    """Return the registry hierarchy, enriched with approved, locally available files."""
    registry_path = PROJECT_ROOT / "data" / "law_registry.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        registry = []
    if not isinstance(registry, list):
        return []

    approved_sources = _load_approved_monitor().get("sources") or {}
    result: list[dict[str, Any]] = []
    for entry in registry:
        if not isinstance(entry, dict):
            continue
        key = str(entry.get("key") or "")
        source = approved_sources.get(key, {}) if isinstance(approved_sources, dict) else {}
        source = source if isinstance(source, dict) else {}
        archive = source.get("approved_archive") or {}
        archived = archive.get("files") or [] if isinstance(archive, dict) else []
        files: list[dict[str, Any]] = []
        for meta in archived:
            if not isinstance(meta, dict):
                continue
            relative = str(meta.get("archived_file") or "")
            path = PROJECT_ROOT / relative if relative else None
            if path is None or not path.is_file():
                continue
            files.append({
                "item_id": str(meta.get("item_id") or path.stem),
                "format": str(meta.get("format") or path.suffix.lstrip(".")).upper(),
                "path": relative,
                "file_name": str(meta.get("file_name") or path.name),
                "sha256": str(meta.get("sha256") or ""),
            })
        result.append({
            **entry,
            "effective_date": str(source.get("effective_date") or ""),
            "issue_number": str(source.get("issue_number") or ""),
            "status": "최신 확인" if approved_source_is_current(key) else ("확인 필요" if source else "승인 원본 없음"),
            "files": files,
        })
    return result
