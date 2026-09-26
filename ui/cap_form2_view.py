from __future__ import annotations

import pandas as pd
import streamlit as st

from ui import cap_frames as frames

from engine.stage2 import cap_form2_workspace as f2
from engine.stage2 import cap_article29 as article29
from engine.stage2 import cap_change_tracking as change_tracking
from engine.stage2 import versioning
from engine.regulatory_tables import observed_source
from engine.law_attachment_archive import approved_source_is_current
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project


def _column_config(columns: list[dict]) -> dict:
    config = {}
    for col in columns:
        if col.get("kind") == "choice":
            config[col["id"]] = st.column_config.SelectboxColumn(col["label"], help=col.get("help"), options=col["options"])
        else:
            config[col["id"]] = st.column_config.TextColumn(col["label"], help=col.get("help"))
    return config


def _render_change_guide() -> None:
    st.info("**왜 이 서식을 작성하나요?** 제출한 화학사고예방관리계획서와 실제 사업장 상태가 달라지면, 무엇이 바뀌었고 어떤 조치를 했는지 이 관리대장에 계속 기록합니다. 저장탱크, 물질, 공정, 안전설비, 주변환경 정보 등의 변경을 나중에 추적할 수 있게 하는 자료입니다.")
    with st.expander("이 대장은 언제 작성하고, 언제 제출하나요?", expanded=True):
        st.markdown("**1. 사업장에서 변경이 생겼나요?** 계획서가 적합 판정을 받은 뒤 시설·물질·공정·도면 등 계획서 내용과 관련된 사항이 바뀌면, 변경일·변경 전후 내용·검토 결과와 후속조치를 대장에 기록합니다. 대장을 작성했다고 별도의 변경제출이나 영업 변경절차가 끝나는 것은 아닙니다.")
        st.markdown("**2. 변경된 계획서를 지금 제출해야 하나요?** 시설을 신설·증설하거나, 유해화학물질을 추가·변경하고, 물질의 농도·상태나 시설 위치를 바꾸는 경우에는 사고가 났을 때 영향을 받는 구역이 기존보다 넓어지는지 확인합니다. 이를 ‘총괄영향범위 확대’라고 합니다. **해당 변경이 법에서 정한 조건에 맞고 영향범위가 확대되면** 변경된 계획서와 이 대장을 함께 **변경완료일 30일 이전까지** 화학물질안전원에 제출합니다. 시설 신설·증설에는 사고시나리오 규정량 등 추가 조건도 확인합니다. 시설을 늘렸다는 사실만으로 제출 대상으로 확정하지 않습니다.")
        st.markdown("**영향범위가 넓어지지 않아도 확인할 경우**: 사업장의 작성수준이 **2군에서 1군으로 바뀌면** 변경된 계획서를 제출합니다. 필요한 조건을 아직 확인하지 못했다면 대장에 변경사실을 기록하고 제출 대상 여부를 확인합니다. 조건에 해당하지 않더라도 변경된 계획서를 제출할 수 있습니다.")
        st.caption("날짜 예시: 제출 대상인 탱크 증설의 변경완료 예정일이 2026년 11월 30일이라면, 2026년 10월 31일까지 계획서와 대장을 제출합니다. 이 기한은 유해화학물질 **영업** 변경신고·변경허가의 기한과 다릅니다.")
        st.markdown("**3. 화학물질안전원에서 주민 대피계획 보완을 통지했나요?** 대피장소, 주민 경보 전달 방법·절차, 관계기관 협의체계를 고치라는 **계획서 제출 통지**를 받았다면 **통지받은 날부터 60일 이내**에 변경된 계획서와 대장을 제출합니다. 사업장이 자체적으로 주민 대피계획을 손봤다는 사실만으로 이 60일 기한을 적용하지 않습니다.")
        st.markdown("**4. 매년 제출해야 하는 사업장인가요?** 취급하는 유해화학물질이 **상위 규정수량 이상**인 사업장 내 취급시설을 법에서는 ‘주요취급시설’이라고 합니다. 주요취급시설 운영자는 계획서 적합통보를 받은 **다음 연도부터 매년**, 자체점검 결과와 대장을 함께 제출합니다. 최초 제출(또는 1군 상향에 따른 최초 제출)의 적합통보일이 속한 **분기의 마지막 날**이 그해의 제출기한입니다. 예: 기준 적합통보가 2025년 5월이면 2026년부터 매년 **6월 30일**까지 제출합니다.")
        st.markdown("**5. 1군 사업장의 5년 재제출 시기인가요?** 계획서를 처음 제출해 적합통보를 받았고 그 뒤 계획서 변경제출이 없었다면, 적합통보일부터 **5년이 되는 날 이전**에 계획서를 재제출하며 대장도 포함합니다. 중간에 변경제출을 해 적합통보를 받았다면 그 **변경제출 적합통보일을 기준**으로 5년을 계산합니다. 법에 따라 취급중단·휴업·폐업 신고가 수리된 기간은 계산에서 제외될 수 있습니다. 5년은 모든 사업장이 **대장만** 따로 내는 주기가 아닙니다.")
        with st.expander("위 안내의 법적 근거 확인"):
            st.markdown("- 대장 작성·변경제출 대상·제출서류·기한·5년 재제출: [「화학사고예방관리계획서 작성 등에 관한 규정」 제11조·제12조·제14조](https://law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000278102)")
            st.markdown("- 변경제출 판단조건과 주요취급시설의 뜻: [「화학물질관리법 시행규칙」 제19조제6항부터 제9항](https://www.law.go.kr/LSW/lsLawLinkInfo.do?chrClsCd=010202&lsJoLnkSeq=900785871)")
            st.markdown("- 주요취급시설의 연간 제출기한: [「화학사고예방관리계획서 이행 등에 관한 규정」 제4조제2항](https://www.law.go.kr/LSW/admRulLsInfoP.do?admRulSeq=2100000279958)")
    st.caption("변경을 기록하는 것과 변경제출·변경신고·변경허가 대상인 것은 별개의 판단입니다. 모든 변경을 곧바로 제출·신고하는 것은 아닙니다.")
    with st.expander("이 서식을 처음 작성한다면: 작성 순서와 입력 예시", expanded=True):
        st.markdown("**작성 순서**: ① 실제 변경 확인 → ② 이전 제출본과 현재 자료 비교 → ③ 바뀐 계획서 항목·변경의 종류 기록 → ④ 계획서 변경제출과 영업 변경절차를 각각 검토 → ⑤ 수행한 조치·담당자를 대장에 기록합니다.")
        st.markdown("**변경항목은 ‘어느 부분’, 변경의 종류는 ‘어떤 성격’입니다.** 예를 들어 탱크의 용량이 10 m³에서 15 m³로 커졌다면 변경항목은 ‘장치·설비 목록 및 명세’, 종류는 ‘시설규모 변경’입니다.")
        st.markdown("변경항목 예시: 사업장 일반정보, 취급시설 개요, 유해화학물질 목록 및 명세, 설비배치도, 공정흐름도, 공정배관계장도(P&ID), 장치·설비 목록 및 명세, 고정식 유해감지시설, 주변환경정보, 지역사회 고지계획. **실제로 바뀐 계획서 작성항목을 확인해 선택하세요.**")
        st.markdown("**변경내용에는 전후 차이를 남기세요.** ‘탱크 변경’ 대신 ‘TK-101 저장용량을 10 m³에서 15 m³로 증설함’처럼 설비번호·용량·물질명·CAS 번호·수량·도면번호 등 확인 가능한 정보를 적습니다. 문장과 전후 비교 중 편한 방식을 사용해도 됩니다.")
    with st.expander("변경의 종류별 뜻 보기"):
        st.markdown("**변경의 종류는 복수 선택할 수 있습니다.** 하나의 변경 건에서 두 가지 이상의 변경이 동시에 발생했다면 해당되는 종류를 모두 선택합니다. 예를 들어 동일한 저장탱크의 위치를 변경하면서 재질도 변경했다면 '시설위치 변경'과 '시설 재질 변경'을 함께 선택합니다.")
        for label, explanation in f2.CHANGE_TYPE_GUIDANCE.items():
            st.markdown(f"- **{label}**: {explanation}")
        st.caption("같은 변경 건이면 여러 종류를 한 행에 함께 기록할 수 있습니다. 서로 다른 설비·변경일자·변경사유·후속조치라면 별도 행으로 나누어 기록하는 것이 좋습니다.")
    with st.expander("후속조치가 헷갈린다면: 제출·관리·신고·허가"):
        st.markdown("**후속조치는 바로 위 ④ 변경내용에 적은 ‘그 변경’에 대해 무엇을 했는지 기록하는 칸입니다.** ④에는 무엇이 어떻게 바뀌었는지, ⑤에는 그 변경을 검토한 뒤 계획서를 다시 제출했는지, 회사 내부에서 관리했는지, 영업 관련 신고·허가를 진행했는지를 적습니다. 같은 변경으로 둘 이상의 절차가 필요할 수도 있습니다.")
        st.markdown("**한 행을 채우는 예시**: ④ ‘설비 P-101의 도면번호를 P-102로 정정함. 실제 시설 변경 없음’ / ⑤ 변경제출·영업 변경절차 대상이 아님을 확인하고 자료를 정정·관리했다면 ‘변경관리’. 담당자와 조치한 날짜도 확인해 기록합니다.")
        st.caption("다른 예: ④ ‘새 물질 B를 추가함’ / ⑤ 먼저 사업장의 영업구분과 변경 후 수량을 확인합니다. 변경신고·변경허가 등은 검토 후보만으로 기입하지 않고, 적용 여부와 실제 처리 상태를 확인한 뒤 적습니다.")
        for label, explanation in f2.FOLLOW_UP_GUIDANCE.items():
            st.markdown(f"- **{label}**: {explanation}")
        st.markdown("**변경신고란?** 영업허가 또는 영업신고 사업자가 법에서 정한 변경사항을 **관할 지방환경관서**에 알리는 절차입니다. 법적 근거: 「화학물질관리법 시행규칙」 제29조제1항제2호(허가 사업자) 및 제3호(신고 사업자).")
        st.markdown("**변경허가란?** 영업허가 사업자가 법정 변경허가 대상에 해당할 때 **변경 전에 관할 지방환경관서의 허가를 받는 절차**입니다. 법적 근거: 「화학물질관리법 시행규칙」 제29조제1항제1호.")
        st.caption("‘지방관서’는 관할 지방환경관서를 뜻합니다. 계획서 변경제출을 받는 화학물질안전원과 구별하세요. ‘기재사항 변경’은 영업허가·신고 서류의 기재 내용 관련 조치로, 적용 여부는 서류와 관할 기관에 확인하세요.")
        st.warning("물질 추가·취급량 증가 시 규정수량 구간을, 시설 변경 시 변경된 계획서 제출 필요 여부·사고시나리오 규정량·총괄영향범위 변화를 확인해야 할 수 있습니다. 사실이 확인되지 않으면 아래 제29조 검토에서 ‘확인 필요’로 남깁니다.")
        st.markdown("법적 근거: [작성 등에 관한 규정 제11조](https://www.law.go.kr/DRF/lawService.do?ID=2100000278102&OC=me_pr&mobileYn=Y&target=admrul&type=HTML) · [화학물질관리법 시행규칙 제29조](https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joBrNo=00&joNo=0029&lsiSeq=279031&urlMode=lsScJoRltInfoR)")
    with st.expander("어디서 확인하나요? 변경 사례와 확인자료"):
        st.markdown("| 변경 사례 | 먼저 확인할 자료·조건 |\n|---|---|\n| 저장탱크 용량 증가 | 설비목록·P&ID·설비배치도, 이전 용량과 현재 용량, 누적 증가량·영향범위 |\n| 새 유해화학물질 추가 | 회사 물질목록·공급자 SDS, 별지 제1호·규정수량 구간·취급량 |\n| 취급시설 위치 변경 | 이전·현재 설비배치도, 부지 경계, 사고시나리오·KORA/GIS 검토결과 |\n| 대표자 변경 | 사업자등록증·영업허가증 또는 영업신고 서류 |\n| 설비명·도면번호 최신화 | 변경 전후 설비목록·도면, 실제 시설 변경 여부 |")
        st.caption("사례는 이해를 돕기 위한 것입니다. 실제 후속조치는 「화학물질관리법 시행규칙」 제29조와 「화학사고예방관리계획서 작성 등에 관한 규정」 제11조의 조건을 확인한 뒤 정합니다.")



