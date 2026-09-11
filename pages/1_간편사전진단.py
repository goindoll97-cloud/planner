from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from engine.cap_engine import assess_cap
from engine.cap_holding import app4_db_ready, build_cap_facility_workbook
from engine.cap_holding_screen import screen_facility_stage
from engine.cap_quick_holding import compare_confirmed_declared_holding, declared_holding_preview
from engine.inventory import inventory_preview, read_intake_workbook, validate_intake
from engine.psm_engine import PSM_EXCLUSION_QUESTIONS, assess_psm


st.set_page_config(page_title="PSM·화사계 간편 사전진단", page_icon="✅", layout="wide")


EXCLUSION_LABELS = [
    "해당 없음",
    "원자력 설비",
    "군사시설",
    "사업장 난방용 연료 저장·사용설비",
    "도매·소매시설",
    "차량 등 운송설비",
    "LPG 충전·저장시설",
    "도시가스 공급시설",
    "기타 고용노동부 고시 제외설비",
    "모름",
]


def _table(df: pd.DataFrame, max_rows: int = 50) -> None:
    if df is None or df.empty:
        st.caption("표시할 내용이 없습니다.")
        return
    st.dataframe(df.head(max_rows), width="stretch", hide_index=True)
    if len(df) > max_rows:
        st.caption(f"전체 {len(df):,}행 중 앞 {max_rows:,}행만 표시합니다.")


def _is_psm_exclusion_question(text: str) -> bool:
    return text in PSM_EXCLUSION_QUESTIONS


st.title("PSM·화사계 간편 사전진단")
st.caption(
    "회사 Excel을 한 번 올리면 PSM과 화사계를 동시에 선별합니다. "
    "추가자료는 실제 판정에 필요한 경우에만 아래에서 요청합니다."
)
st.info(
    "일반 사용자는 이 화면만 사용하면 됩니다. '규정DB 관리', '법령근거 보기'는 관리자·검토자용 화면입니다."
)

uploaded = st.file_uploader(
    "회사 입력파일 업로드 (.xlsx)",
    type=["xlsx"],
    help="기존 PSM_CAP_테스트용_회사입력파일.xlsx도 그대로 사용할 수 있습니다.",
)

if uploaded is None:
    st.stop()

try:
    intake = read_intake_workbook(uploaded.getvalue())
except Exception as exc:
    st.error(f"입력파일을 읽지 못했습니다: {type(exc).__name__}: {exc}")
    st.stop()

issues = validate_intake(intake)
if issues:
    st.error("입력파일에서 먼저 보완할 항목이 있습니다.")
    for issue in issues:
        st.write(f"• {issue}")
    st.stop()

st.session_state["intake"] = intake

c1, c2 = st.columns(2)
c1.metric("사업장", str(intake.business.get("사업장명") or "미입력"))
c2.metric("화학물질", f"{len(intake.chemicals):,}개")
with st.expander("업로드 내용 확인", expanded=False):
    _table(inventory_preview(intake), 40)

# Upload itself is the trigger: no extra '진단 시작' click.
psm = assess_psm(intake)
cap = assess_cap(intake)
cap_screen = screen_facility_stage(intake)

st.markdown("## 1. 자동 선별 결과")
p1, p2 = st.columns(2)
psm_r = psm.r_value
if psm_r is not None:
    p1.metric("PSM", psm.label, f"R = {psm_r:.4f}")
else:
    p1.metric("PSM", psm.label)
p2.metric("화사계", cap.label)

st.markdown("## 2. PSM — 필요한 것만 확인")
if psm.r_value is not None:
    st.write(f"합산 규정량 비율 **R = {psm.r_value:.4f} ({psm.r_value * 100:.0f}%)**")
    if psm.r_value >= 1:
        st.warning("현재 수량기준은 100% 이상입니다. 제외설비 여부를 확인하면 다음 판정으로 갈 수 있습니다.")
    else:
        st.info("현재 확인된 별표 13 수량기준은 100% 미만입니다. 다른 적용조건 또는 미확인 항목이 있으면 계속 확인합니다.")

exclusion_questions = [q for q in psm.questions if _is_psm_exclusion_question(q)]
other_psm_questions = [q for q in psm.questions if not _is_psm_exclusion_question(q)]
if exclusion_questions:
    exclusion = st.selectbox(
        "이번 판정대상 설비가 PSM 제외설비에 해당합니까?",
        ["선택하세요", *EXCLUSION_LABELS],
        key="simple_psm_exclusion",
    )
    if exclusion == "해당 없음" and psm.r_value is not None and psm.r_value >= 1:
        st.success("현재 입력 기준으로 PSM 수량기준 대상 후보입니다. 최종 제출범위는 대상 공정·설비 확인 단계에서 확정합니다.")
    elif exclusion not in {"선택하세요", "해당 없음", "모름"}:
        st.warning("선택한 제외조건이 실제 판정대상 설비 전체에 적용되는지 증빙 확인이 필요합니다.")
    elif exclusion == "모름":
        st.warning("제외설비 여부가 확인될 때까지 PSM은 판정보류입니다.")

