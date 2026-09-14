from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from engine.law_monitor import approve_latest_observation, run_law_monitor
from engine.legal_archive import (
    EVIDENCE_CONFIG,
    evidence_rows,
    open_archive_folder,
    sync_approved_evidence,
)
from engine.readiness import decision_readiness_gate
from engine.regulatory_admin import approve_candidate, approved_db_status, candidate_preview
from engine.regulatory_tables_safe import (
    build_cap_accident_quantity_candidate,
    build_cap_appendix1_candidate,
    build_cap_appendix2_candidate,
    build_cap_appendix4_candidate,
    build_psm_annex13_candidate,
)


LAW_ROWS_KEY = "regdb_law_rows"
LAW_NOTICE_KEY = "regdb_law_notice"

st.set_page_config(page_title="법령·규정 DB 관리", page_icon="🗂️", layout="wide")


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


def _arrow_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    safe = df.copy()
    for column in safe.columns:
        if safe[column].dtype == object:
            safe[column] = safe[column].map(_display_cell)
    return safe


def _table(df: pd.DataFrame, max_rows: int = 40) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    shown = _arrow_safe_frame(df.head(max_rows))
    st.dataframe(shown, width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _checks_frame(checks: dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"검사항목": str(key), "값": _display_cell(value)} for key, value in checks.items()],
        columns=["검사항목", "값"],
    )


def _human(text: object) -> str:
    return str(text or "").replace("화사계", "화학사고예방관리계획서")


def _law_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    result: list[dict[str, object]] = []
    for row in rows:
        files = row.get("attachment_files") or []
        formats = sorted(
            {
                str(item.get("format") or "")
                for item in files
                if isinstance(item, dict) and item.get("format")
            }
        )
        reasons = row.get("change_reason") or []
        result.append(
            {
                "구분": _human(row.get("regime")),
                "법령·규정": row.get("title", ""),
                "시행일": row.get("effective_date", ""),
                "발령번호": row.get("issue_number", ""),
                "확인상태": row.get("monitor_status_ko", row.get("monitor_status", "")),
                "첨부원본": int(row.get("attachment_file_count", 0) or 0),
                "보관형식": ", ".join(formats) or "-",
                "확인사항": " / ".join(str(v) for v in reasons if str(v).strip()),
            }
        )
    return pd.DataFrame(result)


def _law_option_label(row: dict[str, object]) -> str:
    return (
        f"{_human(row.get('regime'))} · {row.get('title', '')} · "
        f"{row.get('monitor_status_ko', row.get('monitor_status', ''))}"
    )


def _show_persistent_notice() -> None:
    notice = st.session_state.get("regdb_notice")
    if not notice:
        return
    status = str(notice.get("status", ""))
    message = str(notice.get("message", ""))
    if status == "APPROVED":
        st.success(message)
        if notice.get("warning"):
            st.warning(str(notice["warning"]))
        if notice.get("next"):
            st.info(f"다음 단계: {notice['next']}")
    else:
        st.error(message)


def _show_archive_notice() -> None:
    results = st.session_state.get("archive_sync_results")
    if not results:
        return
    archived = [r for r in results if r.get("status") == "ARCHIVED"]
    failed = [r for r in results if r.get("status") not in {"ARCHIVED", "NOT_APPROVED"}]
    if archived:
        st.success(f"판정 DB 근거 PDF {len(archived)}건을 로컬 보관소에서 확인했습니다.")
    for row in failed:
        st.warning(str(row.get("message", "근거자료 보관 상태를 확인하세요.")))


st.title("법령·규정 DB 관리")
st.caption(
    "① 법제처 최신 법령·첨부원본(PDF·HWP/HWPX) 확인 → "
    "② 변경 또는 최초 기준선 검토·승인 → "
    "③ 판정용 규정표 추출·검토·승인 → "
    "④ 근거자료 보관 확인 순서로 진행합니다."
)
_show_persistent_notice()

