from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_site_lookup as lookup
from engine.stage2 import cap_vworld_lookup as vworld
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
    st.info(
        "**왜 작성하나요?** 사업장 가까이에 사람이 이용하는 시설과 환경수용체가 무엇이 있는지 확인하고, "
        "사고 시 영향을 검토할 수 있도록 위치와 거리를 기록하는 서식입니다."
    )
    with st.expander("이 서식을 처음 작성한다면: 작성 순서와 예시", expanded=True):
        st.markdown(
            "1. **사업장 경계부터 500m 범위를 확인합니다.** 사업장 주소 한 점이 아니라 실제 부지 경계를 기준으로 지도나 GIS에서 살펴보세요.\n"
            "2. **후보를 찾습니다.** 화면의 자동검색은 출발점입니다. 지도·GIS와 필요하면 현장 자료로 학교, 병원, 주택, 하천 등 빠진 곳을 확인하세요.\n"
            "3. **대상별로 분류하고 거리를 적습니다.** 예를 들어 학교가 검색되면 실제 위치와 해당 분류를 확인하고, 사업장 경계에서 학교까지의 거리를 측정해 목록에 적습니다. 주소점에서 나온 검색거리는 그대로 옮기지 않습니다.\n"
            "4. **지도와 목록을 대조합니다.** 목록의 일련번호를 지도에도 표시하고, 사용한 지도·확인일·측정 방법을 기록한 뒤 500m 전체를 다시 확인하세요."
        )
        st.caption(
            "검색 결과가 없거나 모두 500m 밖에 있어도 '보호대상 없음'으로 바로 확정할 수 없습니다. "
            "경계 기준 500m 전체를 확인하고 근거를 남겨야 합니다."
        )

    with st.expander("자동검색은 어떻게 작동하나요?"):
        st.write(
            "사업장 주소를 카카오 주소 API로 좌표로 바꾸고(카카오 키가 없거나 주소 검색에 실패하면 브이월드 주소 API 사용), "
            f"그 좌표에서 반경 {lookup.SEARCH_RADIUS_M}m의 후보를 찾습니다. "
            "카카오는 등록된 장소 검색을 한 검색당 최대 45건 조회합니다. 브이월드 2D 데이터 API는 도로명주소 건물과 하천망, "
            "습지·자연공원·산림·상수원 보호구역 등의 공간정보를 조회합니다. "
            "OpenStreetMap의 시설·상점·관광지·자연환경 지도 객체도 더합니다. "
            "검색된 정보는 분류하지 않고 출처와 주소점 기준 거리를 함께 보여 줍니다."
        )
        st.warning(
            "화면의 검색거리는 주소 좌표 기준 참고값입니다. 사업장 경계부터의 실제 거리, "
            "보호대상 해당 여부, 원천 데이터에 없는 시설과 페이지 제한에 따른 검색 누락은 프로그램이 확인하지 못합니다. "
            "검색되지 않은 곳도 지도·GIS 또는 현장 자료로 확인하세요."
        )

    with st.expander("법정 서식과 분류 기준 원문 확인"):
        manifest_path = Path(__file__).resolve().parents[1] / "data/stage2/cap_authoritative_sources.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        legal = manifest["legal_structure"]
        st.markdown(
            "- [「화학사고예방관리계획서 작성 등에 관한 규정」 별지 제8호 「사업장 주변 환경 정보」]("
            + FORM8_SOURCE_URL + "): 사업장 경계선 기준 500m 입지 현황, 보호대상 목록, 거리와 지도 일련번호.\n"
            "- [같은 규정 별표 4 「보호대상」](" + RULES_SOURCE_URL
            + "): 갑종·을종 보호대상 및 환경수용체의 세부 분류.\n"
            "- [「유해화학물질 취급시설 외벽으로부터 보호대상까지의 안전거리 고시」 별표 2·3]("
            + SAFETY_DISTANCE_NOTICE_URL + "): 해당하는 보호대상의 세부 기준을 확인할 때 함께 대조할 자료."
        )
        st.caption(
            f"프로그램이 반영한 기준본: {legal['title']} · {legal['notice']} · "
            f"시행 기준일 {legal['effective_date']} · 작성 매뉴얼 "
            f"{manifest['writing_guidance']['document_code']} p.47–48. "
            "제출 전 최신 법령과 매뉴얼을 다시 확인하세요."
        )
        st.caption(
            "별지의 지도상 일련번호 표기는 자동 생성되지 않습니다. 지도를 별도로 작성·첨부하고 "
            "목록·거리·확인 근거와 맞는지 검토하세요."
        )


