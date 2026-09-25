from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_site_lookup as lookup
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project

CAND_KEY = "cap_form08_candidates"
FORM8_SOURCE_URL = (
    "https://www.law.go.kr/flDownload.do?bylClsCd=200203&"
    "flNm=%5B%EB%B3%84%EC%A7%80+8%5D+%EC%82%AC%EC%97%85%EC%9E%A5+"
    "%EC%A3%BC%EB%B3%80+%ED%99%98%EA%B2%BD+%EC%A0%95%EB%B3%B4&flSeq=164152315"
)
RULES_SOURCE_URL = "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000278102&chrClsCd=010201"
SAFETY_DISTANCE_NOTICE_URL = "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000266498"


def _render_methodology() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "data/stage2/cap_authoritative_sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legal = manifest["legal_structure"]
    with st.expander("작성 기준과 검색 방법·근거", expanded=True):
        st.markdown(
            "**법정 서식 기준**  "
            "별지 제8호는 사업장 경계선 바깥 500m 범위의 입지 현황, 보호대상 종류, "
            "사업장 경계선부터 대상까지의 거리와 대상 위치를 일련번호로 표시한 지도를 요구합니다. "
            "종류별 구분·세부 기준은 [「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」](" + RULES_SOURCE_URL + ")와 "
            "별지 주석이 인용하는 [「유해화학물질 취급시설 외벽으로부터 보호대상까지의 안전거리 고시」 별표 2·3](" + SAFETY_DISTANCE_NOTICE_URL + ")에서 확인합니다. "
            "서식 원문: [별지 제8호 「사업장 주변 환경 정보」](" + FORM8_SOURCE_URL + ")."
        )
        st.markdown(
            f"**저장소가 반영한 기준본**  {legal['title']} · {legal['notice']} · "
            f"시행 기준일 {legal['effective_date']} · 매뉴얼 {manifest['writing_guidance']['document_code']} p.47–48"
        )
        st.warning(
            "이 날짜는 저장소에 고정된 기준본의 시행일입니다. 이후 개정이 반영됐는지 제출 전에 "
            "국가법령정보센터와 최신 화학물질안전원 매뉴얼에서 확인하세요."
        )
        st.markdown(
            "**프로그램의 검색 방법**  사업장 주소를 카카오 주소 API로 좌표 변환한 뒤, "
            f"코드에 등록된 {len(lookup.SEARCHES)}개 카테고리·키워드 검색을 좌표 반경 "
            f"{lookup.SEARCH_RADIUS_M}m에서 실행합니다. 각 검색은 최대 15건을 요청하고 거리순 후보를 보여 줍니다."
        )
        st.error(
            "검색 반경은 사업장 주소 좌표 기준이며 법정 500m 경계 기준 측정값이 아닙니다. "
            "검색 분류·키워드에서 빠진 대상, 별표 기준의 세부 규모 조건, 실제 사업장 경계와 거리, "
            "검색 누락을 확인하지 않습니다. 검색 결과가 없다는 것은 보호대상이 없다는 뜻이 아닙니다."
        )
        st.caption(
            "자동검색은 후보 수집 보조입니다. 이 프로그램은 별표 4 및 안전거리 고시 별표 2·3에 따른 대상 여부, 지도 전체의 누락 여부, "
            "거리 산정의 적정성 또는 제출 적합성을 독립적으로 판정하거나 보증하지 않습니다. "
            "별지의 지도상 일련번호 위치 표기도 자동 생성하지 않으므로 지도는 별도로 작성·첨부해야 합니다. "
            "확인 자료와 방법을 GIS/현장 근거에 남기고 담당자가 원문 기준과 대조하세요."
        )