ARTICLE29_EVENTS = {
    "facility": "취급시설 신설·증설·위치·취급물질 변경",
    "material": "유해화학물질 추가·취급량 증가",
    "storage_capacity": "보관·저장시설 또는 운반시설 용량 증가",
    "holding_total": "물질별 최대보유량 합계 증가",
    "vehicle": "운반차량 종류·대수·용량 변경",
    "trial": "60일 이내 시범생산",
    "site": "사업장 소재지 변경",
    "office": "사무실 소재지 변경",
    "name": "사업장 명칭 변경",
    "representative": "대표자 변경",
    "technician": "기술인력 변경",
}


def _render_version_change_candidates(project) -> None:
    """Offer only confirmed fact differences; never copy a legal conclusion."""
    versions = versioning.list_versions(project.project_id, "CAP")
    with st.expander("이전에 저장한 화학사고예방관리계획서와 비교해 변경내역 후보 찾기"):
        if not versions:
            st.caption("비교할 이전 화학사고예방관리계획서 저장본이 없습니다. 기존 제출본의 내용을 확인해 변경내역을 직접 작성하세요.")
            return
        ids = [meta.version_id for meta in versions]
        base_record = project.get_field("cap.submission.base_version_id")
        default = str(base_record.value) if base_record and base_record.value in ids else ids[-1]
        selected_version = st.selectbox(
            "비교 기준(이전 제출·적합본 확인)", ids, index=ids.index(default),
            key=f"cap_form02_compare_version_{project.project_id}",
        )
        st.caption("선택한 저장본이 실제 이전에 제출해 적합통보를 받은 계획서인지 확인하세요. 저장된 계획서와 현재 입력한 정보 중 비교 가능한 물질·시설만 비교합니다.")
        try:
            candidates = change_tracking.form2_change_candidates(project, selected_version)
        except (OSError, ValueError, KeyError) as exc:
            st.warning(f"버전 비교를 완료하지 못했습니다: {type(exc).__name__}. 이전 버전을 확인하세요.")
            return
        if not candidates:
            st.caption("비교 가능한 자료에서 물질 추가·시설 추가·시설용량·최대보유량 증가 후보를 찾지 못했습니다. 위치·대표자·도면 변경 등은 직접 확인하세요.")
            return
        selected_index = st.selectbox(
            "확인할 변경내역 후보", range(len(candidates)),
            format_func=lambda idx: f"{candidates[idx]['제목']}: {candidates[idx]['변경 후']}",
            key=f"cap_form02_compare_candidate_{project.project_id}_{selected_version}",
        )
        candidate = candidates[selected_index]
        st.write(f"**변경 전:** {candidate['변경 전']}  **변경 후:** {candidate['변경 후']}")
        st.caption("확인자료: " + candidate["확인자료"])
        st.warning("비교 결과는 변경사실의 후보일 뿐입니다. 날짜·변경항목·종류·후속조치는 담당자가 실제 자료로 확인하고 작성하세요.")
        if st.button("확인한 후보를 아래 입력란으로 가져오기", key=f"cap_form02_compare_apply_{project.project_id}"):
            suffix = f"{project.project_id}_{len(f2.change_log_rows(project))}"
            item = candidate["변경항목"]
            st.session_state[f"cap_form02_add_items_{suffix}"] = [item] if item in f2.CHANGE_ITEM_SUGGESTIONS else []
            st.session_state[f"cap_form02_add_item_custom_{suffix}"] = "" if item in f2.CHANGE_ITEM_SUGGESTIONS else item
            st.session_state[f"cap_form02_add_types_{suffix}"] = [candidate["변경의 종류"]] if candidate["변경의 종류"] else []
            st.session_state[f"cap_form02_add_mode_{suffix}"] = "변경 전·후 비교"
            st.session_state[f"cap_form02_add_before_{suffix}"] = candidate["변경 전"]
            st.session_state[f"cap_form02_add_after_{suffix}"] = candidate["변경 후"]
            st.success("입력란으로 가져왔습니다. 변경일·변경의 종류·후속조치·담당자를 확인한 다음 행을 추가하세요.")