# ---------------------------------------------------------------------------
# 1. Official current law + attachments
# ---------------------------------------------------------------------------
st.markdown("## 1. 법령·첨부원본 최신성")
st.caption(
    "예전의 '최신 PDF 조회'를 대체하는 단계입니다. 법제처 Open API에서 법령의 시행일·발령번호를 확인하고, "
    "별표·별지의 PDF뿐 아니라 HWP/HWPX 원본도 함께 내려받아 SHA-256으로 비교합니다. "
    "조회만으로는 기준선이 승인되지 않습니다. 변경 또는 최초 등록이 있으면 아래에서 사람이 확인한 뒤 승인해야 합니다."
)

if st.button("법제처 최신 법령·첨부원본 확인", type="primary", width="stretch"):
    with st.status("법제처 최신 법령과 별표·별지 원본을 확인하고 있습니다...", expanded=True) as box:
        try:
            rows = run_law_monitor()
            st.session_state[LAW_ROWS_KEY] = rows
            st.session_state[LAW_NOTICE_KEY] = {
                "status": "CHECKED",
                "message": f"감시대상 {len(rows)}개 법령·규정의 최신성과 첨부원본을 확인했습니다.",
            }
            # diagnosis_entry caches law rows for one hour. Any explicit admin
            # refresh must invalidate that old HOLD/CURRENT result immediately.
            st.cache_data.clear()
            box.update(label="최신 법령·첨부원본 확인 완료", state="complete", expanded=False)
        except Exception as exc:
            st.session_state[LAW_NOTICE_KEY] = {
                "status": "ERROR",
                "message": f"최신 법령 확인에 실패했습니다: {type(exc).__name__}: {exc}",
            }
            box.update(label="최신 법령 확인 실패", state="error", expanded=True)
    st.rerun()

law_notice = st.session_state.get(LAW_NOTICE_KEY)
if law_notice:
    if law_notice.get("status") == "ERROR":
        st.error(str(law_notice.get("message", "")))
    else:
        st.success(str(law_notice.get("message", "")))

law_rows = list(st.session_state.get(LAW_ROWS_KEY) or [])
if not law_rows:
    st.info("먼저 ‘법제처 최신 법령·첨부원본 확인’을 실행하세요. 이 단계가 완료되어야 판정진단의 최신성 상태를 설명할 수 있습니다.")
else:
    current_n = sum(1 for row in law_rows if row.get("monitor_status") == "CURRENT")
    migration_n = sum(1 for row in law_rows if row.get("monitor_status") == "BASELINE_MIGRATION_REQUIRED")
    update_n = sum(1 for row in law_rows if row.get("monitor_status") == "UPDATE_PENDING")
    unapproved_n = sum(1 for row in law_rows if row.get("monitor_status") == "BASELINE_UNAPPROVED")
    unverified_n = len(law_rows) - current_n - migration_n - update_n - unapproved_n

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("최신·반영본 일치", current_n)
    c2.metric("최초/감시체계 재승인", migration_n + unapproved_n)
    c3.metric("실제 변경 감지", update_n)
    c4.metric("확인 실패", unverified_n)
    _table(_law_frame(law_rows), 30)

    approvable = [
        row
        for row in law_rows
        if bool(row.get("observation_valid"))
        and row.get("monitor_status") in {"BASELINE_UNAPPROVED", "BASELINE_MIGRATION_REQUIRED", "UPDATE_PENDING"}
    ]
    if approvable:
        st.markdown("### 최신본 기준선 검토·승인")
        st.caption(
            "`최초 기준선 승인 필요` 또는 `첨부원본 감시 기준선 재등록 필요`는 현재 공식본을 새 감시체계에 등록하는 과정입니다. "
            "`변경 감지·재반영 필요`는 실제 법령/첨부원본 변경일 수 있으므로 판정용 규정 DB 영향까지 확인한 뒤 승인하세요."
        )
        label_to_key = {_law_option_label(row): str(row.get("key", "")) for row in approvable}
        default_labels = [
            label
            for label, key in label_to_key.items()
            if next(
                (
                    row.get("monitor_status")
                    for row in approvable
                    if str(row.get("key", "")) == key
                ),
                "",
            )
            in {"BASELINE_UNAPPROVED", "BASELINE_MIGRATION_REQUIRED"}
        ]
        selected_labels = st.multiselect(
            "기준선으로 승인할 법령·규정",
            options=list(label_to_key),
            default=default_labels,
        )
        reviewed = st.checkbox(
            "위 항목의 시행일·발령번호와 PDF·HWP/HWPX 첨부원본 및 변경사항을 확인했습니다. 실제 개정 항목은 판정용 규정 DB 영향도 함께 검토합니다.",
            key="regdb_confirm_law_baseline",
        )
        if st.button(
            "선택한 최신본을 감시 기준선으로 승인",
            disabled=not (selected_labels and reviewed),
            width="stretch",
        ):
            keys = [label_to_key[label] for label in selected_labels]
            result = approve_latest_observation(keys)
            if result.get("status") == "APPROVED":
                st.session_state[LAW_NOTICE_KEY] = {"status": "APPROVED", "message": result.get("message", "승인했습니다.")}
                # Refresh immediately so the table and diagnosis page no longer
                # show the pre-approval HOLD result.
                st.cache_data.clear()
                st.session_state[LAW_ROWS_KEY] = run_law_monitor()
            else:
                st.session_state[LAW_NOTICE_KEY] = {"status": "ERROR", "message": result.get("message", "승인하지 못했습니다.")}
            st.rerun()