def render(project) -> None:
    schema = ws.load_form_schema(8)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form08_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])
    _render_methodology()

    if step["id"] == "search":
        addr = f8.address(project)
        st.markdown(f"**사업장 주소(별지 제3호):** {addr or '아직 없음 — 별지 제3호에서 입력하세요'}")
        if not lookup.api_key():
            st.info(f"{lookup.ENV_KEY}가 없어 자동 검색을 쓸 수 없습니다. 다음 단계에서 보호대상을 직접 입력하세요.")
            with st.expander("키를 못 찾는 이유 확인하기"):
                st.caption("프로그램이 키를 어디에서 찾았는지 보여 줍니다(키 값은 표시하지 않습니다).")
                for line in lookup.env_diagnosis():
                    st.write("• " + line)
                st.caption(".env 파일을 고쳤다면 프로그램을 완전히 껐다가 다시 실행해야 새 값을 읽습니다.")
        elif st.button("주변 보호대상 후보 검색", type="primary", disabled=not addr, key=f"cap_form08_search_{project.project_id}"):
            found, message = lookup.find_candidates(addr)
            st.session_state[CAND_KEY] = [f8.candidate_row(c) for c in found]
            st.session_state[CAND_KEY + "_msg"] = message
        if st.session_state.get(CAND_KEY + "_msg"):
            st.caption(st.session_state[CAND_KEY + "_msg"])
        candidates = st.session_state.get(CAND_KEY) or []
        if candidates:
            frame = pd.DataFrame(candidates)
            frame.insert(0, "목록에 추가", False)
            edited = st.data_editor(frame, hide_index=True, width="stretch", key=f"cap_form08_cand_{project.project_id}",
                                    disabled=[c for c in frame.columns if c != "목록에 추가"])
            if st.button("선택한 후보를 목록에 추가", key=f"cap_form08_add_{project.project_id}"):
                chosen = [r for r in edited.to_dict("records") if r.pop("목록에 추가")]
                f8.save(project, f8.saved_rows(project) + chosen, no_target=False, status="PROPOSED")
                st.session_state[f"cap_form08_scope_reviewed_{project.project_id}"] = False
                save_project(project)
                st.success(
                    f"{len(chosen)}건을 미검토 후보로 저장했습니다. 주소점 기준 검색거리는 참고란에만 들어가며, "
                    "사업장 경계 기준 거리는 비워 두었습니다. 목록 단계에서 확인 후 입력하세요."
                )
    elif step["id"] == "list":
        no_target = st.checkbox("사업장 경계 500m 안에 보호대상이 없습니다", value=f8.declared_no_target(project),
                                key=f"cap_form08_none_{project.project_id}")
        rows_source = f8.saved_rows(project)
        evidence = ""
        edited_rows: list[dict] = []
        scope_reviewed = st.checkbox(
            "지도/GIS 또는 현장 자료로 사업장 경계 바깥 500m 전체를 확인했고, 「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」 및 안전거리 고시 별표 2·3 해당 대상의 누락 여부를 검토했습니다.",
            value=f8.scope_reviewed(project), key=f"cap_form08_scope_reviewed_{project.project_id}",
        )
        if no_target:
            evidence = st.text_input("확인 근거", key=f"cap_form08_evidence_{project.project_id}",
                                     help="예: 지도 서비스/레이어, 확인일, 사업장 경계와 검토 범위, 현장 확인 기록")
        else:
            frame = pd.DataFrame(rows_source, columns=list(f8.COLUMNS))
            config = {
                "보호대상 구분": st.column_config.SelectboxColumn("구분", options=list(f8.CATEGORIES),
                                                               help="「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」에 따른 구분입니다. 갑종·을종은 「유해화학물질 취급시설 외벽으로부터 보호대상까지의 안전거리 고시」 별표 2·3도 함께 확인하세요."),
                "세부유형": st.column_config.SelectboxColumn(
                    "세부유형", options=[o for opts in f8.SUBTYPES.values() for o in opts],
                    help="「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」의 분류입니다. 갑종·을종 세부 기준은 안전거리 고시 별표 2·3 원문과 함께 대조하세요."),
                "사업장 경계와 거리(m)": st.column_config.NumberColumn(
                    "사업장 경계 기준 실제 거리(m)", min_value=0,
                    help="법정 서식에 작성할 값입니다. 지도/GIS에서 사업장 경계부터 대상까지 확인해 입력하세요."),
                "검색결과 거리(주소점 기준, 참고)": st.column_config.NumberColumn(
                    "주소점 기준 검색거리(참고)", disabled=True,
                    help="카카오 API가 사업장 주소 좌표에서 반환한 참고값입니다. 법정 거리로 사용할 수 없습니다."),
                "검색 출처·검색일": st.column_config.TextColumn("검색 출처·검색일", disabled=True),
                "500m 범위 전체 확인": st.column_config.CheckboxColumn("500m 범위 전체 확인", disabled=True),
                "거주민수": st.column_config.NumberColumn(
                    "거주민수", min_value=0, help="그 대상에 사는 사람 수입니다. 별지 제12·13호 영향범위 내 주민 수 집계에 쓰입니다(비우면 0)."),
                "근로자수": st.column_config.NumberColumn(
                    "근로자수", min_value=0, help="그 대상에서 일하는 사람 수입니다. 별지 제12·13호 집계에 쓰입니다(비우면 0)."),
            }
            edited_rows = st.data_editor(frame, column_config=config, num_rows="dynamic", width="stretch",
                                         key=f"cap_form08_rows_{project.project_id}").to_dict("records")
            hints = {f"{r.get('보호대상 구분')}/{r.get('세부유형')}": f8.type_hint(str(r.get("보호대상 구분")), str(r.get("세부유형")))
                     for r in edited_rows}
            for label, hint in hints.items():
                if hint:
                    st.caption(f"「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」 · {hint}")
        if not scope_reviewed:
            st.info("전체 500m 범위를 확인했다고 표시해야 저장할 수 있습니다. 자동검색 결과만으로는 이 확인을 대신할 수 없습니다.")
        can_save = scope_reviewed and (not no_target or bool(evidence.strip()))
        if st.button("검토한 보호대상 저장", type="primary", disabled=not can_save,
                     key=f"cap_form08_save_{project.project_id}"):
            saved = f8.save(project, [{k: ("" if pd.isna(v) else v) for k, v in r.items()} for r in edited_rows],
                            no_target, evidence, scope_reviewed=scope_reviewed)
            save_project(project)
            st.success("보호대상 없음으로 저장했습니다." if no_target else f"{saved}건을 저장했습니다.")
    else:
        chosen = f8.selected_options(project)
        for category in f8.CATEGORIES:
            marks = "   ".join(f"{'☒' if o in chosen[category] else '☐'} {o}" for o in f8.SUBTYPES[category])
            st.write(f"**{category} 보호대상** {marks}")
        needs = f8.needs(project)
        if needs:
            st.warning("아직 필요한 정보")
            for item in needs:
                st.write(f"• {item}")
        else:
            st.success("별지 제8호 입력 검증을 통과했습니다. 제출 전 최신 법령·매뉴얼과 원자료를 최종 대조하세요.")
        try:
            st.download_button(
                "별지 제8호 작성 초안 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                disabled=bool(needs),
                key=f"cap_form08_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
