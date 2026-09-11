from __future__ import annotations

"""Local evidence archive for approved legal appendices.

The law API remains the freshness/change-detection source. This module keeps a
human-readable, immutable local copy of the exact PDF that supported each
approved regulatory table. Decision engines continue to use reviewed CSV DBs;
the archived PDF is the auditable source document that a reviewer can open
immediately when a result cites an appendix.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .regulatory_tables import (
    APPROVED_DIR,
    CANDIDATE_DIR,
    PROJECT_ROOT,
    observed_pdf_paths,
    observed_source,
)


ARCHIVE_ROOT = PROJECT_ROOT / "data" / "legal_archive"
INDEX_FILE = ARCHIVE_ROOT / "index.json"

EVIDENCE_CONFIG: dict[str, dict[str, Any]] = {
    "PSM_ANNEX13": {
        "law_key": "PSM_DECREE",
        "regime": "PSM",
        "document_folder": "산업안전보건법_시행령",
        "appendix_no": 13,
        "label": "PSM 시행령 별표 13 유해·위험물질 규정량",
        "filename": "별표13_유해위험물질_규정량.pdf",
        "candidate": CANDIDATE_DIR / "psm_annex13_candidate.csv",
        "candidate_meta": CANDIDATE_DIR / "psm_annex13_candidate.meta.json",
        "approved": APPROVED_DIR / "psm_annex13.csv",
        "audit": APPROVED_DIR / "psm_annex13.approval.json",
    },
    "CAP_QTY_APP1": {
        "law_key": "CAP_QTY",
        "regime": "CAP",
        "document_folder": "유해화학물질_규정수량",
        "appendix_no": 1,
        "label": "화사계 별표 1 유해·위험성 그룹별 규정수량",
        "filename": "별표1_유해위험성_그룹별_규정수량.pdf",
        "candidate": CANDIDATE_DIR / "cap_qty_app1_candidate.csv",
        "candidate_meta": CANDIDATE_DIR / "cap_qty_app1_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app1.csv",
        "audit": APPROVED_DIR / "cap_qty_app1.approval.json",
    },
    "CAP_QTY_APP2": {
        "law_key": "CAP_QTY",
        "regime": "CAP",
        "document_folder": "유해화학물질_규정수량",
        "appendix_no": 2,
        "label": "화사계 별표 2 인체·생태유해성 물질별 규정수량",
        "filename": "별표2_인체생태유해성_물질별_규정수량.pdf",
        "candidate": CANDIDATE_DIR / "cap_qty_app2_candidate.csv",
        "candidate_meta": CANDIDATE_DIR / "cap_qty_app2_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app2.csv",
        "audit": APPROVED_DIR / "cap_qty_app2.approval.json",
    },
    "CAP_QTY_APP3": {
        "law_key": "CAP_QTY",
        "regime": "CAP",
        "document_folder": "유해화학물질_규정수량",
        "appendix_no": 3,
        "label": "화사계 별표 3 사고대비물질별 규정수량",
        "filename": "별표3_사고대비물질별_규정수량.pdf",
        "candidate": CANDIDATE_DIR / "cap_qty_app3_candidate.csv",
        "candidate_meta": CANDIDATE_DIR / "cap_qty_app3_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app3.csv",
        "audit": APPROVED_DIR / "cap_qty_app3.approval.json",
    },
    "CAP_QTY_APP4": {
        "law_key": "CAP_QTY",
        "regime": "CAP",
        "document_folder": "유해화학물질_규정수량",
        "appendix_no": 4,
        "label": "화사계 별표 4 최대보유량 산정 방법",
        "filename": "별표4_최대보유량_산정_방법.pdf",
        "candidate": CANDIDATE_DIR / "cap_qty_app4_candidate.csv",
        "candidate_meta": CANDIDATE_DIR / "cap_qty_app4_candidate.meta.json",
        "approved": APPROVED_DIR / "cap_qty_app4.csv",
        "audit": APPROVED_DIR / "cap_qty_app4.approval.json",
    },
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_result(meta: dict[str, Any]) -> dict[str, Any]:
    nested = meta.get("result")
    return nested if isinstance(nested, dict) else meta


def _candidate_status(config: dict[str, Any]) -> str:
    meta = _read_json(Path(config["candidate_meta"]))
    return str(_candidate_result(meta).get("status", "")).strip()


def _candidate_source_path(config: dict[str, Any]) -> Path | None:
    meta = _read_json(Path(config["candidate_meta"]))
    result = _candidate_result(meta)
    raw = str(result.get("source_file") or meta.get("source_file") or "").strip()
    if raw:
        path = PROJECT_ROOT / raw
        if path.exists() and path.suffix.lower() == ".pdf":
            return path
    return None


def _pick_observed_pdf(config: dict[str, Any]) -> Path | None:
    appendix_no = int(config["appendix_no"])
    pattern = re.compile(rf"별표0*{appendix_no}(?:_|$)")
    matches: list[Path] = []
    for path in observed_pdf_paths(str(config["law_key"])):
        logical = path.stem.split("__", 1)[0].replace(" ", "")
        if pattern.search(logical):
            matches.append(path)
    return matches[0] if len(matches) == 1 else None


def _approved_matches_candidate(config: dict[str, Any]) -> bool:
    approved = Path(config["approved"])
    candidate = Path(config["candidate"])
    return approved.exists() and candidate.exists() and _sha256(approved) == _sha256(candidate)


def _safe_effective_date(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"\d{4}[-./]\d{1,2}[-./]\d{1,2}", text)
    if match:
        return match.group().replace(".", "-").replace("/", "-")
    return text or "시행일_미확인"


def _index_payload() -> dict[str, Any]:
    payload = _read_json(INDEX_FILE)
    if not payload:
        payload = {"schema_version": 1, "updated_at_utc": "", "entries": {}}
    if not isinstance(payload.get("entries"), dict):
        payload["entries"] = {}
    return payload


def _update_index(key: str, entry: dict[str, Any]) -> None:
    payload = _index_payload()
    payload["updated_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload["entries"][key] = entry
    _write_json(INDEX_FILE, payload)


def archive_approved_evidence(key: str) -> dict[str, Any]:
    """Archive the exact source PDF associated with an approved DB table.

    The function fails closed if the approved CSV is absent, or when an older
    approval cannot be tied safely to the currently extracted candidate/source.
    """
    config = EVIDENCE_CONFIG.get(key)
    if config is None:
        return {"status": "UNKNOWN_KEY", "message": f"근거자료 설정이 없는 규정표입니다: {key}"}

    approved = Path(config["approved"])
    if not approved.exists():
        candidate_status = _candidate_status(config)
        suffix = (
            " 현재 자동추출 결과는 REVIEW_REQUIRED이므로 사람이 검토한 뒤 승인 DB로 저장해야 합니다."
            if candidate_status == "REVIEW_REQUIRED"
            else ""
        )
        return {
            "status": "NOT_APPROVED",
            "message": f"{config['label']} 승인 DB가 없어 근거 PDF를 보관하지 않았습니다.{suffix}",
        }

    audit = _read_json(Path(config["audit"]))
    audit_source_hash = str(audit.get("source_pdf_sha256") or "").strip()

    # Older legacy approvals did not record source-PDF hashes. In that case we
    # archive only when the approved CSV is byte-identical to the current
    # candidate CSV, proving that the current candidate is the approved table.
    if not audit_source_hash and not _approved_matches_candidate(config):
        return {
            "status": "SOURCE_LINK_UNVERIFIED",
            "message": (
                f"{config['label']} 승인 DB와 현재 후보표의 연결을 확인할 수 없어 다른 PDF를 근거로 보관하지 않았습니다. "
                "최신 공식 PDF에서 다시 추출·검토 후 승인하세요."
            ),
        }

    source_path = _candidate_source_path(config) or _pick_observed_pdf(config)
    if source_path is None:
        return {"status": "SOURCE_NOT_FOUND", "message": f"{config['label']}의 로컬 원본 PDF를 찾지 못했습니다."}

    actual_hash = _sha256(source_path)
    if audit_source_hash and actual_hash != audit_source_hash:
        return {
            "status": "HASH_MISMATCH",
            "message": f"{config['label']} 승인 당시 PDF 해시와 현재 로컬 PDF가 달라 보관을 중단했습니다.",
        }

    source = observed_source(str(config["law_key"])) or {}
    observed_hashes = set(str(v) for v in (source.get("attachment_hashes") or {}).values() if v)
    if observed_hashes and actual_hash not in observed_hashes:
        return {
            "status": "HASH_MISMATCH",
            "message": f"{config['label']} PDF가 현재 법령감시에서 확인한 공식 첨부파일 해시와 일치하지 않습니다.",
        }

    effective_date = _safe_effective_date(source.get("effective_date"))
    folder = ARCHIVE_ROOT / str(config["regime"]) / str(config["document_folder"]) / effective_date
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / str(config["filename"])

    if target.exists() and _sha256(target) != actual_hash:
        target = folder / f"{target.stem}__{actual_hash[:12]}{target.suffix}"
    if not target.exists():
        shutil.copy2(source_path, target)

    manifest = {
        "schema_version": 1,
        "status": "APPROVED_EVIDENCE",
        "regulatory_table_key": key,
        "label": config["label"],
        "law_source_key": config["law_key"],
        "source_title": source.get("title", ""),
        "effective_date": source.get("effective_date", ""),
        "issue_number": source.get("issue_number", ""),
        "archived_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "original_runtime_file": str(source_path.relative_to(PROJECT_ROOT)),
        "archived_file": str(target.relative_to(PROJECT_ROOT)),
        "archive_folder": str(folder.relative_to(PROJECT_ROOT)),
        "sha256": actual_hash,
        "approved_db_file": str(approved.relative_to(PROJECT_ROOT)),
        "approved_at_utc": audit.get("approved_at_utc", ""),
        "approval_audit_file": str(Path(config["audit"]).relative_to(PROJECT_ROOT)),
    }
    manifest_path = target.with_suffix(".manifest.json")
    _write_json(manifest_path, manifest)
    manifest["manifest_file"] = str(manifest_path.relative_to(PROJECT_ROOT))
    _update_index(key, manifest)

    return {
        "status": "ARCHIVED",
        "message": f"{config['label']} 근거 PDF를 로컬 보관소에 저장했습니다.",
        "key": key,
        "label": config["label"],
        "archived_file": manifest["archived_file"],
        "archive_folder": manifest["archive_folder"],
        "sha256": actual_hash,
        "effective_date": source.get("effective_date", ""),
    }


def sync_approved_evidence(keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    wanted = list(keys) if keys is not None else list(EVIDENCE_CONFIG.keys())
    return [archive_approved_evidence(key) for key in wanted if key in EVIDENCE_CONFIG]


def evidence_for_key(key: str) -> dict[str, Any] | None:
    entry = (_index_payload().get("entries") or {}).get(key)
    if not isinstance(entry, dict):
        return None
    raw = str(entry.get("archived_file") or "")
    path = PROJECT_ROOT / raw if raw else None
    if path is None or not path.exists():
        return None
    return dict(entry)


def evidence_rows(keys: Iterable[str] | None = None) -> list[dict[str, Any]]:
    """Return archive status with approval state separated from file storage.

    '미보관' by itself was ambiguous: it could mean the table had never been
    approved, or that an approved table still needed archive synchronization.
    The UI now makes that distinction explicit.
    """
    wanted = list(keys) if keys is not None else list(EVIDENCE_CONFIG.keys())
    rows: list[dict[str, Any]] = []
    for key in wanted:
        config = EVIDENCE_CONFIG.get(key)
        if config is None:
            continue
        entry = evidence_for_key(key)
        approved = Path(config["approved"]).exists()
        candidate_status = _candidate_status(config)
        if entry:
            storage_status = "보관됨"
            next_action = "확인 가능"
        elif approved:
            storage_status = "승인됨 · 근거 PDF 동기화 필요"
            next_action = "현재 승인본 근거 PDF 동기화"
        elif candidate_status == "REVIEW_REQUIRED":
            storage_status = "승인 전"
            next_action = "후보표 검토 후 승인 DB로 저장"
        else:
            storage_status = "미보관"
            next_action = "공식 PDF 추출부터 확인"

        rows.append(
            {
                "key": key,
                "근거": config["label"],
                "승인상태": "승인됨" if approved else "미승인",
                "보관상태": storage_status,
                "다음조치": next_action,
                "후보검증": candidate_status,
                "시행일": (entry or {}).get("effective_date", ""),
                "로컬 PDF": (entry or {}).get("archived_file", ""),
                "SHA256": (entry or {}).get("sha256", ""),
            }
        )
    return rows


def archive_folder_for_key(key: str) -> Path | None:
    entry = evidence_for_key(key)
    if entry:
        raw = str(entry.get("archive_folder") or "")
        if raw:
            path = PROJECT_ROOT / raw
            if path.exists():
                return path
    return None


def open_archive_folder(key: str | None = None) -> dict[str, Any]:
    """Open the trusted local archive folder on the machine running Streamlit."""
    folder = archive_folder_for_key(key) if key else ARCHIVE_ROOT
    if folder is None:
        return {"status": "NOT_FOUND", "message": "해당 근거자료의 로컬 보관 폴더가 아직 없습니다."}
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if os.name == "nt":
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(folder)])
        else:
            subprocess.Popen(["xdg-open", str(folder)])
        return {"status": "OPENED", "message": f"로컬 폴더를 열었습니다: {folder}", "folder": str(folder)}
    except Exception as exc:
        return {
            "status": "OPEN_FAILED",
            "message": f"폴더를 자동으로 열지 못했습니다. 직접 여세요: {folder} ({type(exc).__name__})",
            "folder": str(folder),
        }
