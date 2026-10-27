"""화학사고예방관리계획서 화면들이 함께 쓰는 부분.

예전에는 ‘화학사고예방관리계획서 작성’ 한 화면이 별지 15개·서술형·내보내기·제출서식을 모두 담았습니다.
자료 정리(사업장 업무)와 버전 관리가 따로 나간 뒤, 남은 작성 기능을 하는 일별로 나눠 왼쪽 메뉴의 화면 다섯 개로 둡니다.
각 화면은 이 모듈의 page()만 부릅니다. 별지별 입력 화면(ui/cap_formN_view.py)은 그대로 씁니다.
"""
from __future__ import annotations

import importlib
import re
from collections import defaultdict

import pandas as pd
import streamlit as st

from engine.stage2 import cap_workspace as ws
from engine.stage2 import storage
from engine.stage2.cap_guideline import form_guidelines
from ui import cap_facility_editor, cap_frames as frames
from ui import cap_forms_registry as registry
from ui import unsaved_guard

ACTIVE_PROJECT_KEY = "_stage2_active_project_id"

SPECIAL = {
    "narrative": "서술형 항목 · 사전관리방침과 비상대응계획",
    "export": "점검·내보내기 · 보고서 내려받기",
    "submission": "제출·변경 행정서식 · 별지 제31호·제32호",
    "implementation": "이행점검 · 자체점검 별지 제1호~제3호",
}

# 화면 → (제목, 아이콘, 다루는 별지·항목, 설명). 별지 번호 순서와 작성 순서를 따릅니다.
GROUPS = {
    "facts": ("사업장·물질·시설 작성", "🏷️", [1, 3, 4, 5, 6, 7, 8, 9, 10, 11],
              "별지 제1호(작성수준)와 제3~11호(사업장·시설·물질·주변환경·설비)를 작성해요. "
              "‘자료 접수·확인할 일’에서 보낸 물질·설비 값은 미리 채워져 있어요."),
    "scenario": ("사고시나리오·위험도", "🔥", [12, 14, 15],
                 "별지 제12·13호(사고시나리오와 주변지역 영향평가), 제14호(시설빈도), 제15호(위험도 분석)를 작성해요."),
    "emergency": ("비상대응·서술형", "🚨", [16, "narrative"],
                  "별지 제16호(비상대응분야 요약서)와 사전관리방침·비상대응계획 같은 서술형 항목을 작성해요."),
    "export": ("점검·내보내기", "📤", ["export"],
               "작성한 내용을 점검하고 화학사고예방관리계획서를 내려받아요. 최종 제출 확인과 첨부 자료도 여기서 다뤄요."),
    "submission": ("제출·변경·이행점검", "📮", [2, "submission", "implementation"],
                   "변경내역 관리대장(별지 제2호), 검토·변경 검토신청서(별지 제31·32호), 이행점검 자체점검을 작성해요. "
                   "저장해 둔 버전을 비교 기준으로 쓰므로 먼저 ‘버전 관리’에서 제출본을 저장해 두세요."),
}
PAGES = {group: f"ui/cap_{group}_page.py" for group in GROUPS}


def option_label(option) -> str:
    if option in SPECIAL:
        return SPECIAL[option]
    return f"{registry.label(option)} · {form_guidelines()[option].title}"


def page_for(option) -> str:
    """별지 번호나 항목이 들어 있는 화면 파일."""
    return next(PAGES[g] for g, (_, _, options, _) in GROUPS.items() if option in options)


def start_pointer() -> None:
    """새 사업장은 ‘사업장 업무’에서 자료를 올려 시작합니다(여기서는 만들지 않음)."""
    try:
        st.page_link("ui/evidence_workspace_page.py", label="새 사업장은 ‘사업장 업무’에서 자료를 올려 시작하세요", icon="📂")
    except Exception:  # 이 화면만 따로 실행한 경우(이동 링크를 만들 수 없음)
        st.caption("새 사업장은 ‘사업장 업무’ 화면에서 자료를 올려 시작하세요.")


def _project_selector() -> str | None:
    projects = storage.list_projects()
    if not projects:
        st.info("작성할 사업장이 아직 없습니다. 회사 자료를 올리면 초안이 먼저 만들어집니다.")
        start_pointer()
        return None
    labels = {row["project_id"]: f"{row['company_name']} · {row['project_id']}" for row in projects}
    ids = list(labels)
    current = st.session_state.get(ACTIVE_PROJECT_KEY)
    selected = st.selectbox("작성 프로젝트", ids, index=ids.index(current) if current in ids else 0,
                            format_func=lambda pid: labels[pid])
    st.session_state[ACTIVE_PROJECT_KEY] = selected
    start_pointer()
    return selected


