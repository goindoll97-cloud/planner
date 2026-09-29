from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pandas as pd
import streamlit as st

from engine.stage2 import cap_form8_workspace as f8
from engine.stage2 import cap_workspace as ws
from engine.stage2 import storage
from engine.stage2.cap_baseline_docx import build_cap_baseline_draft, cap_baseline_filename
from engine.stage2.storage import save_project

FORM8_SOURCE_URL = (
    "https://www.law.go.kr/flDownload.do?bylClsCd=200203&"
    "flNm=%5B%EB%B3%84%EC%A7%80+8%5D+%EC%82%AC%EC%97%85%EC%9E%A5+"
    "%EC%A3%BC%EB%B3%80+%ED%99%98%EA%B2%BD+%EC%A0%95%EB%B3%B4&flSeq=164152315"
)
RULES_SOURCE_URL = "https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000278102&chrClsCd=010201"
SAFETY_DISTANCE_NOTICE_URL = "https://www.law.go.kr/admRulInfoP.do?admRulSeq=2100000266498"


def _render_manual_map_guide(*, expanded: bool) -> None:
    with st.expander("처음 작성한다면: 어느 지도에서 무엇을 확인하나요?", expanded=expanded):
        st.write(
            "**특정 지도 하나만 사용해야 하는 것은 아닙니다.** 주변 시설을 찾고, 경계·거리와 "
            "자연환경을 확인할 수 있는 자료를 목적에 맞게 대조하세요. 아래 지도는 바로 열어 볼 수 있습니다."
        )
        st.markdown(
            "| 지도 바로 열기 | 여기서 먼저 확인할 것 | 확인 시 주의할 점 |\n"
            "| --- | --- | --- |\n"
            "| [카카오맵](https://map.kakao.com/) | 주소·학교·병원·주택 등 주변 장소명, 항공사진·거리 모습 | 지도에 없는 장소도 있고, 장소명만으로 법정 보호대상 구분은 확정할 수 없습니다. |\n"
            "| [브이월드](https://www.vworld.kr/) | 항공사진·건물·토지 관련 지도에서 사업장 주변 위치와 범위 대조 | 지도에서 보이는 대략적인 경계를 회사의 부지 도면과 대조하세요. |\n"
            "| [국토정보플랫폼 국토정보맵](https://map.ngii.go.kr/ms/map/NlipMap.do) | 지형·항공사진·건물·하천 등 주변 공간 현황 보완 | 표시된 지형·시설 정보가 현재 현장과 일치하는지 확인하세요. |\n"
            "| [환경공간정보서비스](https://aid.mcee.go.kr/) | 토지피복·환경주제도에서 농경지·산림·물환경·보호지역 자료 대조 | 지도상 모양만으로 국가하천·법정 보호지역 등의 지정 여부를 확정하지 마세요. |"
        )
        st.write(
            "**작성 예시:** 사업장 부지 도면으로 경계를 확인하고 → 카카오맵에서 학교·병원을 찾고 → "
            "브이월드나 국토정보맵에서 위치를 대조하고 → 환경공간정보서비스에서 하천·농지 등을 확인합니다. "
            "빠진 대상을 추가한 뒤, 적용되는 기준 범위와 각 대상까지의 거리를 확인해 목록에 적으세요."
        )
        st.caption(
            "지도 서비스마다 최신성·표시 대상이 다를 수 있습니다. 사용한 지도/레이어, 확인일, "
            "사업장 경계와 거리 확인 방법을 기록하고, 법정 분류와 실제 부지 경계는 별도로 검토하세요."
        )


