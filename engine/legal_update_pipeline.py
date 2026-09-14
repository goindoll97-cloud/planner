from __future__ import annotations

"""One-click refresh of official legal sources and decision data.

Normal users should not have to press one button per appendix. This module
turns the existing conservative building blocks into one explicit admin action:

1. query law.go.kr and download every configured PDF/HWP/HWPX attachment;
2. build and validate every structured decision table from the observed PDFs;
3. only if every automatic parser validation passes, approve the observed legal
   version and version the exact official source files locally;
4. approve all structured decision tables and synchronize their evidence PDFs;
5. write a human-readable Excel snapshot of the approved decision tables;
6. run the same readiness gate used by diagnosis.

The user's single ``최신본 업데이트`` click is the explicit approval action.
Automatic parser validation is never bypassed. If any official attachment or
parser is uncertain, the pipeline stops fail-closed and leaves diagnosis HOLD.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .law_monitor import approve_latest_observation, run_law_monitor
from .legal_archive import EVIDENCE_CONFIG, evidence_for_key, sync_approved_evidence
from .readiness import decision_readiness_gate
from .regulatory_admin import approve_candidate
from .regulatory_tables import PROJECT_ROOT
from .regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_cap_appendix1_candidate,
    build_cap_appendix2_candidate,
    build_cap_appendix4_candidate,
    build_psm_annex13_candidate,
)


ProgressCallback = Callable[[str, str], None]
RUNTIME_DIR = PROJECT_ROOT / "data" / "runtime"
LAST_UPDATE_FILE = RUNTIME_DIR / "legal_update_last.json"
CURRENT_EXPORT_DIR = PROJECT_ROOT / "data" / "legal_archive" / "current"
CURRENT_EXCEL_FILE = CURRENT_EXPORT_DIR / "판정용_규정DB_최신본.xlsx"


REGULATORY_BUILDERS = (
    ("PSM_ANNEX13", "공정안전보고서 별표 13", "공정안전_별표13", build_psm_annex13_candidate),
    ("CAP_QTY_APP1", "화학사고예방관리계획서 별표 1", "화학사고_별표1", build_cap_appendix1_candidate),
    ("CAP_QTY_APP2", "화학사고예방관리계획서 별표 2", "화학사고_별표2", build_cap_appendix2_candidate),
    ("CAP_QTY_APP3", "화학사고예방관리계획서 별표 3", "화학사고_별표3", build_cap_accident_quantity_candidate),
    ("CAP_QTY_APP4", "화학사고예방관리계획서 별표 4", "화학사고_별표4", build_cap_appendix4_candidate),
)


def _emit(callback: ProgressCallback | None, stage: str, message: str) -> None:
    if callback is not None:
        callback(stage, message)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _write_report(payload: dict[str, Any]) -> dict[str, Any]:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["finished_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    LAST_UPDATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def latest_update_report() -> dict[str, Any]:
    return _read_json(LAST_UPDATE_FILE)


def _candidate_summary(result: Any) -> dict[str, Any]:
    return {
        "key": str(getattr(result, "key", "")),
        "status": str(getattr(result, "status", "")),
        "row_count": int(getattr(result, "row_count", 0) or 0),
        "source_file": str(getattr(result, "source_file", "")),
        "candidate_file": str(getattr(result, "candidate_file", "")),
        "messages": list(getattr(result, "messages", []) or []),
        "checks": dict(getattr(result, "checks", {}) or {}),
    }


def _law_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        files = row.get("attachment_files") or []
        formats = sorted(
            {
                str(item.get("format") or "")
                for item in files
                if isinstance(item, dict) and item.get("format")
            }
        )
        out.append(
            {
                "key": str(row.get("key") or ""),
                "title": str(row.get("title") or ""),
                "effective_date": str(row.get("effective_date") or ""),
                "issue_number": str(row.get("issue_number") or ""),
                "monitor_status": str(row.get("monitor_status") or ""),
                "monitor_status_ko": str(row.get("monitor_status_ko") or ""),
                "observation_valid": bool(row.get("observation_valid")),
                "attachment_file_count": int(row.get("attachment_file_count", 0) or 0),
                "formats": formats,
                "change_reason": list(row.get("change_reason") or []),
            }
        )
    return out


def _build_current_excel_snapshot() -> dict[str, Any]:
    """Create one current Excel workbook from the five approved decision tables."""
    CURRENT_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    meta_rows: list[dict[str, Any]] = []

    try:
        with pd.ExcelWriter(CURRENT_EXCEL_FILE, engine="openpyxl") as writer:
            for key, label, sheet_name, _builder in REGULATORY_BUILDERS:
                config = EVIDENCE_CONFIG.get(key) or {}
                approved_raw = config.get("approved")
                approved_path = Path(approved_raw) if approved_raw else None
                if approved_path is None or not approved_path.exists():
                    raise FileNotFoundError(f"{label}: 승인 규정 DB 파일이 없습니다.")

                frame = pd.read_csv(approved_path, dtype=str, keep_default_na=False)
                frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)

                audit_path = Path(config.get("audit")) if config.get("audit") else None
                audit = _read_json(audit_path) if audit_path else {}
                evidence = evidence_for_key(key) or {}
                meta_rows.append(
                    {
                        "규정DB": label,
                        "key": key,
                        "행수": len(frame),
                        "승인파일": str(approved_path.relative_to(PROJECT_ROOT)),
                        "승인시각_UTC": audit.get("approved_at_utc", ""),
                        "시행일": evidence.get("effective_date", ""),
                        "근거PDF_SHA256": evidence.get("sha256", "") or audit.get("source_pdf_sha256", ""),
                        "근거PDF": evidence.get("archived_file", ""),
                    }
                )

            pd.DataFrame(meta_rows).to_excel(writer, sheet_name="업데이트정보", index=False)

        return {
            "status": "WRITTEN",
            "file": str(CURRENT_EXCEL_FILE.relative_to(PROJECT_ROOT)),
            "table_count": len(meta_rows),
        }
    except PermissionError as exc:
        return {
            "status": "FILE_LOCKED",
            "file": str(CURRENT_EXCEL_FILE.relative_to(PROJECT_ROOT)),
            "message": "최신 규정 DB Excel 파일이 열려 있어 덮어쓰지 못했습니다. Excel 파일을 닫고 다시 업데이트하세요.",
            "error": f"{type(exc).__name__}: {exc}",
        }
    except Exception as exc:
        return {
            "status": "ERROR",
            "file": str(CURRENT_EXCEL_FILE.relative_to(PROJECT_ROOT)),
            "message": f"최신 규정 DB Excel 파일 작성에 실패했습니다: {type(exc).__name__}: {exc}",
        }


def _all_sources_current(rows: list[dict[str, Any]]) -> bool:
    return bool(rows) and all(
        bool(row.get("observation_valid")) and str(row.get("monitor_status") or "") == "CURRENT"
        for row in rows
    )


def refresh_all_legal_assets(progress: ProgressCallback | None = None) -> dict[str, Any]:
    """Refresh every legal asset behind one explicit administrator click.

    Legal baseline approval is delayed until all five decision-table parsers have
    passed their automatic structural/anchor checks. This prevents a changed PDF
    layout from being promoted just because the network download succeeded.
    """
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    base: dict[str, Any] = {
        "schema_version": 1,
        "started_at_utc": started,
        "status": "RUNNING",
        "law_rows": [],
        "candidate_results": [],
        "law_approval": {},
        "db_approvals": [],
        "evidence_results": [],
        "excel_snapshot": {},
        "readiness": {},
        "blockers": [],
    }

    try:
        _emit(progress, "law", "법제처에서 최신 법령과 PDF·HWP/HWPX 원본을 확인하고 있습니다.")
        rows = run_law_monitor()
        base["law_rows"] = _law_summary(rows)

        invalid = [row for row in rows if not bool(row.get("observation_valid"))]
        if invalid:
            blockers = [
                f"{row.get('title', row.get('key', '법령'))}: "
                + " / ".join(str(v) for v in (row.get("change_reason") or []) if str(v).strip())
                for row in invalid
            ]
            base.update(
                status="HOLD",
                blockers=blockers or ["공식 법령 또는 첨부원본을 완전히 확인하지 못했습니다."],
            )
            return _write_report(base)

        pre_gate = decision_readiness_gate(rows)
        base["readiness_before"] = pre_gate
        if _all_sources_current(rows) and pre_gate.get("decision") == "ALLOW":
            _emit(progress, "excel", "현재 승인 규정 DB를 최신 Excel 묶음으로 정리하고 있습니다.")
            excel = _build_current_excel_snapshot()
            base["excel_snapshot"] = excel
            base["readiness"] = pre_gate
            base["status"] = "CURRENT"
            if excel.get("status") not in {"WRITTEN"}:
                base["warnings"] = [str(excel.get("message") or "Excel 최신본 작성 상태를 확인하세요.")]
            return _write_report(base)

        # Phase 1: build/validate every decision table BEFORE promoting the new
        # legal baseline. A parser failure means the old approved baseline stays
        # untouched and diagnosis remains HOLD.
        candidate_summaries: list[dict[str, Any]] = []
        candidate_failures: list[str] = []
        for key, label, _sheet, builder in REGULATORY_BUILDERS:
            _emit(progress, "parse", f"{label}을 최신 공식 PDF에서 자동검증하고 있습니다.")
            try:
                result = builder()
                summary = _candidate_summary(result)
            except Exception as exc:
                summary = {
                    "key": key,
                    "status": "ERROR",
                    "row_count": 0,
                    "source_file": "",
                    "candidate_file": "",
                    "messages": [f"{type(exc).__name__}: {exc}"],
                    "checks": {},
                }
            candidate_summaries.append(summary)
            if summary.get("status") != "REVIEW_REQUIRED":
                details = " / ".join(str(v) for v in summary.get("messages", []) if str(v).strip())
                candidate_failures.append(
                    f"{label}: 자동검증 상태 {summary.get('status') or '미확인'}"
                    + (f" · {details}" if details else "")
                )

        base["candidate_results"] = candidate_summaries
        if candidate_failures:
            base.update(status="HOLD", blockers=candidate_failures)
            return _write_report(base)

        # Phase 2: the user already clicked '최신본 업데이트'. With every
        # source valid and every parser validation passed, that click is the
        # explicit approval to promote all non-current observed law sources.
        approvable_statuses = {"BASELINE_UNAPPROVED", "BASELINE_MIGRATION_REQUIRED", "UPDATE_PENDING"}
        law_keys = [
            str(row.get("key") or "")
            for row in rows
            if str(row.get("monitor_status") or "") in approvable_statuses
            and bool(row.get("observation_valid"))
            and str(row.get("key") or "")
        ]
        if law_keys:
            _emit(progress, "approve_law", "검증된 최신 법령과 PDF·HWP/HWPX 원본을 새 승인본으로 버전 보관하고 있습니다.")
            law_approval = approve_latest_observation(law_keys)
            base["law_approval"] = law_approval
            if law_approval.get("status") != "APPROVED" or int(law_approval.get("approved", 0) or 0) != len(law_keys):
                base.update(
                    status="HOLD",
                    blockers=[str(law_approval.get("message") or "최신 법령 기준선 승인에 실패했습니다.")],
                )
                return _write_report(base)
        else:
            base["law_approval"] = {"status": "NOT_NEEDED", "approved": 0, "message": "법령 기준선 변경 없음"}

        # Phase 3: approve all five structured decision tables. The individual
        # approve functions also keep their own audit files; a partial failure is
        # safe because final readiness remains HOLD until every source hash joins.
        approvals: list[dict[str, Any]] = []
        approval_failures: list[str] = []
        for key, label, _sheet, _builder in REGULATORY_BUILDERS:
            _emit(progress, "approve_db", f"{label} 판정 DB를 최신 검증본으로 갱신하고 있습니다.")
            approval = approve_candidate(key)
            row = {"key": key, "label": label, **dict(approval)}
            approvals.append(row)
            if approval.get("status") != "APPROVED":
                approval_failures.append(f"{label}: {approval.get('message', approval.get('status', '승인 실패'))}")
        base["db_approvals"] = approvals
        if approval_failures:
            base.update(status="HOLD", blockers=approval_failures)
            return _write_report(base)

        # Phase 4: evidence archive ties each approved structured table back to
        # the exact current official PDF hash.
        _emit(progress, "evidence", "승인 규정 DB와 공식 PDF SHA-256 근거를 연결하고 있습니다.")
        evidence_results = sync_approved_evidence([item[0] for item in REGULATORY_BUILDERS])
        base["evidence_results"] = evidence_results
        evidence_failures = [
            str(row.get("message") or row.get("status") or "근거 PDF 연결 실패")
            for row in evidence_results
            if row.get("status") != "ARCHIVED"
        ]
        if evidence_failures:
            base.update(status="HOLD", blockers=evidence_failures)
            return _write_report(base)

        _emit(progress, "excel", "승인 규정 DB 전체를 최신 Excel 파일로 묶고 있습니다.")
        excel = _build_current_excel_snapshot()
        base["excel_snapshot"] = excel

        _emit(progress, "ready", "판정진단 준비상태를 최종 확인하고 있습니다.")
        gate = decision_readiness_gate(rows)
        base["readiness"] = gate
        if gate.get("decision") != "ALLOW":
            base.update(
                status="HOLD",
                blockers=list(gate.get("blockers") or [gate.get("message") or "최종 판정 준비상태를 확인하세요."]),
            )
            return _write_report(base)

        base["status"] = "UPDATED"
        if excel.get("status") != "WRITTEN":
            base["warnings"] = [str(excel.get("message") or "Excel 최신본 작성 상태를 확인하세요.")]
        return _write_report(base)

    except Exception as exc:
        base.update(
            status="ERROR",
            blockers=[f"{type(exc).__name__}: {exc}"],
        )
        return _write_report(base)