# ---------------------------------------------------------------------------
# 2. Decision DB extracted from official PDF appendices
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 2. 판정용 규정 DB")
st.caption(
    "법령·첨부원본 최신성 확인과 별개로, 실제 자동판정에는 검토·승인된 구조화 규정 DB가 필요합니다. "
    "이 표들은 법제처 공식 첨부원본 중 PDF를 파싱하여 만들며, HWP/HWPX는 원본서식 보존·결과물 작성에 사용합니다."
)

status_df = approved_db_status().copy()
if not status_df.empty:
    status_df["상태"] = status_df["approved"].map({True: "승인됨", False: "미승인"})
    cols = [c for c in ["key", "상태", "rows", "file", "approved_at_utc"] if c in status_df.columns]
    _table(status_df[cols].rename(columns={"rows": "행수", "file": "파일", "approved_at_utc": "승인시각(UTC)"}), 20)

st.markdown("### 최신 공식 PDF에서 판정표 추출")
st.caption(
    "아래 버튼은 '법령 최신성 조회' 버튼이 아니라 판정 엔진용 구조화 표를 만드는 기능입니다. "
    "법령 또는 첨부원본이 바뀌었다면 관련 표를 다시 추출하고 품질검사 후 승인해야 합니다."
)
c1, c2, c3, c4, c5 = st.columns(5)

if c1.button("공정안전보고서 별표 13 추출", width="stretch"):
    with st.status("공정안전보고서 별표 13 추출 중...", expanded=True) as box:
        result = build_psm_annex13_candidate()
        st.session_state["regdb_psm"] = result
        box.update(label="공정안전보고서 별표 13 추출 완료", state="complete", expanded=False)
    st.rerun()

if c2.button("화학사고예방관리계획서 별표 1 추출", width="stretch"):
    with st.status("화학사고예방관리계획서 별표 1 유해·위험성 그룹표 추출 중...", expanded=True) as box:
        result = build_cap_appendix1_candidate()
        st.session_state["regdb_cap1"] = result
        box.update(label="화학사고예방관리계획서 별표 1 추출 완료", state="complete", expanded=False)
    st.rerun()

if c3.button("화학사고예방관리계획서 별표 2 추출", width="stretch"):
    with st.status("화학사고예방관리계획서 별표 2 물질별 규정수량 추출 중...", expanded=True) as box:
        result = build_cap_appendix2_candidate()
        st.session_state["regdb_cap2"] = result
        box.update(label="화학사고예방관리계획서 별표 2 추출 완료", state="complete", expanded=False)
    st.rerun()

if c4.button("화학사고예방관리계획서 별표 3 추출", width="stretch"):
    with st.status("화학사고예방관리계획서 별표 3 사고대비물질 추출 중...", expanded=True) as box:
        result = build_cap_accident_quantity_candidate()
        st.session_state["regdb_cap3"] = result
        box.update(label="화학사고예방관리계획서 별표 3 추출 완료", state="complete", expanded=False)
    st.rerun()