def _render_methodology() -> None:
    st.info(
        "**왜 작성하나요?** 사업장 가까이에 사람이 이용하는 시설과 환경수용체가 무엇이 있는지 확인하고, "
        "사고 시 영향을 검토할 수 있도록 위치와 거리를 기록하는 서식입니다. "
        "이 별지의 시설·환경 목록과 거리는 지도·부지 도면·현장 자료로 확인합니다. "
        "물질 정보가 담긴 MSDS로 주변 환경 조사 결과를 대신할 수 없습니다."
    )
    with st.expander("이 서식을 처음 작성한다면: 작성 순서와 예시", expanded=True):
        st.markdown(
            "1. **사업장 경계부터 500m 범위를 확인합니다.** 사업장 주소 한 점이 아니라 실제 부지 경계를 기준으로 지도나 GIS에서 살펴보세요.\n"
            "2. **지도·기존 자료에서 후보를 찾습니다.** 지도와 필요하면 현장 자료로 학교, 병원, 주택, 하천 등을 확인하세요. 회사에 이전 목록이 있으면 가져와 현재 상태와 대조합니다.\n"
            "3. **대상별로 분류하고 거리를 적습니다.** 예를 들어 학교가 보이면 실제 위치와 해당 분류를 확인하고, 사업장 경계에서 학교까지의 거리를 측정해 목록에 적습니다.\n"
            "4. **지도와 목록을 대조합니다.** 목록의 일련번호를 지도에도 표시하고, 사용한 지도·확인일·측정 방법을 기록한 뒤 500m 전체를 다시 확인하세요."
        )
        st.caption(
            "지도 한 장에 표시된 장소만으로 '보호대상 없음'을 확정하지 마세요. "
            "사업장 경계 기준 500m 전체를 대조하고 근거를 남겨야 합니다."
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
    with st.expander("분류 기준과 추가 확인 사항 (필요할 때 보기)"):
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


def _render_company_import(project) -> None:
    st.write("**회사에서 작성한 주변 시설 목록이 있나요?** 파일에서 가져와 지도·현장 확인 전 후보로 저장할 수 있습니다.")
    with st.expander("기존 목록 파일 가져오기"):
        st.caption("CSV 또는 엑셀 파일의 첫 시트에서 ‘보호대상 명칭’을 읽습니다. ‘명칭’, ‘주소’, ‘구분’, "
                   "‘세부유형’, ‘거리(m)’, ‘근거자료’ 열도 사용할 수 있습니다. 가져온 값은 미검토 후보이며 "
                   "법정 분류나 거리로 자동 확정되지 않습니다.")
        template = pd.DataFrame(columns=["보호대상 명칭", "주소·위치", "보호대상 구분", "세부유형",
                                         "사업장 경계와 거리(m)", "GIS/현장 근거"])
        st.download_button("입력 양식 CSV 다운로드", template.to_csv(index=False).encode("utf-8-sig"),
                           file_name="별지8호_주변보호대상_입력양식.csv", mime="text/csv",
                           key=f"cap_form08_template_{project.project_id}")
        uploaded = st.file_uploader("기존 보호대상 목록", type=["csv", "xlsx"],
                                    key=f"cap_form08_upload_{project.project_id}")
        if uploaded is None:
            return
        if uploaded.size > 5 * 1024 * 1024:
            st.error("파일은 5 MB 이하로 올려 주세요.")
            return
        try:
            if uploaded.name.lower().endswith(".xlsx"):
                table = pd.read_excel(BytesIO(uploaded.getvalue()), dtype=str, keep_default_na=False)
            else:
                try:
                    table = pd.read_csv(BytesIO(uploaded.getvalue()), dtype=str, keep_default_na=False,
                                        encoding="utf-8-sig")
                except UnicodeDecodeError:
                    table = pd.read_csv(BytesIO(uploaded.getvalue()), dtype=str, keep_default_na=False,
                                        encoding="cp949")
        except (ValueError, UnicodeError, OSError, ImportError) as exc:
            st.error(f"목록을 읽을 수 없습니다({type(exc).__name__}). CSV 또는 첫 시트에 표가 있는 엑셀 파일을 확인해 주세요.")
            return
        if len(table) > 1000:
            st.error("한 번에 최대 1,000행까지 가져올 수 있습니다.")
            return
        if not {"보호대상 명칭", "명칭", "이름"} & {str(c).strip() for c in table.columns}:
            st.error("파일에 ‘보호대상 명칭’ 또는 ‘명칭’ 열이 필요합니다.")
            return
        existing = f8.saved_rows(project)
        rows, notices = f8.import_company_rows(table.to_dict("records"), existing)
        st.caption(f"새로운 후보 {len(rows)}건을 가져올 수 있습니다. 기존 목록 {len(existing)}건은 유지됩니다.")
        if notices:
            with st.expander(f"건너뛴 행 확인 ({len(notices)}건)"):
                for notice in notices[:25]:
                    st.write(f"• {notice}")
        if rows and st.button("기존 목록을 미검토 후보로 가져오기", key=f"cap_form08_import_{project.project_id}"):
            f8.save(project, existing + rows, no_target=False, scope_reviewed=False, status="HOLD")
            f8.invalidate_review(project)
            st.session_state[f"cap_form08_scope_reviewed_{project.project_id}"] = False
            save_project(project)
            st.success(f"{len(rows)}건을 가져왔습니다. ‘2. 보호대상 목록’에서 지도 확인 후 확정해 주세요.")
            st.rerun()


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
    if step["id"] in ("search", "list"):
        _render_manual_map_guide(expanded=step["id"] == "search")

    if step["id"] == "search":
        addr = f8.address(project)
        st.markdown(f"**사업장 주소(별지 제3호):** {addr or '아직 없음 — 별지 제3호에서 입력하세요'}")
        st.caption("위 지도를 열어 사업장 경계 주변을 확인하고, 이전에 작성한 목록이 있으면 아래에서 가져오세요. "
                   "목록이 없다면 ‘2. 보호대상 목록’에서 새로 작성할 수 있습니다. "
                   "그 단계에서 목록 전체를 한 번에 분류할 수 있습니다.")
        _render_company_import(project)
    elif step["id"] == "list":
        st.info("**표에 시설명을 입력하거나 회사 목록을 가져온 뒤 ‘갑종·을종·환경수용체 구분하기’를 누르세요.** "
                "시설명이나 세부유형으로 알 수 있는 행은 분류 칸을 채우고, 규모·법정 지정 여부 등 "
                "확인이 필요한 행은 비워 둔 채 이유를 보여 줍니다. 결과는 미검토 상태로 저장됩니다.")
        _render_classification_guide()
        st.caption("위 지도 안내를 열어 확인한 뒤, 표에 없는 대상은 새 행으로 추가하세요.")
        no_target = st.checkbox("사업장 경계 500m 안에 보호대상이 없습니다", value=f8.declared_no_target(project),
                                key=f"cap_form08_none_{project.project_id}")
        rows_source = f8.saved_rows(project)
        evidence = ""
        edited_rows: list[dict] = []
        if no_target:
            record = project.get_field(f8.SITE_KEY)
            previous = (record.value[0].get("GIS/현장 근거", "") if record is not None
                        and isinstance(record.value, list) and record.value and f8.declared_no_target(project) else "")
            evidence = st.text_input("보호대상 없음 확인 근거", value=previous,
                                     key=f"cap_form08_evidence_{project.project_id}",
                                     help="예: 지도 서비스/레이어, 확인일, 사업장 경계와 검토 범위, 현장 확인 기록")
        else:
            frame = pd.DataFrame(rows_source, columns=list(f8.COLUMNS))
            config = {
                "GIS/현장 근거": st.column_config.TextColumn(
                    "확인한 자료·날짜·방법", help="예: 브이월드 항공사진 2026-09-28 확인, 회사 부지 도면 B-01의 경계부터 측정. 이전 목록만으로는 현재 상태를 확인한 근거가 되지 않습니다."),
                "보호대상 구분": st.column_config.SelectboxColumn("구분", options=list(f8.CATEGORIES),
                                                               help="「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」에 따른 구분입니다. 갑종·을종은 「유해화학물질 취급시설 외벽으로부터 보호대상까지의 안전거리 고시」 별표 2·3도 함께 확인하세요."),
                "세부유형": st.column_config.SelectboxColumn(
                    "세부유형", options=[o for opts in f8.SUBTYPES.values() for o in opts],
                    help="「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」의 분류입니다. 갑종·을종 세부 기준은 안전거리 고시 별표 2·3 원문과 함께 대조하세요."),
                "사업장 경계와 거리(m)": st.column_config.NumberColumn(
                    "사업장 경계 기준 실제 거리(m)", min_value=0,
                    help="법정 서식에 작성할 값입니다. 지도/GIS에서 사업장 경계부터 대상까지 확인해 입력하세요."),
                "거주민수": st.column_config.NumberColumn(
                    "거주민수", min_value=0, help="그 대상에 사는 사람 수입니다. 별지 제12·13호 영향범위 내 주민 수 집계에 쓰입니다(비우면 0)."),
                "근로자수": st.column_config.NumberColumn(
                    "근로자수", min_value=0, help="그 대상에서 일하는 사람 수입니다. 별지 제12·13호 집계에 쓰입니다(비우면 0)."),
            }
            # Keep provenance from older projects in the saved rows, but show
            # only the fields that an author can verify on a map or site visit.
            visible_columns = [c for c in f8.COLUMNS if c not in (
                "검색결과 거리(주소점 기준, 참고)", "검색 출처·검색일", "500m 범위 전체 확인")]
            version_key = f"cap_form08_rows_version_{project.project_id}"
            edited_rows = st.data_editor(frame, column_config=config, column_order=visible_columns,
                                         num_rows="dynamic", width="stretch",
                                         key=f"cap_form08_rows_{project.project_id}_{st.session_state.get(version_key, 0)}").to_dict("records")
            report_key = f"cap_form08_classified_{project.project_id}"
            report = st.session_state.pop(report_key, None)
            if report is not None:
                count, unresolved = report
                st.success(f"{count}건의 구분·세부유형을 채웠습니다. 실제 용도와 법정 조건을 확인한 뒤 저장해 주세요.")
                if unresolved:
                    with st.expander(f"추가 확인이 필요한 항목 ({len(unresolved)}건)", expanded=True):
                        for message in unresolved:
                            st.write(f"• {message}")
            if st.button("갑종·을종·환경수용체 구분하기", type="primary",
                         key=f"cap_form08_classify_{project.project_id}"):
                clean_rows = [{k: ("" if pd.isna(v) else v) for k, v in row.items()} for row in edited_rows]
                if not clean_rows or any(not str(row.get("보호대상 명칭") or "").strip() for row in clean_rows):
                    st.warning("먼저 표에 시설명을 입력하고 이름이 없는 행은 지워 주세요.")
                else:
                    classified_rows, count, unresolved = f8.classify_rows(clean_rows)
                    existing_rows = [{column: row.get(column, "") for column in f8.COLUMNS}
                                     for row in rows_source]
                    if classified_rows != existing_rows:
                        f8.save(project, classified_rows, no_target=False, scope_reviewed=False, status="HOLD")
                        f8.invalidate_review(project)
                        save_project(project)
                    st.session_state[report_key] = (count, unresolved)
                    st.session_state[version_key] = st.session_state.get(version_key, 0) + 1
                    st.rerun()
            hints = {f"{r.get('보호대상 구분')}/{r.get('세부유형')}": f8.type_hint(str(r.get("보호대상 구분")), str(r.get("세부유형")))
                     for r in edited_rows}
            for label, hint in hints.items():
                if hint:
                    st.caption(f"「화학사고예방관리계획서 작성 등에 관한 규정」 별표 4 「보호대상」 · {hint}")
        st.markdown("**지도·현장 확인 기록**")
        st.caption("어느 지도에서 무엇을 확인했는지 기록합니다. 회사의 이전 목록은 현재 상태와 다시 대조하세요.")
        previous_review = f8.review(project)
        previous_checks = previous_review.get("확인항목", {})
        checks = {
            key: st.checkbox(label, value=bool(previous_checks.get(key)),
                             key=f"cap_form08_check_{key}_{project.project_id}")
            for key, label in f8.REVIEW_ITEMS
        }
        source = st.text_input("사용한 지도·도면과 확인일", value=previous_review.get("사용자료·확인일", ""),
                               placeholder="예: 브이월드 항공사진, 회사 부지 도면 B-01, 2026-09-28",
                               key=f"cap_form08_review_source_{project.project_id}")
        method = st.text_input("부지 경계·거리 확인 방법", value=previous_review.get("경계·거리 확인방법", ""),
                               placeholder="예: 도면의 부지 경계를 지도에서 대조하고 보호대상까지 거리를 측정",
                               key=f"cap_form08_review_method_{project.project_id}")
        review_record = project.get_field(f8.REVIEW_KEY)
        existing_evidence = review_record.evidence if review_record is not None else []
        if existing_evidence:
            st.caption("저장된 확인자료: " + ", ".join(ref.source_name for ref in existing_evidence))
        map_file = st.file_uploader("확인한 지도·도면 파일 보관 (선택)", type=["png", "jpg", "jpeg", "pdf"],
                                    help="지도에 목록 번호를 표시한 화면·도면을 프로젝트에 보관합니다. "
                                         "파일이 없어도 자료명과 확인일을 적으면 작성할 수 있습니다.",
                                    key=f"cap_form08_map_file_{project.project_id}")
        if map_file is not None and map_file.size > 10 * 1024 * 1024:
            st.error("지도·도면 파일은 10 MB 이하로 올려 주세요.")
        map_numbers = ""
        if not no_target:
            numbered = [str(r.get("보호대상 명칭") or "").strip() for r in edited_rows]
            if numbered:
                st.caption("목록 번호: " + " · ".join(f"{i}. {name or '(이름 미입력)'}"
                                                    for i, name in enumerate(numbered, start=1)))
            map_numbers = st.text_input("지도에 표시한 번호 (쉼표로 구분)",
                                        value=previous_review.get("지도 번호", ""),
                                        placeholder="예: 1,2,3",
                                        help="별지 제8호의 목록 일련번호를 별도 작성한 지도에도 표시한 뒤 입력하세요. 프로그램은 지도 파일을 자동 생성하지 않습니다.",
                                        key=f"cap_form08_map_numbers_{project.project_id}")
        changed = not no_target and edited_rows != rows_source and f8.scope_reviewed(project)
        changed = changed or no_target != f8.declared_no_target(project)
        rechecked = (st.checkbox("이번에 수정한 목록도 지도와 다시 대조했습니다.",
                                 key=f"cap_form08_recheck_{project.project_id}") if changed else True)
        if changed and existing_evidence:
            st.info("목록 또는 보호대상 없음 여부가 바뀌었습니다. 이전 지도 파일은 새 검토 기록에 자동으로 이어지지 않습니다.")
        issues = f8.review_issues(edited_rows, no_target, checks, source, method, map_numbers)
        if no_target and not evidence.strip():
            issues.append("보호대상 없음 판단에 사용한 근거를 적어 주세요.")
        if not rechecked:
            issues.append("수정한 목록을 지도와 다시 대조해 주세요.")
        if map_file is not None and map_file.size > 10 * 1024 * 1024:
            issues.append("첨부 파일은 10 MB 이하로 올려 주세요.")
        if issues:
            with st.expander(f"저장 전 확인할 내용 ({len(issues)}건)", expanded=True):
                for issue in issues:
                    st.write(f"• {issue}")
        can_save = not issues
        if st.button("검토한 보호대상 저장", type="primary", disabled=not can_save,
                     key=f"cap_form08_save_{project.project_id}"):
            evidence_refs = [] if changed else list(existing_evidence)
            if map_file is not None:
                ref = storage.save_attachment(project.project_id, map_file.name, map_file.getvalue(),
                                              source_type="FORM8_MAP_REVIEW", note="별지 제8호 보호대상 지도 확인 자료")
                if ref.sha256 not in {saved_ref.sha256 for saved_ref in evidence_refs}:
                    evidence_refs.append(ref)
            saved = f8.save(project, [{k: ("" if pd.isna(v) else v) for k, v in r.items()} for r in edited_rows],
                            no_target, evidence, scope_reviewed=True)
            f8.save_review(project, checks, source, method, map_numbers, evidence_refs)
            save_project(project)
            st.success("보호대상 없음으로 저장했습니다." if no_target else f"{saved}건을 저장했습니다.")
    else:
        review = f8.review(project)
        if review:
            st.caption(f"확인 자료·날짜: {review.get('사용자료·확인일', '')} · "
                       f"경계·거리: {review.get('경계·거리 확인방법', '')} · "
                       f"지도 번호: {review.get('지도 번호') or '해당 없음'}")
        review_record = project.get_field(f8.REVIEW_KEY)
        if review_record is not None:
            for ref in review_record.evidence:
                path = Path(ref.location).resolve()
                if path.is_relative_to(storage.project_dir(project.project_id).resolve()) and path.is_file():
                    st.download_button(f"확인 지도·도면: {ref.source_name}", path.read_bytes(),
                                       file_name=ref.source_name, key=f"cap_form08_evidence_{ref.sha256}")
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