def _render_classification_guide() -> None:
    with st.expander("검색 결과를 갑종·을종·환경수용체로 어떻게 구분하나요?", expanded=True):
        st.write(
            "먼저 지도에서 무엇인지 확인한 뒤 아래 순서대로 보세요. 검색된 이름만으로 결정할 수 없으면 "
            "해당 시설의 용도·규모 또는 법정 지정 여부를 확인하고 나서 목록에 입력합니다."
        )
        st.markdown(
            "| 확인 순서 | 알아볼 것 | 예와 추가 확인 사항 |\n"
            "| --- | --- | --- |\n"
            "| 1. 자연·토지인가요? | 환경수용체 해당 여부 | 하천은 **국가하천·지방하천인지**, 농지는 농지법상 농지인지, 산지는 산지관리법상 산지인지 확인합니다. 지도에 그려진 물길이나 녹지만으로 확정하지 않습니다. |\n"
            "| 2. 사람이 이용하는 건물·시설인가요? | 갑종 유형과 조건부터 확인 | 학교·도서관·연구소, 병원·의원은 별표 4의 해당 유형을 확인합니다. 교회는 **300명 이상 수용** 여부, 어린이집·노인복지시설 등은 **20명 이상 수용** 여부를 확인합니다. |\n"
            "| 3. 갑종으로 확인되지 않나요? | 을종 유형과 조건 확인 | 단독주택·일정 규모 미만 공동주택, 근린생활시설, 주유소·가스충전소 등은 별표 4의 을종 항목과 대조합니다. 공동주택의 **300명 이상 수용** 여부 등 갑종과 겹치는 조건을 먼저 확인합니다. |\n"
            "| 4. 확인할 정보가 모자라나요? | 보류하고 자료 확인 | 예: '아파트'라는 지도 이름만으로 수용 인원을 알 수 없습니다. 실제 용도·수용 인원·면적 또는 지정 현황을 확인한 다음 구분합니다. |"
        )
        st.caption(
            "예시는 분류 방법을 설명합니다. 별지 제8호의 환경수용체 체크항목에는 자연공원·습지보호지역 등도 있지만, "
            "「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4의 환경수용체 표에는 "
            "생태·경관보호지역, 국가하천·지방하천, 농지·산지가 명시되어 있습니다. "
            "서식 항목 이름과 별표 4의 법정 정의를 함께 대조하세요."
        )
        st.markdown("[「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」 원문](https://www.law.go.kr/flDownload.do?bylClsCd=200201&flNm=%5B%EB%B3%84%ED%91%9C+4%5D+%EB%B3%B4%ED%98%B8%EB%8C%80%EC%83%81%28%EC%A0%9C2%EC%A1%B0+%EB%B0%8F+%EC%A0%9C24%EC%A1%B0+%EA%B4%80%EB%A0%A8%29&flSeq=164152403)")