def open_project():
    """사업장을 고르고, 작성 대상인지 확인하고, 법령 개정 알림과 버전 상태를 보여 줍니다. 없으면 화면을 멈춥니다."""
    project_id = _project_selector()
    if not project_id:
        st.stop()
    project = storage.load_project(project_id)
    from engine.stage2 import cap_judgement
    from engine.stage2.standalone_entry import is_standalone_stage2_project

    if is_standalone_stage2_project(project) and not project.stage1_snapshot.get("legal_applicability_confirmed"):
        st.info("판정 없이 시작한 작성 프로젝트입니다. 법정 제출 대상 여부는 별도 ‘사업장 판정하기’에서 확인할 수 있습니다.")
        with st.expander("작성수준 확인 (별지 제1호)", expanded=not project.cap_group):
            chosen = st.selectbox("회사가 확인한 작성수준", ["확인 전", "1군", "2군"],
                                  index={"": 0, "1군": 1, "2군": 2}.get(project.cap_group, 0),
                                  key=f"cap_direct_level_{project.project_id}")
            if st.button("작성수준 저장", key=f"cap_direct_level_save_{project.project_id}"):
                project.cap_group = "" if chosen == "확인 전" else chosen
                if project.cap_group:
                    project.set_field("cap.business.writing_level", "작성수준", f"{project.cap_group} 사업장",
                                      "USER_CONFIRMED", note="회사 확인값, 대상 판정 수행하지 않음")
                else:
                    project.fields.pop("cap.business.writing_level", None)
                storage.save_project(project)
                st.rerun()
    if not project.cap_in_scope and not cap_judgement.undecided(project):
        if project.psm_in_scope:
            st.info("이 사업장은 공정안전보고서 작성 대상입니다. 화학사고예방관리계획서 대상은 아닙니다.")
            st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성으로 이동", icon="🏭")
            st.stop()
        st.warning("이 사업장은 화학사고예방관리계획서 작성·제출 대상으로 확인되지 않았습니다. 위에서 다른 사업장을 고르거나 "
                   "'사업장 판정하기'에서 확인하세요.")
        st.stop()

    from ui import version_panel

    version_panel.render_refresh_banner(project, "CAP")
    version_panel.render_status(project, "CAP")
    return project


def _explain(step: dict) -> None:
    st.caption(step["summary"])
    for item in step["explain"]:
        with st.expander(item["term"]):
            st.write(item["text"])