def _render_article29_review(key_suffix: str, action_key: str) -> None:
    with st.container(border=True):
        st.markdown("**④에 적은 변경의 영업 관련 후속조치 검토 (시행규칙 제29조)**")
        st.caption("④에 기록한 바로 그 변경이 영업 변경신고·변경허가 대상인지 확인하는 질문입니다. 계획서 자체의 변경제출 여부는 별도로 검토합니다. 답이 확인되지 않으면 ‘확인 전’으로 두세요.")
        data = article29.load_rules()
        observed = observed_source(data["law_key"])
        current = article29.law_ready(data, observed, approved_source_is_current(data["law_key"]))
        if not current:
            st.warning("법령 변경 확인 필요: 제29조 규칙의 승인된 현행 판을 확인하고 규칙 데이터를 재대조하세요. 후보를 제안하지 않습니다.")
            st.link_button("제29조 원문", data["source_url"])
            return
        prefix = f"cap_f2_a29_{key_suffix}_"
        status = st.selectbox(
            "우리 사업장의 유해화학물질 영업 상태", ["미확인", "영업허가", "영업신고"],
            key=prefix + "status",
            help="유해화학물질 영업허가증 또는 영업신고증으로 확인하세요. 화학사고예방관리계획서 제출 여부와는 다른 정보입니다.",
        )
        st.caption("영업허가증·영업신고증을 확인해 선택합니다. 영업 형태가 미확인이면 변경신고·변경허가 후보를 제시하지 않습니다.")
        labels = st.multiselect("변경사항(해당하는 항목 모두 선택)", list(ARTICLE29_EVENTS.values()), key=prefix + "events")
        events = [key for key, label in ARTICLE29_EVENTS.items() if label in labels]
        facts = {}

        def yes_no(field: str, label: str) -> None:
            value = st.selectbox(label, ["확인 전", "예", "아니요"], key=prefix + field)
            facts[field] = {"예": True, "아니요": False}.get(value)

        def ratio(field: str, title: str) -> None:
            st.caption(title + " — 최초 허가·신고 또는 최근 변경허가·변경신고 시점의 총량과 변경 후 총량을 같은 단위로 입력하세요.")
            left, right = st.columns(2)
            before = left.text_input("기준 총량", key=prefix + field + "_before")
            after = right.text_input("변경 후 총량", key=prefix + field + "_after")
            try:
                facts[field] = article29.cumulative_ratio(float(before) if before else None, float(after) if after else None)
            except ValueError:
                facts[field] = None
            if before and facts[field] is None:
                st.warning("기준 총량은 0보다 커야 하며 양쪽에 숫자를 입력해야 합니다.")
            elif facts[field] is not None:
                st.caption(f"누적 증가율: {facts[field]:.1%}")

        if "facility" in events:
            yes_no("same_site", "동일 사업장 내 변경인가요?")
            yes_no("cap_submission", "변경된 화학사고예방관리계획서 제출이 필요한가요?")
            if facts["cap_submission"] is not True:
                yes_no("boundary_or_other", "신설·증설·부지 경계로 위치 변경 또는 취급물질 변경에 해당하나요?")
                yes_no("scenario_amount", "변경 후 취급량이 사고시나리오 규정량 이상인가요?")
                yes_no("impact_expanded", "총괄영향범위가 확대되나요?")
        if "material" in events:
            st.markdown("**물질을 추가하거나 취급량을 늘린 경우**")
            st.caption("예: 기존 물질 A만 취급하다 B도 취급하게 되었다면 ④에 ‘B 추가, 변경 후 취급량 ○○ kg’이라고 적습니다. 물질명·CAS 번호와 수량은 물질목록, 공급자 SDS, 시설별 자료에서 확인하세요. 아래 답은 바로 그 B 추가 건에 관한 것입니다.")
            if status == "영업허가":
                yes_no("transport", "허가증의 영업구분이 ‘유해화학물질 운반업’인가요?")
                st.caption("예: 허가증의 영업구분이 ‘운반업’이면 ‘예’. 제조업 허가만 있고 운송을 외부 업체에 맡긴다면 이 질문에는 ‘아니요’. 허가증을 못 봤다면 ‘확인 전’. 탱크로리를 쓴다는 사실만으로 운반업이라고 판단하지 마세요(「화학물질관리법」 제27조제4호).")
                yes_no("trial", "이번 물질 변경이 시장출시와 직접 관계없는 60일 이내의 일시적인 시범생산인가요?")
                st.caption("예: 판매·출시와 무관한 시험을 위해 B를 30일만 한시적으로 사용하고 다시 원래 물질로 돌아가는 계획이 확인되면 ‘예’. 정규 제품 생산을 위해 B를 계속 사용한다면 ‘아니요’. 목적·기간이 불명확하면 ‘확인 전’. 시범생산 계획서로 확인하세요.")
                st.caption("**수량 구간 예시(가상값)**: B의 최하위 기준이 100 kg, 하위 기준이 1,000 kg이라고 가정합니다. 변경 후 취급량이 50 kg이면 ‘최하위 미만’, 500 kg이면 ‘최하위 이상·하위 미만’, 1,200 kg이면 ‘하위 이상’입니다. 실제 기준량은 B의 규정수량 표에서 찾아 같은 단위로 비교하세요.")
                value = st.selectbox("변경 후 이 물질의 취급량은 어느 구간인가요?", ["확인 전", "최하위 미만", "최하위 이상·하위 미만", "하위 이상"], key=prefix + "quantity_band", help="최하위 미만: 최하위 기준보다 적음 / 최하위 이상·하위 미만: 두 기준 사이 / 하위 이상: 하위 기준에 도달하거나 초과. 정확한 기준량과 단위는 해당 물질의 규정수량 표에서 확인하세요.")
                facts["quantity_band"] = {"최하위 미만": "below_minimum", "최하위 이상·하위 미만": "minimum_to_lower", "하위 이상": "lower_or_above"}.get(value)
            elif status == "영업신고":
                st.caption("영업신고 사업자는 해당 물질의 **변경 후 최대보유량**을 최하위·하위 규정수량과 비교합니다. 취급량 입력값을 그대로 사용하지 말고 별지 제1호와 시설별 최대보유량 자료를 확인하세요.")
                st.caption("예(가상값): B의 최하위가 100 kg, 하위가 1,000 kg이고 시설별 B의 변경 후 최대보유량이 500 kg이라면 ‘최하위 이상·하위 미만’을 고릅니다. 수량을 모르면 ‘확인 전’으로 둡니다.")
                value = st.selectbox("변경 후 이 물질의 최대보유량은 어느 구간인가요?", ["확인 전", "최하위 미만", "최하위 이상·하위 미만", "하위 이상"], key=prefix + "holding_band", help="규정수량 표에서 해당 물질의 최하위·하위 기준량을 확인하세요. 비교할 수 없다면 ‘확인 전’을 유지하세요.")
                facts["holding_band"] = {"최하위 미만": "below_minimum", "최하위 이상·하위 미만": "minimum_to_lower", "하위 이상": "lower_or_above"}.get(value)
            st.page_link("ui/legal_evidence_page.py", label="규정수량 원문을 법령·근거 라이브러리에서 확인", icon="📚")
        if "storage_capacity" in events and status == "영업신고":
            kind = st.selectbox("증가한 시설 종류", ["확인 전", "보관·저장시설", "운반시설"], key=prefix + "storage_kind")
            facts["storage_kind"] = {"보관·저장시설": "storage", "운반시설": "transport"}.get(kind)
        if "storage_capacity" in events or "vehicle" in events:
            ratio("storage_ratio", "보관·저장시설 또는 운반시설 총용량 누적 증가")
        if "vehicle" in events:
            yes_no("vehicle_capacity_increased", "운반시설 용량이 증가했나요?")
            ratio_value = facts.get("storage_ratio")
            facts["capacity_threshold_applies"] = (facts["vehicle_capacity_increased"] and ratio_value >= 0.5) if facts["vehicle_capacity_increased"] is not None and ratio_value is not None else (False if facts["vehicle_capacity_increased"] is False else None)
        if "holding_total" in events:
            ratio("holding_ratio", "사업장 유해화학물질별 최대보유량 합계 누적 증가")
        if "trial" in events:
            yes_no("market_unrelated", "시장출시와 직접적인 관계가 없나요?")
            yes_no("temporary_material", "취급물질이 일시적으로 바뀌나요?")
            raw_days = st.text_input("시범생산 기간(일)", key=prefix + "trial_days")
            try:
                facts["trial_days"] = int(raw_days) if raw_days else None
            except ValueError:
                facts["trial_days"] = None
            yes_no("scenario_amount", "변경 후 취급량이 사고시나리오 규정량 이상인가요?")
        if status == "영업신고" and any(e in events for e in ("site", "material", "storage_capacity", "holding_total")):
            yes_no("permit_transition", "변경 후 시행규칙 제27조제1항 영업허가 대상이 되나요? (제29조제8항)")

        result = article29.assess(status, events, facts, data=data, law_current=current)
        if result["missing"]:
            st.warning("확인 필요: " + " · ".join(result["missing"]))
        for rule in result["candidates"]:
            st.info(f"후속조치 {'후보' if not result['missing'] else '검토 중'}: {rule['action']}\n\n"
                    f"근거: 「화학물질관리법 시행규칙」 {rule['clause']}\n\n"
                    f"판단근거: {rule['reason']}\n\n제출시기: {rule['due']}")
        if result["state"] == "별도 검토":
            st.caption("입력한 조건에 맞는 제29조 후보가 없습니다. 다른 조문 및 사업장 사실을 확인하세요.")
        if result["state"] == "후보 제안":
            selected = st.multiselect("실제 후속조치에 반영할 후보", sorted({r['action'] for r in result['candidates']}), key=prefix + "apply")
            if st.button("확인한 후보를 ⑤ 후속조치에 반영", key=prefix + "confirm"):
                if selected:
                    mapping = {"변경신고": "㈐ 변경신고", "변경허가": "㈑ 변경허가"}
                    existing = [a for a in st.session_state.get(action_key, []) if a != "해당없음"]
                    st.session_state[action_key] = list(dict.fromkeys(existing + [mapping[x] for x in selected]))
                    st.success("선택한 후보를 입력란에 옮겼습니다. 변경내역 행 추가 시 최종 저장됩니다.")
                else:
                    st.warning("반영할 후보를 선택하세요.")
        st.link_button("제29조 법령 원문 확인", data["source_url"])

