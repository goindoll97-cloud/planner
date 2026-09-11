from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import streamlit as st

from engine.cap_engine import assess_cap
from engine.cap_holding import app4_db_ready, build_cap_facility_workbook
from engine.cap_holding_screen import screen_facility_stage
from engine.cap_quick_holding import compare_confirmed_declared_holding
from engine.consulting_guidance import get_guide
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


_psm_exclusion_guide = get_guide("PSM_EXCLUDED_FACILITY")
EXCLUSION_LABELS = [
    "해당 없음",
    *list(_psm_exclusion_guide.what_to_check if _psm_exclusion_guide else ()),
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


def _render_guide(key: str, *, show_title: bool = True, compact: bool = False) -> None:
    """Render one legal question as a consulting card."""
    guide = get_guide(key)
    if guide is None:
        return
    with st.container(border=True):
        if show_title:
            st.markdown(f"**{guide.title}**")
        if guide.why_needed:
            st.write(f"**왜 확인하나요?** {guide.why_needed}")
        st.write(guide.plain_language)
        if guide.what_to_check and not compact:
            st.markdown("**회사에서 확인할 것**")
            for value in guide.what_to_check:
                st.write(f"• {value}")
        if guide.example:
            st.write(f"**예시** {guide.example}")
        if guide.legal_basis:
            st.info(f"법적 근거: {guide.legal_basis}")
        if guide.legal_hierarchy:
            st.markdown("**법령이 다른 규정에 기준을 맡긴 경우**")
            for value in guide.legal_hierarchy:
                st.write(f"• {value}")
        if guide.resolved_detail:
            st.success(guide.resolved_detail)
        if guide.source_status:
            st.caption(f"근거 확인상태: {guide.source_status}")
        if guide.decision_effect and not compact:
            st.write(f"**이 답변이 판정에 미치는 영향** {guide.decision_effect}")
        if guide.if_unknown:
            st.caption(guide.if_unknown)


def _status_card(title: str, status: str, *, value: str = "", explanation: str = "") -> None:
    """Long screening states should wrap instead of being truncated by st.metric."""
    with st.container(border=True):
        st.markdown(f"### {title}")
        st.caption("현재 단계")
        st.markdown(f"#### {status}")
        if value:
            st.markdown(f"**{value}**")
        if explanation:
            st.write(explanation)


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

# Build readable summary text before rendering. st.metric truncates long values,
# so the summary uses normal wrapping containers instead.
if psm.r_value is None:
    psm_status = _cap_text(psm.label)
    psm_value = ""
    psm_explanation = "규정량 비율 계산에 필요한 정보가 더 필요합니다."
elif psm.r_value >= 1:
    psm_value = f"R = {psm.r_value:.4f}"
    if psm_exclusion_choice == "해당 없음":
        psm_status = "수량기준 충족 후보"
        psm_explanation = "수량기준은 충족했지만 최종 PSM 대상 확정 전 단계입니다."
    elif psm_exclusion_choice not in {"선택하세요", "모름"}:
        psm_status = "제외조건 검토 필요"
        psm_explanation = "수량기준은 충족했지만 선택한 제외조건의 실제 적용범위를 확인해야 합니다."
    else:
        psm_status = "수량기준 충족 · 제외조건 확인 필요"
        psm_explanation = "R이 1.0 이상이라는 이유만으로 PSM 대상이 최종 확정되는 것은 아닙니다."
else:
    psm_status = "현재 확인된 수량기준은 100% 미만"
    psm_value = f"R = {psm.r_value:.4f}"
    psm_explanation = "다른 적용조건이나 미확인 정보가 있으면 추가 검토합니다."

if quick_cap is not None:
    cap_status = _cap_text(quick_cap.label)
    if quick_cap.status == "LOWER_CANDIDATE":
        cap_explanation = "하위 규정수량 이상이 확인된 단계입니다. 면제조건 등을 확인한 뒤 2군 여부를 판단합니다."
    elif quick_cap.status == "UPPER_CANDIDATE":
        cap_explanation = "상위 규정수량 이상이 확인된 단계입니다. 주요취급시설 여부 등을 확인한 뒤 1군 여부를 판단합니다."
    else:
        cap_explanation = "최대보유량과 규정수량 비교 결과를 확인한 상태입니다."
elif cap_screen.ready and cap_screen.row_numbers:
    cap_status = "규정수량 대상물질 확인 · 최대보유량 확인 필요"
    cap_explanation = "대상물질은 찾았지만 법정 방식의 사업장 최대보유량을 아직 확인하지 않았습니다."
elif cap.app1_required_rows:
    cap_status = "SDS 유해성 분류 확인 필요"
    cap_explanation = "물질명/CAS 직접목록만으로 비대상을 확정할 수 없는 물질이 있습니다."
else:
    cap_status = _cap_text(cap.label)
    cap_explanation = "현재 입력정보를 기준으로 확인된 단계입니다."

st.markdown("## 1. 지금까지의 결과를 한눈에 보기")
left, right = st.columns(2, gap="large")
with left:
    _status_card(PSM_FULL, psm_status, value=psm_value, explanation=psm_explanation)
with right:
    _status_card(CAP_FULL, cap_status, explanation=cap_explanation)

st.info(
    f"따라서 화면에 {PSM_FULL} 가능성과 {CAP_FULL} 가능성이 함께 표시되는 것은 오류가 아닙니다. "
    "같은 사업장이 두 제도의 검토대상이 될 수 있기 때문에 두 갈래를 동시에 확인하고 있습니다."
)

st.markdown(f"## 2. {PSM_FULL} — 수량기준 다음에 제외조건 확인")
if psm.r_value is not None:
    st.write(
        f"**R = {psm.r_value:.4f} ({psm.r_value * 100:.0f}%)** 입니다. "
        "이 값은 PSM 수량기준을 먼저 확인하기 위한 값이며, 이것만으로 최종 PSM 대상이 확정되지는 않습니다."
    )
    with st.expander("R이 무엇인지 · 법적 근거 보기", expanded=False):
        _render_guide("PSM_R_RATIO", compact=True)

exclusion_questions = [q for q in psm.questions if _is_psm_exclusion_question(q)]
other_psm_questions = [q for q in psm.questions if not _is_psm_exclusion_question(q)]
if exclusion_questions:
    st.markdown("#### 질문 1. 업로드한 화학물질을 실제로 제조·사용·저장하는 공정·설비가 PSM 제외설비에 해당합니까?")
    st.write(
        "아래에는 단순히 '그 밖에 고시하는 설비'라고만 쓰지 않고, 현행 하위 고시에서 구체화된 내용까지 함께 표시합니다. "
        "회사의 실제 설비와 가장 가까운 항목을 선택하고, 판단하기 어렵다면 '모름'을 선택하세요."
    )
    _render_guide("PSM_EXCLUDED_FACILITY", show_title=False)
    exclusion = st.selectbox(
        "PSM 제외설비 선택",
        ["선택하세요", *EXCLUSION_LABELS],
        key="simple_psm_exclusion",
        label_visibility="collapsed",
    )
    if exclusion == "해당 없음" and psm.r_value is not None and psm.r_value >= 1:
        st.success("현재 입력 기준으로 PSM 수량기준 대상 후보입니다. 이후 실제 대상 공정·설비 범위를 확인해야 최종 판단할 수 있습니다.")
    elif exclusion == "비상발전기용 경유의 저장탱크 및 사용설비":
        st.info(
            "이 항목은 시행령의 '그 밖에 고용노동부장관이 고시하는 설비'를 현행 고시 제2조의2에서 구체화한 항목입니다. "
            "실제 설비가 비상발전기용 경유 저장·사용설비인지 확인한 뒤 제외범위를 적용합니다."
        )
    elif exclusion not in {"선택하세요", "해당 없음", "모름"}:
        st.warning("선택한 제외유형이 이번 물질과 관련된 공정·설비에 실제로 적용되는지 증빙 확인이 필요합니다.")
    elif exclusion == "모름":
        st.warning("제외설비 여부가 확인될 때까지 PSM은 판정보류입니다.")
        _render_guide("DECISION_HOLD", compact=True)

if other_psm_questions:
    st.markdown("#### 추가로 확인해야 하는 PSM 특수조건")
    _render_guide("PSM_SPECIAL_CONDITION", show_title=False, compact=True)
    with st.expander(f"실제 확인 질문 {len(other_psm_questions)}개", expanded=False):
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
        "물질별 직접 규정수량 목록에서는 바로 결론이 나지 않았습니다. "
        "아래 SDS 유해성 분류 또는 포괄 규제범위 확인이 필요한 물질이 있는지 계속 확인합니다."
    )