def _render_form1(project) -> None:
    schema = ws.load_form_schema(1)
    steps = ws.steps(1)
    titles = ["1. 시설 입력", "2. 결과", "3. 서식 내보내기"]
    step_ids = ["inputs", "result", "export"]

    st.header(schema["title"])
    step_title = st.radio("단계", titles, horizontal=True, label_visibility="collapsed", key="cap_form01_step")
    step_id = step_ids[titles.index(step_title)]
    if step_id == "inputs":
        st.caption("아래 표에 시설을 한 줄씩 입력하세요. 물질 목록은 시작하기에서 입력한 값이 자동으로 들어와 있고, 최대보유량은 프로그램이 계산합니다.")
        for part in steps:
            if part["id"] in ("scope", "facilities", "chemicals"):
                for item in part["explain"]:
                    with st.expander(item["term"]):
                        st.write(item["text"])
    else:
        current = next((step for step in steps if step["id"] == step_id), None)
        if current:
            _explain(current)

    if step_id == "inputs":
        st.subheader("취급 물질")
        chemicals = ws.form1._chemical_identity_rows(project)
        if chemicals:
            frames.show(
                pd.DataFrame([
                    {
                        "물질명": ws.form1._row_value(row, "물질명", "유해화학물질명", "제품명"),
                        "CAS No.": ws.form1._row_value(row, "CAS 번호", "CAS No."),
                        "함량(%)": ws.form1._row_value(row, "함량(%)", "함량"),
                    }
                    for row in chemicals
                ]),
                width="stretch", hide_index=True,
            )
        else:
            st.warning("물질 목록이 없습니다. 별지 제6호에서 물질을 직접 추가하거나 엑셀·CSV로 올려 주세요.")
        st.caption("별지 제6호에서도 같은 물질 정보를 사용합니다. 단일물질은 아래에서 KOSHA 후보를 조회할 수 있습니다.")
        from ui import cap_kosha_panel

        with st.expander("KOSHA 물질 정보 조회 (참고 후보)"):
            cap_kosha_panel.render(project, "cap_form01")


        st.caption("여기서 고친 설비명·용량·시설유형·성상·비중·운전조건은 ‘자료 접수·확인할 일’ 기록에도 ‘별지 제1호 직접 입력’으로 함께 저장돼 두 곳의 값이 같게 유지돼요. 행을 지우면 자료 접수에서도 제외돼요.")
        cap_facility_editor.render(project, "cap_form01")

    elif step_id == "result":
        form = ws.resolve_form1(project)
        if form.needs:
            st.warning("아직 필요한 정보가 있습니다")
            for item in form.needs:
                st.write(f"• {item}")
        for blocker in form.blockers:
            st.error(blocker)
        for line in ws.result_sentences(list(form.chemical_rows)):
            st.write("• " + line)
        hint_label, hint_reason = ws.level_hint(list(form.chemical_rows), form.writing_level)
        st.metric(
            "사업장 작성수준", form.writing_level or "미확정",
            help="사업장 판정하기에서 승계했거나 회사가 직접 확인해 입력한 작성수준입니다.",
        )
        st.info(f"이 서식의 물질별 최대보유량으로 본 결과: **{hint_label}** — {hint_reason}")
        st.caption("직접 시작한 프로젝트는 제출 전 작성수준과 최대보유량을 확인하세요. 별도 사업장 판정 결과가 있는 프로젝트는 해당 결과를 따릅니다.")

    else:
        form = ws.resolve_form1(project)
        st.write("입력한 자료로 아래 서식이 채워집니다. 규정서식 표 그대로의 DOCX로 내려받을 수 있습니다.")
        with st.expander("서식에 채워지는 내용 미리보기"):
            st.write("**1. 단위공장별 최대보유량 산출**")
            if form.facility_rows:
                frames.show(pd.DataFrame(form.facility_rows).drop(columns=["산정근거"], errors="ignore"), width="stretch", hide_index=True)
            st.write("**2. 유해화학물질별 사업장 내의 최대보유량 산출**")
            if form.chemical_rows:
                frames.show(pd.DataFrame(form.chemical_rows), width="stretch", hide_index=True)
            st.write(f"**3. 작성수준 도출**: {form.writing_level or '미확정'}")
        st.info("점검하고 보고서를 내려받는 곳은 왼쪽 ‘점검·내보내기’ 화면입니다.")


def render_option(project, option) -> None:
    """별지 번호 또는 특별 항목 하나를 그립니다."""
    if option == "submission":
        from ui import cap_submission_forms_view

        cap_submission_forms_view.render(project)
    elif option == "implementation":
        from ui import cap_implementation_self_check_view

        cap_implementation_self_check_view.render(project)
    elif option == "narrative":
        from engine.stage2 import cap_narrative_workspace as cap_narrative
        from ui import narrative_panel

        narrative_panel.render(project, cap_narrative.CAP_PROFILE, ("cap-contacts", "cap-resources"), "cap",
                               decision_facts=cap_narrative.visible_facts(project))
    elif option == "export":
        from engine.stage2 import psm_attachments
        from ui import attachments_panel, cap_final_evidence_panel, report_export_panel

        with st.expander("최종 제출 확인 · 타 제도 심사결과와 공동제출"):
            cap_final_evidence_panel.render(project)
        with st.expander("첨부 자료 · 도면과 분석 자료 올리기"):
            attachments_panel.render(project, psm_attachments.CAP_SLOTS, "cap")
        st.markdown("### 점검하고 내려받기")
        report_export_panel.render(project, "CAP")
    elif option == 1:
        _render_form1(project)
    else:
        importlib.import_module(f"ui.cap_form{option}_view").render(project)


# ---------------------------------------------------------------- 진행 현황

GOTO_KEY = "cap_goto"       # 진행 현황에서 고른 (화면, 서식): 그 화면을 열 때 해당 서식을 바로 펼칩니다
_FORM_CODE = re.compile(r"CAP-FORM(\d+)")
# 서식 번호가 붙지 않은 점검 항목이 속한 별지
_OTHER_CODES = {"CAP-CAS": 6, "CAP-CHEMICAL": 6, "CAP-FACILITY": 1}


def _form_of(code: str):
    match = _FORM_CODE.match(code)
    if match:
        number = int(match.group(1))
        return 12 if number == 13 else number          # 별지 제13호는 제12호 화면에서 함께 작성
    return next((form for prefix, form in _OTHER_CODES.items() if code.startswith(prefix)), None)