def render(project) -> None:
    schema = ws.load_form_schema(8)
    steps = schema["steps"]
    titles = [step["title"] for step in steps]
    st.header(schema["title"])
    _render_methodology()
    choice = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form08_step")
    step = steps[titles.index(choice)]
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])

    if step["id"] == "search":
        candidate_key = f"{CAND_KEY}_{project.project_id}"
        addr = f8.address(project)
        st.markdown(f"**사업장 주소(별지 제3호):** {addr or '아직 없음 — 별지 제3호에서 입력하세요'}")
        if not lookup.api_key() and not vworld.api_key():
            st.info(f"{lookup.ENV_KEY} 또는 {vworld.ENV_KEY}가 없어 자동 검색을 쓸 수 없습니다. 다음 단계에서 보호대상을 직접 입력하세요.")
            with st.expander("키를 못 찾는 이유 확인하기"):
                st.caption("프로그램이 키를 어디에서 찾았는지 보여 줍니다(키 값은 표시하지 않습니다).")
                for line in lookup.env_diagnosis():
                    st.write("• " + line)
                st.caption("브이월드 인증키는 프로젝트 .env 파일의 VWORLD_API_KEY 또는 기존 v_world_key로 읽습니다. 키 값은 화면에 표시하지 않습니다.")
                st.caption(".env 파일을 고쳤다면 프로그램을 완전히 껐다가 다시 실행해야 새 값을 읽습니다.")
        if vworld.api_key() and not lookup.api_key():
            st.info("카카오 키가 없어 시설·장소 검색은 생략합니다. 브이월드와 OpenStreetMap 환경 후보는 조회할 수 있습니다.")
        if (lookup.api_key() or vworld.api_key()) and st.button("주소로 주변 시설·환경 후보 찾기", type="primary", disabled=not addr, key=f"cap_form08_search_{project.project_id}"):
            with st.spinner("주변 시설과 환경 지도 자료를 조회하는 중입니다..."):
                found, message = lookup.find_combined_candidates(addr)
            st.session_state[candidate_key] = [f8.candidate_row(c) for c in found]
            st.session_state[candidate_key + "_msg"] = message
            st.session_state[candidate_key + "_address"] = addr
        same_address = st.session_state.get(candidate_key + "_address") == addr
        if same_address and st.session_state.get(candidate_key + "_msg"):
            st.caption(st.session_state[candidate_key + "_msg"])
        if not same_address and st.session_state.get(candidate_key):
            st.info("사업장 주소가 변경되었습니다. 주변 장소 후보를 다시 검색해 주세요.")
        candidates = (st.session_state.get(candidate_key) or []) if same_address else []
        if candidates:
            st.caption(f"검색된 공간정보 {len(candidates)}건입니다. 구분·유형 후보는 검색 자료로 추정할 수 있을 때만 표시하며 확정 판정이 아닙니다. 빈칸은 확인 후 목록 단계에서 분류하세요.")
            page_size = 100
            page_count = (len(candidates) + page_size - 1) // page_size
            page = st.number_input("후보 목록 페이지", min_value=1, max_value=page_count, value=1,
                                   key=f"cap_form08_page_{project.project_id}") if page_count > 1 else 1
            start = (page - 1) * page_size
            page_rows = candidates[start:start + page_size]
            frame = pd.DataFrame([{
                "목록에 추가": False,
                "장소명": row["보호대상 명칭"],
                "구분 후보": row["보호대상 구분"],
                "유형 후보": row["세부유형"],
                "주소·위치": row["주소·위치"],
                "주소점 거리(m)": row["검색결과 거리(주소점 기준, 참고)"],
                "검색 출처": row["검색 출처·검색일"],
            } for row in page_rows])
            edited = st.data_editor(frame, hide_index=True, width="stretch", key=f"cap_form08_cand_{project.project_id}_{page}",
                                    disabled=[c for c in frame.columns if c != "목록에 추가"])
            if st.button("선택한 후보를 목록에 추가", key=f"cap_form08_add_{project.project_id}"):
                chosen = [page_rows[i] for i, selected in enumerate(edited["목록에 추가"]) if selected]
                f8.save(project, f8.saved_rows(project) + chosen, no_target=False, status="HOLD")
                st.session_state[f"cap_form08_scope_reviewed_{project.project_id}"] = False
                save_project(project)
                st.success(
                    f"{len(chosen)}건을 미검토 후보로 저장했습니다. 주소점 기준 검색거리는 참고란에만 들어가며, "
                    "사업장 경계 기준 거리는 비워 두었습니다. 목록 단계에서 확인 후 입력하세요."
                )
    elif step["id"] == "list":
        _render_classification_guide()
        no_target = st.checkbox("사업장 경계 500m 안에 보호대상이 없습니다", value=f8.declared_no_target(project),
                                key=f"cap_form08_none_{project.project_id}")
        rows_source = f8.saved_rows(project)
        evidence = ""
        edited_rows: list[dict] = []
        scope_reviewed = st.checkbox(
            "지도·GIS 또는 현장 자료로 사업장 경계선 기준 500m 전체를 살펴보고 보호대상 누락 여부를 검토했습니다.",
            value=f8.scope_reviewed(project), key=f"cap_form08_scope_reviewed_{project.project_id}",
            help="분류는 「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4를 확인하세요. 해당 시설의 세부 기준은 안전거리 고시 별표 2·3도 대조하세요.",
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
                    help="카카오·브이월드·공개 지도가 사업장 주소 좌표에서 반환하거나 계산한 참고값입니다. 법정 거리로 사용할 수 없습니다."),
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