else:
    st.info(
        f"업로드한 물질 중 **{len(cap_screen.row_numbers)}개가 {CAP_FULL}의 물질별 규정수량 기준에 직접 연결**되었습니다. "
        f"따라서 이 물질이 사업장 안에 한 순간 최대 얼마까지 존재할 수 있는지 확인해 규정수량과 비교해야 합니다."
    )
    _table(_cap_direct_preview(intake, cap_screen.legal_hits), 30)

    if not app4_db_ready():
        st.error("최대보유량 계산기준 DB가 준비되지 않았습니다. 일반 사용자가 처리할 항목이 아니므로 관리자 확인이 필요합니다.")
    elif cap_screen.blockers:
        st.warning("같은 물질이라도 상태나 농도 같은 특수조건에 따라 적용할 규정수량이 달라질 수 있습니다.")
        _render_guide("CAP_SPECIAL_CONDITION", show_title=False, compact=True)
        for blocker in cap_screen.blockers:
            st.write(f"• {blocker}")
    else:
        st.markdown("#### 질문 2. 회사 Excel의 '최대 동시보유량' 값은 법에서 말하는 '사업장 최대보유량'으로 계산한 값입니까?")
        _render_guide("CAP_MAX_HOLDING", show_title=False)
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
            template = build_cap_facility_workbook(intake, cap_screen.row_numbers)
            st.download_button(
                "최대보유량 계산용 시설정보 입력서 다운로드",
                data=template,
                file_name="화학사고예방관리계획서_최대보유량_보완입력.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch",
            )
            st.caption(
                "모든 회사가 반드시 작성하는 두 번째 양식이 아닙니다. 현재 입력값이 법정 최대보유량인지 확인할 수 없을 때만 사용하는 보완자료입니다."
            )
            if holding_choice == "잘 모르겠습니다":
                _render_guide("DECISION_HOLD", compact=True)