def _render_structured_change_entry(project) -> bool:
    existing_count = len(f2.change_log_rows(project))
    key_suffix = f"{project.project_id}_{existing_count}"
    added = False
    with st.expander("변경내역을 항목별로 입력해 행 추가", expanded=True):
        st.caption("입력한 내용은 법정 서식의 각 열에 배치됩니다. 제29조 검토는 확인한 조건으로만 후보를 제시합니다.")
        date_value = st.text_input("① 변경일", placeholder="예: 2020. 1. 2.", key=f"cap_form02_add_date_{key_suffix}")
        selected_items = st.multiselect(
            "② 변경항목", f2.CHANGE_ITEM_SUGGESTIONS,
            key=f"cap_form02_add_items_{key_suffix}",
            help="자주 쓰는 계획서 세부 항목입니다. 여러 항목을 고를 수 있고, 목록에 없으면 아래 칸에 입력하세요.",
        )
        custom_item = st.text_input(
            "목록에 없는 변경항목 (선택)", key=f"cap_form02_add_item_custom_{key_suffix}"
        ).strip()
        item_value = " / ".join([*selected_items, *([custom_item] if custom_item else [])])
        change_types = st.multiselect(
            "③ 변경의 종류", f2.CHANGE_TYPES, key=f"cap_form02_add_types_{key_suffix}"
        )
        content_mode = st.radio(
            "④ 변경 내용 입력 방식", ["변경 전·후 비교", "문장으로 작성"], horizontal=True,
            key=f"cap_form02_add_mode_{key_suffix}",
        )
        if content_mode == "변경 전·후 비교":
            before_col, after_col = st.columns(2)
            before = before_col.text_input("변경 전", key=f"cap_form02_add_before_{key_suffix}")
            after = after_col.text_input("변경 후", key=f"cap_form02_add_after_{key_suffix}")
            content = f"{before.strip()} → {after.strip()}" if before.strip() and after.strip() else ""
        else:
            content = st.text_area(
                "변경 내용", placeholder="예: TK-101을 철거하고 TK-201을 설치함.",
                key=f"cap_form02_add_narrative_{key_suffix}",
            ).strip()

        action_key = f"cap_form02_add_actions_{key_suffix}"
        _render_article29_review(key_suffix, action_key)
        st.markdown("**⑤ 후속조치 = ④에 적은 변경에 대해 실제로 한 일**")
        st.caption("예: ④ ‘도면번호 P-101을 P-102로 정정, 시설은 그대로’ / ⑤ 변경제출·영업절차 대상이 아님을 확인하고 도면을 정정·관리했다면 ‘변경관리’. ④ ‘물질 B 추가’라면 수량·영업구분을 확인한 뒤 해당 조치를 정하세요. 제29조 검토 후보만으로 신고·허가가 완료됐다고 기록하지 마세요. 아직 판단하지 못했다면 비워 두고 제출 전에 확인하세요.")
        actions = st.multiselect(
            "⑤ 후속조치", f2.FOLLOW_UPS, key=action_key,
            help="계획서 조치와 영업허가 조치가 함께 해당할 수 있습니다. 해당없음은 다른 조치와 함께 선택하지 마세요. 아직 판단 중이면 비워 두고, 제출 전에는 확인해 입력하세요.",
        )
        action_dates = {}
        dated_actions = [action for action in actions if action != "해당없음"]
        if dated_actions:
            st.caption("실제로 조치한 날짜를 입력하세요. 아직 조치하지 않았거나 날짜를 확인 중이면 비워 둘 수 있습니다.")
            for action in dated_actions:
                action_dates[action] = st.text_input(
                    f"{action.split(' ', 1)[-1]} 일자 (선택)",
                    placeholder="예: 2020. 3. 7.",
                    key=f"cap_form02_add_action_date_{key_suffix}_{action}",
                )
        person = st.text_input("⑥ 담당자", key=f"cap_form02_add_person_{key_suffix}")
        st.caption("저장 전 확인: 이 대장은 변경사실과 조치를 함께 기록합니다. 계획서 변경제출, 내부 변경관리, 영업 변경신고·변경허가는 별도로 검토하세요. 프로그램 제안은 확인된 입력자료의 후보이며 미확인 사항은 추정하지 않습니다. 실제 인허가 상태와 변경내용을 확인한 담당자가 최종 결정합니다.")
        submitted = st.button("변경내역 행 추가", type="primary", key=f"cap_form02_add_button_{key_suffix}")

        if submitted:
            errors = []
            if not date_value.strip():
                errors.append("변경일을 입력하세요.")
            if not item_value.strip():
                errors.append("변경항목을 입력하거나 선택하세요.")
            if not change_types:
                errors.append("변경의 종류를 하나 이상 선택하세요.")
            if not content:
                errors.append("변경 전·후 값 또는 변경 내용을 입력하세요.")
            if "해당없음" in actions and len(actions) > 1:
                errors.append("‘해당없음’은 다른 후속조치와 함께 선택할 수 없습니다.")
            if errors:
                for error in errors:
                    st.error(error)
            else:
                rows = f2.change_log_rows(project)
                rows.append({
                    "일자": date_value.strip(),
                    "변경항목": item_value.strip(),
                    "변경의 종류": " / ".join(change_types),
                    "변경 내용(변경전 → 변경후)": content,
                    "후속조치": f2.format_follow_up_actions(actions, action_dates),
                    "담당자": person.strip(),
                })
                f2.save_change_log(project, rows)
                save_project(project)
                st.session_state[f"cap_form02_added_notice_{project.project_id}"] = "변경내역을 법정 서식 표에 추가했습니다."
                added = True
    return added