def progress(project) -> dict:
    """화면별로 남은 일. 내보내기 점검(report_export.evaluate)과 같은 기준을 별지별로 나눠 셉니다(0.1초 이내).

    돌려주는 값: {"rows": [화면별 행], "final_ready": 제출용 작성본 가능 여부, "remaining": 보완할 것 수}
    각 행: group, title, icon, forms(별지 수), open_forms([(별지, 남은 수)]), later(따로 준비할 첨부 수), next(다음 서식), status, done
    """
    from engine.stage2 import report_export as rx
    from engine.stage2 import versioning as ver

    state = rx.evaluate(project, "CAP")
    remaining, later = defaultdict(int), defaultdict(int)
    for issue in state.text_issues:
        if issue.status != "PASS":
            remaining[_form_of(issue.code)] += 1
    for issue in state.manual_issues:
        later[_form_of(issue.code)] += 1
    rows = []
    for group, (title, icon, options, _) in GROUPS.items():
        forms = [o for o in options if isinstance(o, int)]
        open_forms = [(f, remaining[f]) for f in forms if remaining[f]]
        row = {"group": group, "title": title, "icon": icon, "forms": len(forms), "open_forms": open_forms,
               "later": sum(later[f] for f in forms), "next": open_forms[0][0] if open_forms else options[0]}
        if group == "export":
            total = state.hold + state.review
            row["done"] = state.final_ready
            row["status"] = ("제출용 작성본을 만들 수 있어요" if state.final_ready else
                             f"보완할 것 {total}건이 남아 있어요 · 검토용 초안은 지금도 내려받을 수 있어요" if total else
                             "점검을 확정하면 제출용 작성본을 만들 수 있어요")
        elif group == "submission":
            versions = ver.list_versions(project.project_id, "CAP")
            row["done"] = bool(versions) and not open_forms
            row["status"] = (f"저장한 제출본 {len(versions)}개" if versions else "제출본을 아직 저장하지 않았어요 (버전 관리에서 저장)") + \
                            (f" · 별지 제2호 보완 {open_forms[0][1]}건" if open_forms else "")
        else:
            row["done"] = not open_forms
            done_forms = len(forms) - len(open_forms)
            row["status"] = f"서식 {done_forms}/{len(forms)} 완료" + (
                " · 남은 것: " + ", ".join(f"{registry.label(f)} {n}건" for f, n in open_forms) if open_forms else "")
            if group == "emergency":
                row["status"] += " · 서술형은 직접 확인"
        rows.append(row)
    return {"rows": rows, "final_ready": state.final_ready, "remaining": state.hold + state.review}


def render_progress(project, *, key_prefix: str = "hub") -> None:
    """화학사고예방관리계획서 진행 현황판: 화면별 남은 일과 ‘이어서 작성’ 버튼(다음 서식을 바로 엽니다)."""
    try:
        info = progress(project)
    except ValueError as exc:      # 작성 범위에 화학사고예방관리계획서가 없을 때
        st.caption(str(exc))
        return
    done = sum(r["done"] for r in info["rows"])
    st.markdown(f"**화학사고예방관리계획서 진행 현황** — 화면 {done}/{len(info['rows'])} 완료")
    for row in info["rows"]:
        with st.container(border=True):
            cols = st.columns([4, 1])
            cols[0].markdown(f"{'✅' if row['done'] else row['icon']} **{row['title']}** — {row['status']}")
            if row["later"]:
                cols[0].caption(f"첨부·현장 자료로 따로 준비할 것 {row['later']}건")
            if not row["done"]:
                cols[0].caption("다음: " + option_label(row["next"]))
            if cols[1].button("이어서 작성 →" if not row["done"] else "열기", key=f"{key_prefix}_{row['group']}"):
                st.session_state[GOTO_KEY] = (row["group"], row["next"])
                try:
                    st.switch_page(PAGES[row["group"]])
                except Exception:          # 메뉴 없이 단독 실행되는 경우
                    st.info(f"왼쪽 메뉴의 ‘{row['title']}’ 화면을 열어 주세요.")


def page(group: str) -> None:
    """화면 하나: 제목·사업장 선택·(여러 개면) 별지 선택·본문."""
    title, icon, options, summary = GROUPS[group]
    st.set_page_config(page_title=title, page_icon=icon, layout="wide")
    st.title(f"{icon} {title}")
    st.caption(summary)
    project = open_project()
    goto = st.session_state.pop(GOTO_KEY, None)
    if goto and goto[0] == group and goto[1] in options and len(options) > 1:
        key = f"cap_form_no_{group}"
        st.session_state[key] = st.session_state[f"{key}__accepted"] = goto[1]
    if len(options) == 1:
        render_option(project, options[0])
        return
    option = unsaved_guard.selector("작성할 서식", options, key=f"cap_form_no_{group}", format_func=option_label)
    try:
        render_option(project, option)
    finally:
        unsaved_guard.finish()
