from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from engine.cap_engine import assess_cap
from engine.cap_holding import app4_db_ready, build_cap_facility_workbook
from engine.cap_holding_screen import screen_facility_stage
from engine.cap_quick_holding import compare_confirmed_declared_holding
from engine.inventory import inventory_preview, read_intake_workbook, validate_intake
from engine.psm_engine import PSM_EXCLUSION_QUESTIONS, assess_psm


CAP_FULL = "화학사고예방관리계획서"
PSM_FULL = "공정안전보고서(PSM)"

st.set_page_config(page_title=f"{PSM_FULL} · {CAP_FULL} 사전진단", page_icon="✅", layout="wide")
st.markdown(
    """
    <style>
    .block-container { max-width: 1120px; }
    div[data-testid="stSelectbox"] label p,
    div[data-testid="stRadio"] label p {
        font-size: 1.05rem !important;
        font-weight: 650 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


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


def _cap_text(value: object) -> str:
    return str(value or "").replace("화사계", CAP_FULL)


def _cap_basis(hit: dict[str, object]) -> str:
    source = str(hit.get("source_key", ""))
    item = str(hit.get("item_no", "-") or "-")
    if source == "CAP_QTY_APP3":
        return f"사고대비물질별 규정수량(별표 3) 제{item}호"
    if source == "CAP_QTY_APP2":
        return f"인체·생태유해성 물질별 규정수량(별표 2) 제{item}호"
    return f"규정수량 기준 제{item}호"


def _cap_direct_preview(intake, legal_hits: list[dict[str, object]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    seen: set[tuple[int, str, str]] = set()
    for hit in legal_hits:
        row_no = int(hit.get("row_no") or 0)
        source = str(hit.get("source_key", ""))
        item_no = str(hit.get("item_no", ""))
        key = (row_no, source, item_no)
        if row_no <= 0 or row_no > len(intake.chemicals) or key in seen:
            continue
        seen.add(key)
        item = intake.chemicals.iloc[row_no - 1]
        rows.append(
            {
                "제품명": item.get("제품명", ""),
                "CAS No.": item.get("CAS No.", ""),
                "확인된 법적 근거": _cap_basis(hit),
                "회사 입력 최대 동시보유량": item.get("최대 동시보유량(알면 입력)", ""),
                "단위": item.get("수량 단위", ""),
                "하위 규정수량(ton)": hit.get("lower_quantity_ton"),
                "상위 규정수량(ton)": hit.get("upper_quantity_ton"),
            }
        )
    return pd.DataFrame(rows)


st.title(f"{PSM_FULL} · {CAP_FULL} 사전진단")
st.caption(
    "회사 Excel을 한 번 올리면 두 제도를 각각 자동 선별하고, 정말 필요한 정보만 추가로 확인합니다."
)
st.info(
    "두 제도는 서로 다른 법적 의무이므로 한 사업장이 둘 다 대상이 될 수 있습니다. "
    f"{PSM_FULL} 결과와 {CAP_FULL} 결과는 서로 대체되는 결과가 아니라 각각 따로 판단하는 결과입니다."
)

uploaded = st.file_uploader(
    "회사 입력파일 업로드 (.xlsx)",
    type=["xlsx"],
    help="기존 PSM_CAP_테스트용_회사입력파일.xlsx도 그대로 사용할 수 있습니다.",
)

if uploaded is None:
    st.caption("일반 사용자는 이 화면만 사용하면 됩니다. 규정DB 관리와 법령근거 화면은 관리자·검토자용입니다.")
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
c2.metric("입력한 화학물질", f"{len(intake.chemicals):,}개")
with st.expander("업로드한 내용 확인", expanded=False):
    _table(inventory_preview(intake), 40)

# Upload itself triggers the screening. No separate start button.
psm = assess_psm(intake)
cap = assess_cap(intake)
cap_screen = screen_facility_stage(intake)

psm_exclusion_choice = str(st.session_state.get("simple_psm_exclusion", "선택하세요"))
cap_holding_choice = str(st.session_state.get("simple_cap_holding_basis", "선택하세요"))
quick_cap = None
if (
    cap_holding_choice == "예, 법정 산정방식으로 계산한 값입니다"
    and app4_db_ready()
    and cap_screen.ready
    and cap_screen.row_numbers
    and not cap_screen.blockers
):
    quick_cap = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)

st.markdown("## 1. 지금까지의 결과를 한눈에 보기")
left, right = st.columns(2)

with left:
    st.markdown(f"### {PSM_FULL}")
    if psm.r_value is None:
        st.metric("현재 단계", psm.label)
        st.caption("규정량 비율 계산에 필요한 정보가 더 필요합니다.")
    elif psm.r_value >= 1:
        if psm_exclusion_choice == "해당 없음":
            st.metric("현재 단계", "수량기준 충족 후보", f"R = {psm.r_value:.4f}")
            st.caption("수량기준은 충족했지만 최종 PSM 대상 확정 전 단계입니다.")
        elif psm_exclusion_choice not in {"선택하세요", "모름"}:
            st.metric("현재 단계", "제외조건 검토 필요", f"R = {psm.r_value:.4f}")
            st.caption("수량기준은 충족했지만 선택한 제외조건의 실제 적용범위를 확인해야 합니다.")
        else:
            st.metric("현재 단계", "수량기준 충족 · 제외조건 확인 필요", f"R = {psm.r_value:.4f}")
            st.caption("R이 1.0 이상이라는 이유만으로 PSM 대상이 최종 확정되는 것은 아닙니다.")
    else:
        st.metric("현재 단계", "현재 확인된 수량기준은 100% 미만", f"R = {psm.r_value:.4f}")
        st.caption("다른 적용조건이나 미확인 정보가 있으면 추가 검토합니다.")

with right:
    st.markdown(f"### {CAP_FULL}")
    if quick_cap is not None:
        st.metric("현재 단계", _cap_text(quick_cap.label))
        if quick_cap.status == "LOWER_CANDIDATE":
            st.caption("하위 규정수량 이상이 확인된 단계입니다. 면제조건 등을 확인한 뒤 2군 여부를 판단합니다.")
        elif quick_cap.status == "UPPER_CANDIDATE":
            st.caption("상위 규정수량 이상이 확인된 단계입니다. 주요취급시설 여부 등을 확인한 뒤 1군 여부를 판단합니다.")
        else:
            st.caption("최대보유량과 규정수량 비교 결과를 확인한 상태입니다.")
    elif cap_screen.ready and cap_screen.row_numbers:
        st.metric("현재 단계", "규정수량 대상물질 확인 · 최대보유량 확인 필요")
        st.caption("대상물질은 찾았지만 법정 방식의 사업장 최대보유량을 아직 확인하지 않았습니다.")
    elif cap.app1_required_rows:
        st.metric("현재 단계", "SDS 유해성 분류 확인 필요")
        st.caption("물질명/CAS 직접목록만으로 비대상을 확정할 수 없는 물질이 있습니다.")
    else:
        st.metric("현재 단계", _cap_text(cap.label))

st.info(
    f"따라서 화면에 {PSM_FULL} 가능성과 {CAP_FULL} 가능성이 함께 표시되는 것은 오류가 아닙니다. "
    "같은 사업장이 두 제도의 검토대상이 될 수 있기 때문에 두 갈래를 동시에 확인하고 있습니다."
)

st.markdown(f"## 2. {PSM_FULL} — 수량기준 다음에 제외조건 확인")
if psm.r_value is not None:
    st.write(
        f"**R = {psm.r_value:.4f} ({psm.r_value * 100:.0f}%)** 입니다. "
        "R은 별표 13의 물질별 보유량을 각 규정량으로 나눈 비율을 합산한 값입니다. "
        "**R이 1.0 이상이면 수량기준을 충족할 가능성이 있다는 뜻이며, 이것만으로 최종 PSM 대상이 확정되지는 않습니다.**"
    )

exclusion_questions = [q for q in psm.questions if _is_psm_exclusion_question(q)]
other_psm_questions = [q for q in psm.questions if not _is_psm_exclusion_question(q)]
if exclusion_questions:
    st.markdown("#### 현재 업로드한 화학물질을 실제로 제조·사용·저장하는 공정·설비가 아래 PSM 제외유형 중 하나에 해당합니까?")
    st.caption(
        "여기서 '관련 공정·설비'는 아직 특정 설비명을 입력했다는 뜻이 아닙니다. "
        "이번 Excel에 적은 화학물질을 실제로 제조·사용·저장하는 반응기, 저장탱크, 공급설비 등의 범위를 뜻합니다."
    )
    exclusion = st.selectbox(
        "PSM 제외설비 선택",
        ["선택하세요", *EXCLUSION_LABELS],
        key="simple_psm_exclusion",
        label_visibility="collapsed",
    )
    if exclusion == "해당 없음" and psm.r_value is not None and psm.r_value >= 1:
        st.success("현재 입력 기준으로 PSM 수량기준 대상 후보입니다. 이후 실제 대상 공정·설비 범위를 확인해야 최종 판단할 수 있습니다.")
    elif exclusion not in {"선택하세요", "해당 없음", "모름"}:
        st.warning("선택한 제외유형이 이번 물질과 관련된 공정·설비 전체에 실제로 적용되는지 증빙 확인이 필요합니다.")
    elif exclusion == "모름":
        st.warning("제외설비 여부가 확인될 때까지 PSM은 판정보류입니다.")

if other_psm_questions:
    with st.expander(f"PSM에서 추가로 확인할 수 있는 항목 {len(other_psm_questions)}개", expanded=False):
        st.caption("CAS 목록만으로 판단할 수 없는 물성조건이나 특수조건이 있을 때만 필요한 질문입니다.")
        for question in other_psm_questions:
            st.write(f"• {question}")

with st.expander("PSM 계산 근거 보기 · 검토자용", expanded=False):
    if psm.ratio_lines:
        _table(pd.DataFrame([asdict(row) for row in psm.ratio_lines]), 50)
    if psm.blockers:
        st.markdown("**보류·확인사항**")
        for blocker in psm.blockers:
            st.write(f"• {blocker}")

st.markdown(f"## 3. {CAP_FULL} — 왜 최대보유량을 확인하나요?")
if not cap_screen.ready:
    st.error("시스템의 규정수량 DB가 준비되지 않았습니다. 일반 사용자가 해결할 항목이 아니므로 관리자에게 확인이 필요합니다.")
    for blocker in cap_screen.blockers:
        st.caption(blocker)
elif not cap_screen.row_numbers:
    st.info(
        "별표 2·3의 직접 물질목록에서는 바로 확인된 대상이 없습니다. "
        "아래 SDS 유해성 분류 또는 포괄 규제범위 확인이 필요한 물질이 있는지 계속 확인합니다."
    )
else:
    st.info(
        f"업로드한 물질 중 **{len(cap_screen.row_numbers)}개가 {CAP_FULL}의 물질별 규정수량 기준에 직접 연결**되었습니다. "
        f"그래서 {CAP_FULL}에서는 이 물질이 사업장 안에 한 순간 최대 얼마까지 존재할 수 있는지 확인해 하위·상위 규정수량과 비교해야 합니다."
    )
    _table(_cap_direct_preview(intake, cap_screen.legal_hits), 30)

    if not app4_db_ready():
        st.error("최대보유량 계산기준 DB가 준비되지 않았습니다. 일반 사용자가 처리할 항목이 아니므로 관리자 확인이 필요합니다.")
    elif cap_screen.blockers:
        st.warning("물질의 상태나 특수조건을 먼저 확인해야 최대보유량 비교를 계속할 수 있습니다.")
        for blocker in cap_screen.blockers:
            st.write(f"• {blocker}")
    else:
        st.markdown("#### 회사 Excel의 '최대 동시보유량'은 사업장 내 관련 제조·사용·저장·보관시설을 모두 고려해 계산한 값입니까?")
        st.caption(
            "예를 들어 같은 물질이 반응기와 저장탱크에 동시에 존재할 수 있다면 둘을 모두 고려한 값이어야 합니다. "
            "잘 모르겠다면 '잘 모르겠습니다'를 선택하세요."
        )
        holding_choice = st.radio(
            "최대 동시보유량 산정방식 확인",
            ["선택하세요", "예, 법정 산정방식으로 계산한 값입니다", "아니오, 단순 재고량 또는 임의값입니다", "잘 모르겠습니다"],
            key="simple_cap_holding_basis",
            label_visibility="collapsed",
        )

        if holding_choice == "예, 법정 산정방식으로 계산한 값입니다":
            quick = compare_confirmed_declared_holding(intake, cap_screen.legal_hits)
            if quick.status == "HOLD":
                st.warning(_cap_text(quick.label))
                for blocker in quick.blockers:
                    st.write(f"• {blocker}")
            elif quick.status in {"UPPER_CANDIDATE", "LOWER_CANDIDATE"}:
                st.success(_cap_text(quick.label))
            else:
                st.info(_cap_text(quick.label))
            if quick.comparison_rows:
                with st.expander(f"{CAP_FULL} 규정수량 비교 근거 보기", expanded=False):
                    _table(pd.DataFrame(quick.comparison_rows), 60)

        elif holding_choice in {"아니오, 단순 재고량 또는 임의값입니다", "잘 모르겠습니다"}:
            st.warning(
                "현재 값으로는 법적 최대보유량을 확정하지 않습니다. 정확한 계산이 필요하므로 해당 물질이 실제로 들어 있는 시설정보만 추가로 확인합니다."
            )
            st.write(
                "아래 입력서는 모든 회사가 반드시 작성하는 두 번째 양식이 아닙니다. "
                "**현재 Excel의 최대 동시보유량이 법정 계산방식인지 모를 때만 사용하는 보완용 입력서**입니다."
            )
            template = build_cap_facility_workbook(intake, cap_screen.row_numbers)
            st.download_button(
                "최대보유량 계산용 시설정보 입력서 다운로드",
                data=template,
                file_name="화학사고예방관리계획서_최대보유량_보완입력.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.caption(
                "이 입력서는 현행 별표 4의 최대보유량 산정방법을 적용하기 위한 자료입니다. "
                "시설별 설계용량·비중·보관량 등 필요한 항목만 작성합니다."
            )

if cap.app1_required_rows:
    st.markdown("## 4. 왜 SDS 확인이 필요한 물질이 있나요?")
    st.warning(
        f"별표 2·3의 CAS 직접목록으로 결론이 끝나지 않은 물질이 {len(cap.app1_required_rows)}개 있습니다. "
        f"이 물질들을 곧바로 {CAP_FULL} 비대상으로 처리할 수는 없습니다."
    )
    st.write(
        "**이유는 별표 1이 '물질명 목록'이 아니라 SDS 제2항의 유해성·위험성 분류를 기준으로 적용되는 표이기 때문입니다.** "
        "따라서 별표 2·3에서 직접 찾지 못한 물질은 SDS 제2항에 기재된 급성독성·인화성·수생환경 유해성 등의 분류를 확인해야 별표 1 적용 여부를 판단할 수 있습니다."
    )
    app1_df = pd.DataFrame(cap.app1_required_rows).rename(
        columns={"row_no": "목록행번호", "product_name": "제품명", "cas": "CAS No."}
    )
    _table(app1_df, 40)
    st.caption(
        "현재 버전에서는 SDS 제2항 분류 입력 단계가 아직 간편 화면에 연결되지 않았으므로, 위 물질은 확인이 끝날 때까지 판정보류로 유지합니다. "
        "물질명이나 CAS만 보고 프로그램이 임의로 유해성 분류를 추정하지 않습니다."
    )

if cap.scope_candidates:
    st.markdown("## 5. CAS만으로 확정할 수 없는 물질범위")
    st.warning(
        f"염류·화합물군·반응생성물 등 CAS 하나만으로 확정할 수 없는 규제범위 후보가 {len(cap.scope_candidates)}건 있습니다. "
        "이 경우도 자동으로 비대상 처리하지 않고 확인이 끝날 때까지 판정보류합니다."
    )

st.divider()
st.markdown("### 이 화면에서 기억할 것")
st.write(
    f"**{PSM_FULL}와 {CAP_FULL}는 동시에 해당될 수 있습니다.** "
    "지금 화면은 두 제도의 최종 제출대상을 한 번에 확정하는 화면이 아니라, 회사 Excel 한 번으로 각각의 가능성을 선별하고 "
    "정말 필요한 추가정보만 순서대로 요청하는 화면입니다."
)
st.caption("규정DB 추출·승인, 별표 PDF 보관, 법령 최신성 확인은 관리자 영역에서 처리하며 일반 회사 사용 흐름에는 넣지 않습니다.")
