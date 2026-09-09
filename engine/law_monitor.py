from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

from .law_api import (
    credential_status,
    download_binary,
    extract_attachments,
    fetch_source_payload,
    search_current_source,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
REGISTRY_FILE = DATA_DIR / "law_registry.json"
RUNTIME_DIR = DATA_DIR / "runtime"
OBSERVED_FILE = RUNTIME_DIR / "law_monitor_last_observed.json"
APPROVED_FILE = RUNTIME_DIR / "law_monitor_approved.json"
PENDING_PDF_DIR = RUNTIME_DIR / "law_pending"


@dataclass(frozen=True)
class LawSource:
    key: str
    regime: str
    title: str
    target: str
    attachment_required: bool = False
    attachment_selector: dict[str, str] | None = None


def bytes_sha256(content: bytes) -> str:
    return sha256(content).hexdigest()


def file_sha256(path: str | Path) -> str:
    h = sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_registry(path: Path = REGISTRY_FILE) -> tuple[LawSource, ...]:
    payload = _load_json(path, [])
    sources: list[LawSource] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        sources.append(
            LawSource(
                key=str(row.get("key", "")).strip(),
                regime=str(row.get("regime", "")).strip(),
                title=str(row.get("title", "")).strip(),
                target=str(row.get("target", "")).strip(),
                attachment_required=bool(row.get("attachment_required", False)),
                attachment_selector=row.get("attachment_selector") if isinstance(row.get("attachment_selector"), dict) else None,
            )
        )
    return tuple(source for source in sources if source.key and source.title and source.target)


def source_rows(sources: Iterable[LawSource] | None = None) -> list[dict[str, object]]:
    selected = tuple(sources) if sources is not None else load_registry()
    return [asdict(source) for source in selected]


def _select_attachments(items: list[dict[str, str]], selector: dict[str, str] | None) -> list[dict[str, str]]:
    if not selector or selector.get("mode") in {None, "", "all"}:
        return items

    wanted_no = str(selector.get("appendix_no", "")).strip()
    title_contains = str(selector.get("title_contains", "")).strip()
    selected: list[dict[str, str]] = []
    for item in items:
        appendix_no = str(item.get("appendix_no", "")).strip()
        appendix_title = str(item.get("appendix_title", "")).strip()
        if wanted_no and appendix_no != wanted_no:
            continue
        # Appendix number is the primary identifier. If the API omits a title,
        # do not reject an otherwise exact appendix-number match.
        if title_contains and appendix_title and title_contains not in appendix_title:
            continue
        selected.append(item)
    return selected


def _safe_filename(value: str, fallback: str) -> str:
    value = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", value).strip("_.")
    return value[:100] or fallback


def _attachment_id(item: dict[str, str], index: int) -> str:
    no = str(item.get("appendix_no", "")).strip()
    branch = str(item.get("appendix_branch", "")).strip()
    title = str(item.get("appendix_title", "")).strip()
    prefix = f"별표{no}" if no else f"첨부{index}"
    if branch and branch != "0":
        prefix += f"-{branch}"
    return f"{prefix} {title}".strip()


def _save_pending_pdf(source_key: str, item_id: str, digest: str, content: bytes) -> str:
    target_dir = PENDING_PDF_DIR / source_key
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(item_id, "appendix")
    target = target_dir / f"{stem}__{digest[:16]}.pdf"
    if not target.exists():
        target.write_bytes(content)
    return str(target.relative_to(PROJECT_ROOT))


def _baseline_sources() -> dict[str, Any]:
    payload = _load_json(APPROVED_FILE, {})
    sources = payload.get("sources", {}) if isinstance(payload, dict) else {}
    return sources if isinstance(sources, dict) else {}


def _snapshot_from_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": row.get("key", ""),
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
        "attachment_hashes": row.get("attachment_hashes", {}),
        "attachment_titles": row.get("attachment_titles", {}),
        "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def _compare_to_baseline(row: dict[str, Any], baseline: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not baseline:
        return "BASELINE_UNAPPROVED", ["프로그램 반영 기준선이 아직 승인되지 않았습니다."]

    changes: list[str] = []
    for field, label in (
        ("serial", "법령/행정규칙 일련번호"),
        ("effective_date", "시행일"),
        ("issue_date", "공포·발령일"),
        ("issue_number", "공포·발령번호"),
    ):
        old = str(baseline.get(field, "")).strip()
        new = str(row.get(field, "")).strip()
        if old != new:
            changes.append(f"{label}: {old or '-'} → {new or '-'}")

    old_hashes = baseline.get("attachment_hashes", {}) or {}
    new_hashes = row.get("attachment_hashes", {}) or {}
    if old_hashes != new_hashes:
        old_keys = set(old_hashes)
        new_keys = set(new_hashes)
        for key in sorted(old_keys | new_keys):
            old = str(old_hashes.get(key, ""))
            new = str(new_hashes.get(key, ""))
            if old != new:
                if not old:
                    changes.append(f"PDF 추가: {key}")
                elif not new:
                    changes.append(f"PDF 삭제/미확인: {key}")
                else:
                    changes.append(f"PDF 내용 변경: {key} ({old[:10]}… → {new[:10]}…)")

    return ("UPDATE_PENDING", changes) if changes else ("CURRENT", [])


def run_law_monitor(timeout: int = 45) -> list[dict[str, Any]]:
    """Check official current versions and PDF hashes against approved local baselines.

    The monitor NEVER auto-approves a changed source. New/changed PDFs are stored
    under data/runtime/law_pending so they can be re-ingested and reviewed first.
    """
    sources = load_registry()
    baselines = _baseline_sources()
    rows: list[dict[str, Any]] = []

    for source in sources:
        row: dict[str, Any] = {
            **asdict(source),
            "api_status": "",
            "monitor_status": "UNVERIFIED",
            "monitor_status_ko": "확인 전",
            "change_reason": [],
            "attachment_count": 0,
            "attachment_hashes": {},
            "attachment_titles": {},
            "pending_pdf_files": [],
            "observation_valid": False,
        }

        found = search_current_source(source.title, source.target, timeout=timeout)
        row.update(found)
        if found.get("api_status") != "FOUND":
            row["monitor_status"] = "UNVERIFIED"
            row["monitor_status_ko"] = "공식 최신본 확인 실패"
            row["change_reason"] = [str(found.get("message", "공식 API 확인 실패"))]
            rows.append(row)
            continue

        try:
            payload = fetch_source_payload(found, source.target, timeout=max(timeout, 60))
        except Exception as exc:
            row["monitor_status"] = "UNVERIFIED"
            row["monitor_status_ko"] = "본문 조회 실패"
            row["change_reason"] = [f"{type(exc).__name__}: {exc}"]
            rows.append(row)
            continue

        attachments = extract_attachments(payload)
        selected = _select_attachments(attachments, source.attachment_selector)
        row["attachment_count"] = len(selected)

        attachment_problem = False
        if source.attachment_required and not selected:
            attachment_problem = True
            row["change_reason"].append("감시가 필요한 별표·서식 PDF를 공식 본문에서 찾지 못했습니다.")

        for index, item in enumerate(selected, 1):
            item_id = _attachment_id(item, index)
            row["attachment_titles"][item_id] = item.get("appendix_title", "")
            pdf_url = str(item.get("pdf_url", "")).strip()
            if not pdf_url:
                attachment_problem = True
                row["change_reason"].append(f"PDF 링크 없음(HWP만 제공 가능): {item_id}")
                continue
            try:
                content = download_binary(pdf_url, timeout=max(timeout, 60))
                digest = bytes_sha256(content)
                row["attachment_hashes"][item_id] = digest
                row["pending_pdf_files"].append(_save_pending_pdf(source.key, item_id, digest, content))
            except Exception as exc:
                attachment_problem = True
                host = urlparse(pdf_url).netloc or "law.go.kr"
                row["change_reason"].append(f"PDF 다운로드 실패({host}, {item_id}): {type(exc).__name__}")

        if attachment_problem:
            row["monitor_status"] = "UNVERIFIED"
            row["monitor_status_ko"] = "별표·서식 확인 필요"
            rows.append(row)
            continue

        row["observation_valid"] = True
        status, changes = _compare_to_baseline(row, baselines.get(source.key))
        row["monitor_status"] = status
        if status == "CURRENT":
            row["monitor_status_ko"] = "최신·반영본 일치"
        elif status == "BASELINE_UNAPPROVED":
            row["monitor_status_ko"] = "최초 기준선 승인 필요"
        else:
            row["monitor_status_ko"] = "변경 감지·재반영 필요"
        row["change_reason"].extend(changes)
        rows.append(row)

    _write_json(
        OBSERVED_FILE,
        {
            "checked_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "credential_status": credential_status(),
            "rows": rows,
        },
    )
    return rows


def approve_latest_observation(keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Mark already-reviewed/re-ingested current observations as the approved baseline.

    This function must only be called AFTER the administrator confirms that the
    current official text/PDF has actually been reflected in the program's legal
    knowledge/rule database. It deliberately refuses invalid observations.
    """
    observed = _load_json(OBSERVED_FILE, {})
    rows = observed.get("rows", []) if isinstance(observed, dict) else []
    if not rows:
        return {"status": "NO_OBSERVATION", "approved": 0, "message": "먼저 최신 법령 확인을 실행하세요."}

    wanted = set(keys) if keys is not None else None
    current_payload = _load_json(APPROVED_FILE, {})
    approved_sources = current_payload.get("sources", {}) if isinstance(current_payload, dict) else {}
    if not isinstance(approved_sources, dict):
        approved_sources = {}

    approved = 0
    skipped: list[str] = []
    for row in rows:
        key = str(row.get("key", ""))
        if wanted is not None and key not in wanted:
            continue
        if not row.get("observation_valid"):
            skipped.append(key)
            continue
        approved_sources[key] = _snapshot_from_row(row)
        approved += 1

    _write_json(
        APPROVED_FILE,
        {
            "approved_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sources": approved_sources,
        },
    )
    return {
        "status": "APPROVED" if approved else "NOTHING_APPROVED",
        "approved": approved,
        "skipped": skipped,
        "message": f"검증·반영 확인된 {approved}개 자료를 최신 기준선으로 저장했습니다.",
    }


def overall_sync_gate(status_rows: list[dict[str, object]] | None = None) -> dict[str, str]:
    if not status_rows:
        return {
            "status": "MONITOR_NOT_RUN",
            "label": "법령 최신성 미확인",
            "decision": "HOLD",
            "message": "법제처 Open API와 첨부 PDF 최신성 확인이 수행되지 않아 법적 확정판정을 보류합니다.",
        }

    bad = [row for row in status_rows if row.get("monitor_status") != "CURRENT"]
    if bad:
        changed = [row for row in bad if row.get("monitor_status") == "UPDATE_PENDING"]
        unapproved = [row for row in bad if row.get("monitor_status") == "BASELINE_UNAPPROVED"]
        if changed:
            label = f"법령/PDF 변경 {len(changed)}건"
        elif unapproved:
            label = f"최초 기준선 승인 필요 {len(unapproved)}건"
        else:
            label = "법령 최신성 확인 필요"
        return {
            "status": "UPDATE_OR_UNVERIFIED",
            "label": label,
            "decision": "HOLD",
            "message": "최신 공식본과 프로그램 반영본의 일치가 확인되지 않은 자료가 있어 관련 판정을 보류합니다.",
        }

    return {
        "status": "CURRENT",
        "label": "법령·PDF 최신",
        "decision": "ALLOW",
        "message": "감시대상 법령과 별표·서식 PDF가 검증된 프로그램 반영본과 일치합니다.",
    }
