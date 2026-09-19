from __future__ import annotations

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_site_lookup as lookup
from engine.stage2 import cap_workspace as ws
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project

CAND_KEY = "cap_form08_candidates"


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

    if step["id"] == "search":
        addr = f8.address(project)
        st.markdown(f"**사업장 주소(별지 제3호):** {addr or '아직 없음 — 별지 제3호에서 입력하세요'}")
        if not lookup.api_key():
            st.info(f"{lookup.ENV_KEY}가 없어 자동 검색을 쓸 수 없습니다. 다음 단계에서 보호대상을 직접 입력하세요.")
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
                f8.save(project, f8.saved_rows(project) + chosen, no_target=False)
                save_project(project)
                st.success(f"{len(chosen)}건을 목록에 추가했습니다. 다음 단계에서 규모·거리를 확인하세요.")
    elif step["id"] == "list":
        no_target = st.checkbox("사업장 경계 500m 안에 보호대상이 없습니다", value=f8.declared_no_target(project),
                                key=f"cap_form08_none_{project.project_id}")
        rows_source = f8.saved_rows(project)
        evidence = ""
        edited_rows: list[dict] = []
        if no_target:
            evidence = st.text_input("확인 근거", key=f"cap_form08_evidence_{project.project_id}",
                                     help="예: 지도 캡처 2026-09-19, 현장 확인")
        else:
            frame = pd.DataFrame(rows_source, columns=list(f8.COLUMNS))
            config = {
                "보호대상 구분": st.column_config.SelectboxColumn("구분", options=list(f8.CATEGORIES),
                                                               help="갑종·을종·환경수용체(별표 4)"),
                "세부유형": st.column_config.SelectboxColumn(
                    "세부유형", options=[o for opts in f8.SUBTYPES.values() for o in opts],
                    help="별표 4의 종류입니다. 규모 조건(예: 300명 이상)이 있는 항목은 아래 도움말을 확인하세요."),
                "사업장 경계와 거리(m)": st.column_config.NumberColumn("경계 기준 거리(m)", min_value=0),
            }
            edited_rows = st.data_editor(frame, column_config=config, num_rows="dynamic", width="stretch",
                                         key=f"cap_form08_rows_{project.project_id}").to_dict("records")
            hints = {f"{r.get('보호대상 구분')}/{r.get('세부유형')}": f8.type_hint(str(r.get("보호대상 구분")), str(r.get("세부유형")))
                     for r in edited_rows}
            for label, hint in hints.items():
                if hint:
                    st.caption(f"별표 4 · {hint}")
        if st.button("보호대상 저장", type="primary", key=f"cap_form08_save_{project.project_id}"):
            saved = f8.save(project, [{k: ("" if pd.isna(v) else v) for k, v in r.items()} for r in edited_rows],
                            no_target, evidence)
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
            st.success("모든 칸이 채워졌습니다.")
        try:
            st.download_button(
                "화학사고예방관리계획서 규정서식 작성본 DOCX 다운로드",
                data=build_cap_baseline_draft(project), file_name=cap_baseline_filename(project),
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"cap_form08_download_{project.project_id}",
            )
        except Exception as exc:
            st.error(f"규정서식 작성본을 만들지 못했습니다: {type(exc).__name__}: {exc}")