def render(project) -> None:
    schema = ws.load_form_schema(2)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form02_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    current = f2.submission(project)

    if step["id"] == "submission":
        st.text_input("사업장명", value=current["company"], disabled=True,
                      help="판정진단에서 승계된 값입니다.")
        unit_plant = st.text_input(
            "단위공장명(또는 단위공정명)", value=current["unit_plant"], key=f"cap_form02_unit_{project.project_id}",
            help="별지 제3호의 단위공장명 칸에도 그대로 들어갑니다.",
        )
        types = [""] + list(f2.SUBMISSION_TYPES)
        submission_type = st.selectbox(
            "제출구분", types, index=types.index(current["type"]) if current["type"] in types else 0,
            key=f"cap_form02_type_{project.project_id}", help="별지 제3호의 제출구분 칸에도 그대로 들어갑니다.",
        )
        reasons = [""] + list(f2.SUBMISSION_REASONS)
        reason = st.selectbox(
            "제출 사유", reasons, index=reasons.index(current["reason"]) if current["reason"] in reasons else 0,
            key=f"cap_form02_reason_{project.project_id}",
        )
        if st.button("저장", type="primary", key=f"cap_form02_save_sub_{project.project_id}"):
            f2.save_submission(project, submission_type, reason, unit_plant)
            save_project(project)
            st.success("저장했습니다. 다른 서식의 같은 칸에도 반영됩니다.")
        state = f2.resolve_form2(project)
        (st.info if state.applies is None else st.success if state.applies else st.warning)(state.headline)

    elif step["id"] == "log":
        state = f2.resolve_form2(project)
        if state.applies is False:
            st.warning(state.headline + " 아래 표는 건너뛰어도 됩니다.")
        _render_change_guide()
        notice_key = f"cap_form02_added_notice_{project.project_id}"
        if st.session_state.pop(notice_key, None):
            st.success("변경내역을 법정 서식 표에 추가했습니다.")
        _render_version_change_candidates(project)
        if _render_structured_change_entry(project):
            st.rerun()
        st.subheader("등록된 변경내역")
        st.caption("위 입력창에서 추가한 내역입니다. 세부 수정이나 행 삭제는 아래 표에서 할 수 있습니다.")
        columns = ws.section(2, "change_log")["columns"]
        ids = [c["id"] for c in columns]
        frame = pd.DataFrame(f2.change_log_rows(project), columns=ids)
        edited = st.data_editor(
            frame, column_config=_column_config(columns), num_rows="dynamic", width="stretch",
            key=f"cap_form02_log_{project.project_id}",
        )
        st.caption("저장 전 확인: 표에서 직접 수정한 후속조치도 회사의 실제 인허가 상태·변경내용과 대조한 뒤 담당자가 확정하세요.")
        if st.button("변경내역 저장", type="primary", key=f"cap_form02_save_log_{project.project_id}"):
            rows = []
            for record in edited.to_dict("records"):
                cleaned = {}
                for key, value in record.items():
                    if value is None or (isinstance(value, float) and pd.isna(value)):
                        cleaned[key] = ""
                    else:
                        cleaned[key] = value
                rows.append(cleaned)
            saved = f2.save_change_log(project, rows)
            save_project(project)
            st.success(f"변경내역 {saved}건을 저장했습니다.")

    else:
        state = f2.resolve_form2(project)
        st.write(state.headline)
        for blocker in state.readiness.blockers:
            st.error(blocker)
        for message in state.readiness.messages:
            st.caption(message)
        with st.expander("별지 제2호에 채워지는 내용 미리보기", expanded=True):
            st.write(f"**사업장명**: {current['company'] or '-'}    **단위공장명**: {current['unit_plant'] or '-'}")
            if state.applies:
                frames.show(pd.DataFrame(f2.change_log_rows(project)), width="stretch", hide_index=True)
            else:
                st.caption("작성 대상이 아니어서 표는 비워 둡니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form02_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