if c5.button("화학사고예방관리계획서 별표 4 추출", width="stretch"):
    with st.status("화학사고예방관리계획서 별표 4 최대보유량 산정 규칙 추출 중...", expanded=True) as box:
        result = build_cap_appendix4_candidate()
        st.session_state["regdb_cap4"] = result
        box.update(label="화학사고예방관리계획서 별표 4 추출 완료", state="complete", expanded=False)
    st.rerun()

entries = (
    ("regdb_psm", "PSM_ANNEX13", "공정안전보고서 시행령 별표 13", "화학사고예방관리계획서 별표 1·2·3·4 검증"),
    ("regdb_cap1", "CAP_QTY_APP1", "화학사고예방관리계획서 별표 1 유해·위험성 그룹", "별표 4 최대보유량 산정 규칙 검증"),
    ("regdb_cap2", "CAP_QTY_APP2", "화학사고예방관리계획서 별표 2 인체·생태유해성", "별표 4 최대보유량 산정 규칙 검증"),
    ("regdb_cap3", "CAP_QTY_APP3", "화학사고예방관리계획서 별표 3 사고대비물질", "별표 4 최대보유량 산정 규칙 검증"),
    ("regdb_cap4", "CAP_QTY_APP4", "화학사고예방관리계획서 별표 4 최대보유량 산정 방법", "판정진단 준비상태 재확인"),
)

for session_key, db_key, title, next_step in entries:
    result = st.session_state.get(session_key)
    if result is None:
        continue

    st.markdown(f"### {title} 자동추출 결과")
    m1, m2 = st.columns(2)
    m1.metric("상태", result.status)
    m2.metric("추출 행수", f"{result.row_count:,}")
    st.caption(f"원본 PDF: {result.source_file or '-'}")
    for message in result.messages:
        if result.status == "REVIEW_REQUIRED":
            st.info(message)
        else:
            st.warning(message)

    if result.checks:
        with st.expander("추출 품질검사 상세", expanded=result.status != "REVIEW_REQUIRED"):
            _table(_checks_frame(result.checks), 80)

    preview = candidate_preview(db_key)
    if not preview.empty:
        with st.expander("후보표 미리보기", expanded=False):
            _table(preview, 30)

    can_approve = result.status == "REVIEW_REQUIRED" and not preview.empty
    if db_key == "CAP_QTY_APP1":
        confirm_text = (
            "공식 별표 1과 22개 유해성 그룹, 구분별 하위·상위 규정수량, "
            "복수 유해성 그룹 시 가장 작은 수량 적용 원칙을 확인했습니다."
        )
    elif db_key == "CAP_QTY_APP2":
        confirm_text = (
            "공식 별표 2와 행수·물질명·CAS·함량기준·규정수량을 확인했고, "
            "CAS 없는 포괄범위·삭제행·용액 특수행이 보존된 것을 확인했습니다."
        )
    elif db_key == "CAP_QTY_APP4":
        confirm_text = (
            "공식 별표 4와 최대보유량 총합 원칙, 제조·사용시설, 저장탱크, 보관시설, "
            "단순혼합·반응·다중성상·기상물질·혼합물 관련 산정 문구를 확인했습니다."
        )
    else:
        confirm_text = "공식 PDF와 후보표의 행수·물질명·규정수량 및 핵심 행을 확인했습니다."

    confirmed = st.checkbox(confirm_text, key=f"regdb_confirm_{db_key}", disabled=not can_approve)
    if st.button(
        f"{title} 승인 DB로 저장",
        key=f"regdb_approve_{db_key}",
        disabled=not (can_approve and confirmed),
        width="stretch",
    ):
        approval = approve_candidate(db_key)
        st.session_state["regdb_notice"] = {
            "status": approval.get("status", ""),
            "message": approval.get("message", "승인 처리 결과를 확인하세요."),
            "warning": approval.get("archive_warning", ""),
            "next": next_step if approval.get("status") == "APPROVED" else "",
        }
        st.session_state.pop(session_key, None)
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# 3. Evidence archive
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 3. 승인 근거자료 보관")
st.caption(
    "1단계에서 법령·별표·별지의 PDF·HWP/HWPX 원본을 버전별로 관리합니다. "
    "여기서는 판정용 구조화 DB가 정확히 어느 공식 PDF에서 생성되었는지 별도의 감사 근거를 확인합니다."
)
a1, a2 = st.columns(2)
if a1.button("판정 DB 근거 PDF 보관 재확인", width="stretch"):
    approved_keys: list[str] = []
    if not status_df.empty:
        approved_keys = [
            str(row["key"])
            for _, row in status_df.iterrows()
            if bool(row.get("approved")) and str(row.get("key")) in EVIDENCE_CONFIG
        ]
    st.session_state["archive_sync_results"] = sync_approved_evidence(approved_keys)
    st.cache_data.clear()
    st.rerun()