if other_psm_questions:
    with st.expander(f"PSM 추가 확인 {len(other_psm_questions)}개", expanded=False):
        for question in other_psm_questions:
            st.write(f"• {question}")

with st.expander("PSM 계산 상세", expanded=False):
    if psm.ratio_lines:
        _table(pd.DataFrame([asdict(row) for row in psm.ratio_lines]), 50)
    if psm.blockers:
        st.markdown("**보류·확인사항**")
        for blocker in psm.blockers:
            st.write(f"• {blocker}")

st.markdown("## 3. 화사계 — 최대보유량은 빠른 경로 우선")
if not cap_screen.ready:
    for blocker in cap_screen.blockers:
        st.warning(blocker)
elif not cap_screen.row_numbers:
    st.info("별표 2·3 직접대상은 없습니다. 별표 1 유해성그룹 또는 포괄 규제범위 검토가 필요한 물질만 추가 확인합니다.")
else:
    st.write(
        f"별표 3 → 별표 2 우선순위에서 직접 규칙 대상 **{len(cap_screen.row_numbers)}개 물질**을 확인했습니다."
    )
    preview = declared_holding_preview(intake, cap_screen.legal_hits)
    _table(preview, 30)

    if not app4_db_ready():
        st.warning("별표 4 승인 DB가 아직 없어 최대보유량 확정 비교는 보류합니다. 관리자 화면에서 별표 4를 승인하세요.")
    elif cap_screen.blockers:
        for blocker in cap_screen.blockers:
            st.warning(blocker)
    else:
        confirmed = st.checkbox(
            "위 '최대 동시보유량' 값은 별표 4 기준으로 사업장 내 관련 제조·사용·저장·보관시설을 모두 고려해 산정한 값입니다.",
            key="simple_cap_app4_confirm",
        )
        st.caption(
            "확실하지 않으면 체크하지 마세요. 체크하지 않은 경우에만 아래 상세 시설정보 입력서를 사용합니다."
        )

        if confirmed:
            quick = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)
            if quick.status == "HOLD":
                st.warning(quick.label)
                for blocker in quick.blockers:
                    st.write(f"• {blocker}")
            elif quick.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE"}:
                st.success(quick.label)
            else:
                st.info(quick.label)
            if quick.comparison_rows:
                with st.expander("화사계 규정수량 비교 상세", expanded=True):
                    _table(pd.DataFrame(quick.comparison_rows), 60)
        else:
            with st.expander("별표 4 상세 시설정보가 필요한 경우", expanded=False):
                st.write(
                    "최대 동시보유량이 별표 4 기준인지 확실하지 않을 때만 사용하세요. "
                    "직접 규칙 대상 물질만 들어 있는 2차 입력서를 생성합니다."
                )
                template = build_cap_facility_workbook(intake, cap_screen.row_numbers)
                st.download_button(
                    "별표 4 시설정보 입력서 다운로드",
                    data=template,
                    file_name="화사계_별표4_시설정보_2차입력.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    width="stretch",
                )
                st.caption("작성 후 기존 'CAP 최대보유량' 상세 화면에서 업로드하면 시설별 계산을 검증할 수 있습니다.")

if cap.app1_required_rows:
    st.markdown("### SDS 확인이 필요한 별표 1 후보")
    st.warning(
        f"별표 2·3으로 직접 확정되지 않은 물질 {len(cap.app1_required_rows)}개는 별표 1 적용 여부를 위해 SDS 제2항 유해성·위험성 분류 확인이 필요합니다."
    )
    _table(pd.DataFrame(cap.app1_required_rows), 40)

if cap.scope_candidates:
    st.markdown("### 포괄 규제범위 확인 필요")
    st.warning(f"CAS만으로 확정할 수 없는 포괄 규제범위 후보가 {len(cap.scope_candidates)}건 있습니다. 자동으로 비대상 처리하지 않습니다.")

st.markdown("## 4. 지금 화면에서의 결론")
st.write(
    "이 간편 화면의 목표는 **한 번 업로드 → 자동 선별 → 정말 필요한 질문만 추가**입니다. "
    "화사계는 아직 면제조건과 주요취급시설/1군·2군 최종분류가 연결되기 전이므로, 현재는 상위·하위 기준 후보 또는 판정보류까지만 확정합니다."
)
st.caption(
    "관리자용 규정DB 추출·승인과 법령근거 폴더 확인은 일반 회사 사용 흐름에 포함하지 않습니다."
)
