from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.law_attachment_archive import (
    approved_source_archive_rows,
    approved_source_files,
    approved_source_is_current,
)
from engine.law_monitor import OBSERVED_FILE
from engine.legal_archive import evidence_rows, open_archive_folder
from engine import law_old_new
from engine.legal_update_pipeline import latest_update_report, refresh_all_legal_assets, requires_rule_mapping_review
from engine.readiness import decision_readiness_gate
from engine.regulatory_admin import approved_db_status
from engine.rule_mapping_review import record_reviews
from engine.stage2.legal_refresh import load_impact_map


UPDATE_REPORT_KEY = "regdb_one_click_update_report"

st.set_page_config(page_title="법령·규정 DB 관리", page_icon="🗂️", layout="wide")


def _read_json(path) -> dict[str, object]:
    try:
        if not path.exists():
            return {}
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _observed_rows() -> list[dict[str, object]]:
    payload = _read_json(OBSERVED_FILE)
    rows = payload.get("rows") or []
    return [dict(row) for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _display_cell(value: object) -> object:
    if isinstance(value, (dict, list, tuple, set)):
        serializable = list(value) if isinstance(value, set) else value
        return json.dumps(serializable, ensure_ascii=False)
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value)


def _table(df: pd.DataFrame, max_rows: int = 40) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    shown = df.head(max_rows).copy()
    for column in shown.columns:
        if shown[column].dtype == object:
            shown[column] = shown[column].map(_display_cell)
    st.dataframe(shown, width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _human(text: object) -> str:
    return str(text or "").replace("화사계", "화학사고예방관리계획서")


def _row_is_current(row: dict[str, object]) -> bool:
    if str(row.get("monitor_status") or "") == "CURRENT":
        return True
    key = str(row.get("key") or "")
    return bool(key and row.get("observation_valid") and approved_source_is_current(key))


def _law_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    out: list[dict[str, object]] = []
    for row in rows:
        files = row.get("attachment_files") or []
        formats = sorted(
            {
                str(item.get("format") or "")
                for item in files
                if isinstance(item, dict) and item.get("format")
            }
        )
        key = str(row.get("key") or "")
        local_paths = [
            str(path.relative_to(Path(__file__).resolve().parents[1]))
            for path in approved_source_files(key)
        ]
        if not local_paths:
            for item in files:
                if not isinstance(item, dict):
                    continue
                pending = str(item.get("pending_file") or "").strip()
                candidate = Path(__file__).resolve().parents[1] / pending if pending else None
                if candidate is not None and candidate.is_file():
                    local_paths.append(pending)
        current = _row_is_current(row)
        out.append(
            {
                "법령·규정": row.get("title", ""),
                "법령 종류": "법령" if row.get("target") == "law" else "행정규칙",
                "파일 형식": ", ".join(formats) or "-",
                "시행일": row.get("effective_date", ""),
                "상태": "최신" if current else row.get("monitor_status_ko", row.get("monitor_status", "확인 필요")),
                "로컬 파일 경로": "\n".join(dict.fromkeys(local_paths)) or "-",
            }
        )
    return pd.DataFrame(out)


def _render_law_group(rows: list[dict[str, object]], regime: str) -> None:
    subset = [row for row in rows if _human(row.get("regime")) == regime]
    st.markdown(f"#### {regime}")
    if subset:
        _table(_law_frame(subset), 40)
    else:
        st.caption("표시할 법령·규정이 없습니다.")


def _show_last_result(report: dict[str, object]) -> None:
    if not report:
        return
    status = str(report.get("status") or "")
    finished = str(report.get("finished_at_utc") or "")
    if status in {"UPDATED", "CURRENT"}:
        if status == "UPDATED":
            st.success("최신본 업데이트가 완료되었습니다. PDF·HWP/HWPX 원본과 판정용 규정 DB가 같은 최신 법령 버전에 맞춰졌습니다.")
        else:
            st.success("이미 최신 상태입니다. 별도 갱신이 필요하지 않았습니다.")
        if finished:
            st.caption(f"마지막 확인: {finished}")
    elif status in {"HOLD", "ERROR"}:
        st.error("최신본 자동 업데이트를 완료하지 못했습니다. 실패한 부분은 기존 승인본으로 임의 대체하지 않았습니다.")
        for blocker in report.get("blockers") or []:
            st.write(f"• {_human(blocker)}")
        if not (report.get("law_approval") or {}).get("approved"):
            st.caption("업데이트는 한 자료라도 확인에 실패하면 전체를 그 자리에서 멈춥니다. 그래서 위 문제와 관계없는 법령·별표도 "
                       "이번에는 새 승인본으로 반영되지 않았고, 아래 판정 보류 사유에 함께 표시될 수 있습니다. "
                       "위 문제를 해결한 뒤 다시 실행하면 함께 반영됩니다.")
    for warning in report.get("warnings") or []:
        st.warning(str(warning))

    excel = report.get("excel_snapshot") or {}
    if isinstance(excel, dict) and excel.get("status") == "WRITTEN":
        st.caption(f"판정용 규정 DB Excel 최신본: {excel.get('file', '')}")


def _render_rule_mapping_review(rows: list[dict[str, object]]) -> None:
    """실제 개정된 법령에 대해, 담당자가 규칙과 새 조문을 대조했다는 확인을 남긴다."""
    pending = [row for row in rows if requires_rule_mapping_review(row)]
    if not pending:
        return
    try:
        impact = load_impact_map()
    except Exception:
        impact = {}
    st.subheader("규칙 매핑 검토가 필요한 개정")
    st.warning(
        "아래 법령은 실제로 개정되었습니다. 프로그램의 판정·작성 규칙이 새 조문과 맞는지는 프로그램이 스스로 확인할 수 없어 "
        "자동 승인하지 않았습니다. 개정 전후 조문을 확인하고 영향 범위를 대조한 뒤, 아래에 확인을 기록하고 "
        "‘최신본 업데이트’를 다시 실행하세요. 확인은 이 판에만 적용되며 다음 개정은 다시 검토해야 합니다."
    )
    for row in pending:
        key = str(row.get("key") or "")
        with st.expander(f"{_human(row.get('title') or key)} — 시행 {row.get('effective_date') or '-'}", expanded=True):
            for reason in row.get("change_reason") or []:
                st.write(f"• {_human(reason)}")
            info = impact.get(key) or {}
            if info:
                st.caption(f"프로그램에서 영향받는 범위: {info.get('scope', '')} → {info.get('action', '')}")
            state_key = f"rule_review_oldnew_{key}_{row.get('serial')}"
            if st.button("법제처에서 신구조문 불러오기", key=f"{state_key}_btn"):
                st.session_state[state_key] = law_old_new.fetch_old_new(key, row)
            result = st.session_state.get(state_key)
            if result is not None:
                if result.get("status") != "OK":
                    st.info(result.get("message") or "조문 비교를 불러오지 못했습니다. 법제처 사이트에서 직접 확인하세요.")
                else:
                    changed = [r for r in result.get("rows", []) if r.get("변경") != "같음"]
                    if changed:
                        st.dataframe(pd.DataFrame(changed, columns=["조문", "변경", "개정 전", "개정 후"]),
                                     hide_index=True, width="stretch")
                    else:
                        st.write("바뀐 조문이 없습니다(별표·별지만 바뀐 개정일 수 있습니다).")
    with st.form("rule_mapping_review_form"):
        confirmed = st.checkbox("위 법령의 개정 전후 조문을 확인했고, 프로그램 판정·작성 규칙이 새 조문과 어긋나지 않음을 확인했습니다.")
        reviewer = st.text_input("확인자 이름")
        memo = st.text_area("확인 메모(선택) — 무엇을 어떻게 확인했는지", height=80)
        submitted = st.form_submit_button("검토 확인 기록")
    if submitted:
        if not confirmed:
            st.error("확인 항목에 체크해야 기록할 수 있습니다.")
        else:
            result = record_reviews(pending, reviewer=reviewer, memo=memo)
            if result.get("status") == "RECORDED":
                st.success(f"{result['message']} 이제 ‘최신본 업데이트’를 다시 실행하세요.")
            else:
                st.error(result.get("message", "기록하지 못했습니다."))


st.title("법령·규정 DB 관리")
st.caption(
    "평소에는 별표별로 관리할 필요가 없습니다. 법령 개정 또는 최신본 미반영이 감지되면 "
    "아래 ‘최신본 업데이트’ 한 번으로 법제처 원본(PDF·HWP/HWPX), 판정용 규정 DB, 근거 PDF, Excel 최신본을 함께 갱신합니다."
)

rows = _observed_rows()
gate = decision_readiness_gate(rows) if rows else {
    "decision": "HOLD",
    "message": "아직 법령 최신성 확인기록이 없습니다.",
    "blockers": [],
}

law_needs_update = bool(rows) and any(not _row_is_current(row) for row in rows)
if law_needs_update:
    st.error("법령 개정 또는 공식 첨부원본 변경이 감지되었습니다. ‘최신본 업데이트’를 실행해 주세요.")
elif rows and gate.get("decision") == "ALLOW":
    st.success("현재 법령·첨부원본과 판정용 규정 DB가 최신 상태입니다.")
elif rows:
    st.warning("법령 원본은 확인되었지만 판정용 규정 DB 또는 근거 연결을 최신화해야 합니다. ‘최신본 업데이트’를 실행해 주세요.")
else:
    st.info("처음 사용하는 경우 ‘최신본 업데이트’를 한 번 실행하면 법령 원본과 판정용 규정 DB를 함께 준비합니다.")

button_label = "최신본 업데이트" if gate.get("decision") != "ALLOW" else "최신본 다시 확인·업데이트"
if st.button(button_label, type="primary", width="stretch"):
    with st.status("최신 법령자료를 한 번에 갱신하고 있습니다...", expanded=True) as box:
        line = st.empty()

        def _progress(_stage: str, message: str) -> None:
            line.write(message)

        result = refresh_all_legal_assets(progress=_progress)
        st.session_state[UPDATE_REPORT_KEY] = result
        st.cache_data.clear()
        if result.get("status") in {"UPDATED", "CURRENT"} and (result.get("readiness") or {}).get("decision") == "ALLOW":
            box.update(label="최신본 업데이트 완료", state="complete", expanded=False)
        elif result.get("status") == "CURRENT":
            box.update(label="최신 상태 확인 완료", state="complete", expanded=False)
        else:
            box.update(label="최신본 업데이트 중 확인이 필요한 항목이 있습니다", state="error", expanded=True)
    st.rerun()

report = st.session_state.get(UPDATE_REPORT_KEY) or latest_update_report()
if isinstance(report, dict):
    _show_last_result(report)

# Re-read after a possible update report so readiness shown below always reflects
# the latest on-disk observation/approval state rather than stale session data.
rows = _observed_rows()
_render_rule_mapping_review(rows)
gate = decision_readiness_gate(rows) if rows else gate
if gate.get("decision") == "ALLOW":
    st.page_link("ui/judgement_page.py", label="사업장 판정하기로 이동", icon="✅")
else:
    with st.expander("업데이트가 완료되지 않은 이유 보기", expanded=False):
        st.write(str(gate.get("message") or "법령 또는 규정 DB 준비상태를 확인하세요."))
        for blocker in gate.get("blockers") or []:
            st.write(f"• {_human(blocker)}")

st.divider()
with st.expander("고급 관리·감사정보", expanded=False):
    st.caption(
        "일반 사용자는 이 영역을 조작할 필요가 없습니다. 자동 업데이트 실패 원인을 확인하거나 "
        "법령 원본·판정 DB의 SHA-256 감사근거를 확인할 때만 사용합니다."
    )

    st.markdown("### 법령·첨부원본 상태")
    _render_law_group(rows, "화학사고예방관리계획서")
    _render_law_group(rows, "공정안전보고서")

    st.markdown("### 판정용 규정 DB 상태")
    status_df = approved_db_status().copy()
    if not status_df.empty:
        status_df["상태"] = status_df["approved"].map({True: "승인됨", False: "미승인"})
        cols = [c for c in ["key", "상태", "rows", "file", "approved_at_utc"] if c in status_df.columns]
        _table(status_df[cols].rename(columns={"rows": "행수", "file": "파일", "approved_at_utc": "승인시각(UTC)"}), 20)

    st.markdown("### 판정 DB 근거 PDF")
    _table(pd.DataFrame(evidence_rows()), 20)

    st.markdown("### 법제처 PDF·HWP/HWPX 원본 버전보관")
    _table(pd.DataFrame(approved_source_archive_rows()), 30)

    if st.button("법령 근거자료 폴더 열기", key="open_legal_archive_advanced", width="stretch"):
        opened = open_archive_folder()
        if opened.get("status") == "OPENED":
            st.toast(str(opened.get("message", "폴더를 열었습니다.")))
        else:
            st.warning(str(opened.get("message", "폴더를 열지 못했습니다.")))

    if isinstance(report, dict) and report:
        st.markdown("### 마지막 자동 업데이트 상세")
        candidate_rows = report.get("candidate_results") or []
        if candidate_rows:
            _table(
                pd.DataFrame(
                    [
                        {
                            "규정DB": _human(item.get("key", "")),
                            "자동검증": item.get("status", ""),
                            "행수": item.get("row_count", 0),
                            "원본PDF": item.get("source_file", ""),
                        }
                        for item in candidate_rows
                        if isinstance(item, dict)
                    ]
                ),
                20,
            )

st.caption(
    "최신본 업데이트는 인터넷 연결과 법제처 응답속도, 첨부파일 크기에 따라 시간이 걸릴 수 있습니다. "
    "자동검증을 통과하지 못한 법령·별표는 새 승인본으로 강제 적용하지 않고 판정을 보류합니다."
)