if cap.app1_required_rows:
    st.markdown("## 4. 왜 SDS 확인이 필요한 물질이 있나요?")
    st.warning(
        f"물질별 직접목록으로 결론이 끝나지 않은 물질이 {len(cap.app1_required_rows)}개 있습니다. "
        f"이 물질들을 곧바로 {CAP_FULL} 비대상으로 처리할 수는 없습니다."
    )
    _render_guide("CAP_APP1_SDS", show_title=False)
    app1_df = pd.DataFrame(cap.app1_required_rows).rename(
        columns={"row_no": "목록행번호", "product_name": "제품명", "cas": "CAS No."}
    )
    _table(app1_df, 40)
    st.caption(
        "현재 버전에서는 SDS 제2항 분류 입력 단계가 아직 간편 화면에 연결되지 않았으므로, 위 물질은 확인이 끝날 때까지 판정보류로 유지합니다."
    )

if cap.scope_candidates:
    st.markdown("## 5. CAS만으로 확정할 수 없는 물질범위")
    st.warning(
        f"염류·화합물군·반응생성물 등 CAS 하나만으로 확정할 수 없는 규제범위 후보가 {len(cap.scope_candidates)}건 있습니다. "
        "이 경우도 자동으로 비대상 처리하지 않고 확인이 끝날 때까지 판정보류합니다."
    )
    _render_guide("CAP_BROAD_SCOPE", show_title=False, compact=True)

st.divider()
st.markdown("### 이 화면에서 기억할 것")
st.write(
    f"**{PSM_FULL}와 {CAP_FULL}는 동시에 해당될 수 있습니다.** "
    "이 화면은 회사 Excel 한 번으로 각각의 가능성을 선별하고, 최종판정에 꼭 필요한 추가정보만 순서대로 요청합니다. "
    "법령 용어를 이미 안다고 가정하지 않고 질문마다 뜻·확인자료·예시·법적 근거를 함께 보여주며, "
    "상위 법령이 고시에 기준을 맡긴 경우에는 확인된 하위 규정의 실제 내용까지 안내합니다."
)
st.caption("규정DB 추출·승인, 별표 PDF 보관, 법령 최신성 확인은 관리자 영역에서 처리하며 일반 회사 사용 흐름에는 넣지 않습니다.")