if a2.button("법령 근거자료 폴더 열기", width="stretch"):
    opened = open_archive_folder()
    if opened.get("status") == "OPENED":
        st.toast(str(opened.get("message", "폴더를 열었습니다.")))
    else:
        st.warning(str(opened.get("message", "폴더를 열지 못했습니다.")))

_show_archive_notice()
archive_df = pd.DataFrame(evidence_rows())
if not archive_df.empty:
    display_archive = archive_df.copy()
    if "SHA256" in display_archive.columns:
        display_archive["SHA256"] = display_archive["SHA256"].astype(str).map(lambda v: v[:16] + "…" if len(v) > 16 else v)
    _table(display_archive, 20)

    available = archive_df[archive_df["보관상태"].eq("보관됨")]
    if not available.empty:
        buttons = st.columns(min(4, len(available)))
        for idx, (_, row) in enumerate(available.iterrows()):
            key = str(row["key"])
            label = _human(row["근거"])
            if buttons[idx % len(buttons)].button(f"폴더 열기 · {key}", key=f"open_archive_{key}", width="stretch"):
                opened = open_archive_folder(key)
                if opened.get("status") == "OPENED":
                    st.toast(f"{label} 근거 폴더를 열었습니다.")
                else:
                    st.warning(str(opened.get("message", "폴더를 열지 못했습니다.")))

# ---------------------------------------------------------------------------
# 4. One final readiness gate - same gate used by diagnosis entry
# ---------------------------------------------------------------------------
st.divider()
st.markdown("## 4. 판정진단 준비상태")
if not law_rows:
    st.info("1단계의 최신 법령·첨부원본 확인을 먼저 실행하세요.")
else:
    gate = decision_readiness_gate(law_rows)
    if gate.get("decision") == "ALLOW":
        st.success("법령·첨부원본과 판정용 승인 DB가 서로 연결되어 있습니다. 판정진단을 시작할 수 있습니다.")
        st.page_link("ui/diagnosis_entry.py", label="1. 판정진단으로 이동", icon="✅")
    else:
        st.error("아직 판정진단을 시작할 수 없습니다.")
        st.write(str(gate.get("message") or "법령 최신성 또는 판정용 규정 DB를 확인하세요."))
        blockers = gate.get("blockers") or []
        if blockers:
            st.markdown("**남은 확인사항**")
            for blocker in blockers:
                st.write(f"• {_human(blocker)}")
        st.caption(
            "법령·첨부원본 상태가 CURRENT가 아니면 1단계를, 승인 DB가 없거나 공식 PDF SHA-256이 맞지 않으면 2단계를 처리하세요. "
            "사용자 회사자료와는 별개의 관리자 준비상태입니다."
        )

st.info(
    "화학사고예방관리계획서 규정수량 우선순위는 사고대비물질 별표 3 → 인체·생태유해성 물질별 별표 2 → "
    "그 밖의 유해화학물질에 대한 유해·위험성 그룹 별표 1 순으로 적용합니다. "
    "규정수량을 고른 뒤 실제 비교수량은 별표 4의 시설유형별 최대보유량 산정방법으로 계산합니다."
)
st.caption("최신법령 미반영, 첨부원본 미확인, 자동검증 실패 또는 규정 DB 출처 불일치 시 승인 또는 비대상 확정을 하지 않습니다.")
