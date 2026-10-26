"""사업장 업무 화면: 자료를 올리면 초안이 먼저 만들어지고, 사람은 예외만 처리합니다."""
from __future__ import annotations

import hashlib
import json

import streamlit as st

from engine.stage2 import evidence_llm, scenario_triage
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project

STATE_TEXT = {"confirmed": "확정", "provisional": "잠정", "assumed": "가정", "conflict": "충돌", "invalid": "오류"}
FIELD_SHORT = {"inventory": "보유량", "pressure": "압력", "concentration": "함량"}
MAX_EXPANDERS = 40


def _entity_label(entity: str) -> str:
    if not entity.startswith(("facility:", "material:")):
        return entity
    return entity.split(":", 1)[1] + (" (설비)" if entity.startswith("facility:") else " (물질)")


MISSING_PREFIX = "기본 운전조건 미확인: "


def _task_rows(project) -> list[dict]:
    """같은 설비의 빠진 항목은 한 줄로 묶고, 화면에 내부 열 이름이 보이지 않게 합니다."""
    grouped, rows = {}, []
    for task in ew.tasks(project):
        if task["key"]:
            continue
        if task["task"].startswith(MISSING_PREFIX):
            grouped.setdefault(task["entity"], []).append(task["task"][len(MISSING_PREFIX):])
        else:
            rows.append({"대상": _entity_label(task["entity"]), "할 일": task["task"]})
    rows.extend({"대상": _entity_label(entity), "할 일": "자료에 없는 값: " + ", ".join(labels)} for entity, labels in grouped.items())
    return rows


def _commit(project) -> None:
    save_project(project)
    st.rerun()


def _project_header():
    projects = list_projects()
    with st.expander("새 사업장 만들기", expanded=not projects):
        with st.form("evidence_new_project"):
            name = st.text_input("사업장명")
            address = st.text_input("사업장 주소")
            if st.form_submit_button("자료 정리 시작"):
                try:
                    project = create_direct_cap_project(name, address=address, cap_group="")
                    save_project(project)
                    st.session_state["_stage2_active_project_id"] = project.project_id
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if not projects:
        st.stop()
    options = {p["project_id"]: p["company_name"] for p in projects}
    current = st.session_state.get("_stage2_active_project_id")
    project_id = st.selectbox("작업할 사업장", list(options), index=list(options).index(current) if current in options else 0,
                              format_func=options.get)
    st.session_state["_stage2_active_project_id"] = project_id
    return load_project(project_id)


def _metrics(project) -> None:
    info = ew.summary(project)
    cols = st.columns(5)
    cols[0].metric("접수한 문서", info["documents"])
    cols[1].metric("자동 기입", info["auto"], help="규칙을 모두 통과해 사람 손 없이 채운 값입니다. 출처는 모두 남아 있습니다.")
    cols[2].metric("직접 확인", info["person"])
    cols[3].metric("확인할 일", info["pending"], help="충돌·값 오류·자동 기입 보류 항목입니다.")
    cols[4].metric("먼저 볼 핵심값", info["critical_auto"], help="자동 기입했지만 예비 순위를 바꿀 수 있는 값입니다.")


# ---------------------------------------------------------------- 1. 자료 올리기

def _classify(name: str, content: bytes) -> tuple[str, str | None]:
    """(내용 해시, 종류). 분류 결과는 엔진이 내용 해시로 보관하므로 다시 그려도 파일을 다시 읽지 않습니다."""
    digest = hashlib.sha256(content).hexdigest()
    try:
        return digest, ew.classify_document(name, content)
    except Exception:
        return digest, None


def _tab_upload(project) -> None:
    st.write("회사에 있는 자료를 그대로 올리세요. 표의 설비번호·제품코드로 같은 대상을 연결하고, 규칙을 통과한 값은 알아서 채웁니다.")
    pid = project.project_id
    uploaded = st.file_uploader("회사 자료 (파일당 20MB 이하)", type=["csv", "xlsx", "pdf", "docx", "hwpx", "txt"], accept_multiple_files=True)
    st.caption("물질·설비 파일을 함께 선택하세요. 머리글로 자동 분류하고 판별할 수 없는 파일만 종류를 묻습니다.")
    selected = {}
    for index, file in enumerate(uploaded or []):
        digest, detected = _classify(file.name, file.getvalue())
        if detected:
            st.write(f"{file.name}: {'물질' if detected == 'material' else '설비'} 자료로 분류")
            selected[index] = detected
        else:
            # 파일 내용 기준 키: 다른 파일을 빼도 이미 고른 종류가 다른 파일로 옮겨 가지 않습니다
            selected[index] = st.selectbox(f"{file.name} 자료 종류 확인", ["선택하세요", "material", "facility"],
                                           format_func=lambda v: {"선택하세요": "선택하세요", "material": "물질", "facility": "설비"}[v],
                                           key=f"kind_{pid}_{digest[:16]}")
    hint = st.text_input("식별번호가 없는 단일 대상 문서의 대상번호 (선택)", help="예: P-01, TK-01. 표에 번호가 있으면 비워 두세요.")
    if st.button("자료 읽기", type="primary", disabled=not uploaded):
        for index, file in enumerate(uploaded):
            try:
                if selected[index] == "선택하세요":
                    raise ValueError("자료 종류를 선택하세요.")
                count = ew.ingest(project, file.name, file.getvalue(), selected[index], hint)
                save_attachment(project.project_id, file.name, file.getvalue(), note="공통정보 추출 원문")
                save_project(project)
                st.session_state.setdefault("evidence_notes", []).append(f"{file.name}: 후보 {count}개 접수")
            except Exception as exc:
                st.session_state.setdefault("evidence_notes", []).append(
                    f"{file.name}: 읽지 못했습니다 ({exc if isinstance(exc, ValueError) else type(exc).__name__}). 저장된 다른 자료는 유지됩니다.")
        st.rerun()
    st.download_button("가상 회사 시험자료 ZIP", ew.demo_zip(), file_name="synthetic_company_evidence.zip", mime="application/zip")
    st.caption("ZIP을 풀어 네 파일을 한 번에 올리세요. 02·03번은 용량 충돌, 04번은 제목 줄과 수식이 있는 대장입니다.")
    data = ew.graph(project)
    for doc in data["documents"]:
        with st.expander(f"{doc['name']} · 후보 {doc['fact_count']}개"):
            st.code(doc["sha256"], language=None)
            for table in doc.get("tables", []):
                if table["header_row"]:
                    st.caption(f"{table['location']}: {table['header_row']}번째 줄을 머리글로 읽음 · 데이터 {table['rows']}행")
                else:
                    st.caption(f"{table['location']}: 알아볼 수 있는 머리글이 없어 읽지 못함")
            if doc["unmapped_columns"]:
                st.write("아직 연결하지 못한 열:", doc["unmapped_columns"])
            for passage in doc["passages"][:200]:
                st.text(passage["location"] + "\n" + passage["text"][:4000])
    _local_llm(project, data)
    st.caption("스캔 PDF의 OCR, 구형 HWP·도면 해석은 자동 처리하지 않습니다. 읽지 못한 자료는 확인할 일에 남습니다.")


def _local_llm(project, data) -> None:
    with st.expander("로컬 AI로 서술형 문서 후보 제안 (선택)"):
        readable = {d["sha256"]: d for d in data["documents"] if d.get("hint") and any(p.get("text", "").strip() for p in d.get("passages", []))}
        if not readable:
            st.info("대상 식별번호를 지정해 텍스트가 있는 PDF·DOCX·HWPX·TXT를 접수하세요.")
            return
        doc_id = st.selectbox("읽을 문서", list(readable), format_func=lambda k: readable[k]["name"])
        st.caption("로컬 LLM 설정(LOCAL_LLM_PROVIDER, LOCAL_LLM_URL, LOCAL_LLM_MODEL)을 사용합니다. 원문 인용 검증을 통과한 값도 사람이 확인하기 전에는 보류됩니다.")
        if st.button("로컬 AI 후보 제안"):
            try:
                from engine.stage2.local_llm import build_local_llm_client, local_llm_config_from_sources
                outcome = evidence_llm.propose(project, doc_id, build_local_llm_client(local_llm_config_from_sources()))
                save_project(project)
                st.success(f"원문 대조를 통과한 후보 {outcome['accepted']}개, 거부 {outcome['rejected']}개.")
            except Exception as exc:
                st.error(f"로컬 AI 후보 추출 실패: {exc}")


# ---------------------------------------------------------------- 2. 확인할 일

def _fact_label(fact) -> str:
    return f"{fact['value']} — {fact['document']} / {fact['location']} (원문: {fact['raw']})"


def _critical_section(project) -> None:
    items = ew.critical_auto(project)
    if not items:
        return
    st.subheader(f"먼저 볼 핵심값 {len(items)}개")
    st.caption("규칙을 통과해 자동으로 채웠지만, 이 값이 틀리면 예비 순위가 달라집니다. 출처를 보고 맞으면 확인 완료로 바꾸세요.")
    st.dataframe([{"대상": _entity_label(s["entity"]), "항목": ew.LABELS[s["field"]], "값": str(s["chosen"]["value"]),
                   "문서": s["chosen"]["document"], "위치": s["chosen"]["location"]} for s in items],
                 hide_index=True, width="stretch")
    checked = st.checkbox("위 값을 출처와 대조했습니다", key="critical_checked_" + project.project_id)
    if st.button("핵심값 확인 완료", disabled=not checked):
        ew.confirm_auto(project, [s["key"] for s in items])
        _commit(project)


def _resolve_item(project, item) -> None:
    slot = item["slot"]
    pid = project.project_id
    choices = {f["id"]: f for f in slot["facts"]}
    selectable = [i for i, f in choices.items() if ew.value_problem(slot["field"], f["value"]) is None]
    if item["reasons"]:
        st.write("자동 기입 보류 이유:", ", ".join(item["reasons"]))
    if selectable:
        choice = st.radio("사용할 값", selectable, key=f"pick_{pid}_{slot['key']}",
                          format_func=lambda i: _fact_label(choices[i]))
        checked = st.checkbox("원문·단위·현재 적용 여부를 확인했습니다", key=f"chk_{pid}_{slot['key']}_{slot['signature']}")
        if st.button("이 값으로 확인", key=f"ok_{pid}_{slot['key']}", disabled=not checked):
            try:
                ew.approve(project, slot["key"], choice)
                _commit(project)
            except ValueError as exc:
                st.error(str(exc))
    else:
        st.write("후보:", [_fact_label(f) for f in slot["facts"]])
        st.caption("읽은 값을 쓸 수 없습니다. 원문을 확인해 값을 직접 적어 주세요.")
    with st.form(f"manual_{pid}_{slot['key']}"):
        value = st.text_input(f"직접 확인한 {ew.LABELS[slot['field']]}")
        reason = st.text_input("확인한 자료·위치·날짜")
        if st.form_submit_button("직접 입력으로 확인"):
            try:
                ew.add_manual(project, slot["entity"], slot["field"], value, reason, confirm=True)
                _commit(project)
            except ValueError as exc:
                st.error(str(exc))


def _tab_review(project) -> None:
    pid = project.project_id
    queue = ew.review_queue(project)
    if not queue and not ew.critical_auto(project) and not ew.tasks(project):
        st.success("확인할 일이 없습니다. 모든 시나리오 조건이나 법적 대상 여부가 확인됐다는 뜻은 아닙니다.")
    _critical_section(project)

    for kind, title in (("충돌", "자료끼리 값이 다릅니다"), ("값 오류", "읽은 값을 쓸 수 없습니다")):
        items = [i for i in queue if i["kind"] == kind]
        if not items:
            continue
        st.subheader(f"{title} ({len(items)})")
        for item in items[:MAX_EXPANDERS]:
            star = " ★핵심" if item["critical"] else ""
            with st.expander(f"{_entity_label(item['entity'])} · {ew.LABELS[item['field']]}{star}"):
                _resolve_item(project, item)
        if len(items) > MAX_EXPANDERS:
            st.caption(f"나머지 {len(items) - MAX_EXPANDERS}개는 위 항목을 처리하면 이어서 표시됩니다.")

    held = [i for i in queue if i["kind"] == "확인 필요"]
    if held:
        st.subheader(f"자동 기입을 보류한 값 ({len(held)})")
        st.caption("충돌은 없지만 출처 신뢰도가 낮거나 단위·추출 경로가 불확실해 사람이 보고 넘기는 값입니다.")
        st.dataframe([{"대상": _entity_label(i["entity"]), "항목": ew.LABELS[i["field"]], "값": str(i["slot"]["facts"][0]["value"]),
                       "보류 이유": ", ".join(i["reasons"]), "문서": i["slot"]["facts"][0]["document"],
                       "위치": i["slot"]["facts"][0]["location"], "핵심": "★" if i["critical"] else ""} for i in held],
                     hide_index=True, width="stretch")
        st.caption("표에서 읽은 값만 일괄 확인합니다. 문장·AI로 뽑은 값, 충돌, 오류 값은 포함되지 않습니다.")
        checked = st.checkbox("위 표의 값과 출처를 확인했습니다", key="bulk_checked_" + pid)
        if st.button("충돌 없는 값 일괄 확인", disabled=not checked):
            outcome = ew.approve_bulk(project, [i["key"] for i in held])
            st.session_state["evidence_notes"] = [f"{outcome['approved']}개 확인, {len(outcome['skipped'])}개는 개별 확인이 필요합니다."]
            _commit(project)
        with st.expander("하나씩 확인"):
            for item in held[:MAX_EXPANDERS]:
                st.markdown(f"**{_entity_label(item['entity'])} · {ew.LABELS[item['field']]}**")
                _resolve_item(project, item)

    others = _task_rows(project)
    if others:
        st.subheader("자료에서 더 필요한 것")
        st.caption("올린 자료에 없는 값입니다. 알고 있으면 아래 ‘직접 추가’로, 없으면 다음 자료를 올리세요.")
        st.dataframe(others, hide_index=True, width="stretch")

    with st.expander("회사에서 확인한 사실 직접 추가"):
        with st.form("manual_add_" + pid):
            entity = st.text_input("대상 (예: facility:TK-01 또는 material:P-01)")
            field = st.selectbox("항목", list(ew.LABELS), format_func=ew.LABELS.get)
            value = st.text_input("확인값 (숫자는 항목에 표시한 단위로)")
            reason = st.text_input("확인한 자료·위치·날짜 또는 담당자 확인 내용")
            if st.form_submit_button("확인값으로 추가"):
                try:
                    ew.add_manual(project, entity, field, value, reason, confirm=True)
                    _commit(project)
                except ValueError as exc:
                    st.error(str(exc))


# ---------------------------------------------------------------- 3. 시나리오 후보

def _state_text(row) -> str:
    return " · ".join(f"{FIELD_SHORT[f]} {STATE_TEXT[row['value_states'][f]]}" for f in scenario_triage.SCORED_FIELDS)


def _question_form(project, index, question) -> None:
    field = question["field"]
    entity = question["material"] if field == "concentration" else question["facility"]
    st.write(question["question"])
    with st.form(f"question_{project.project_id}_{index}"):
        value = st.text_input(f"{ew.LABELS[field]} 실제 값")
        reason = st.text_input("확인한 자료·위치·날짜")
        if st.form_submit_button("알고 있는 값 입력"):
            try:
                ew.add_manual(project, entity, field, value, reason, confirm=True)
                _commit(project)
            except ValueError as exc:
                st.error(str(exc))


def _tab_scenarios(project) -> None:
    triage = scenario_triage.evaluate(project)
    st.warning("예비 검토 순서입니다. 피해거리·규정수량·법적 대상 판정이나 최종 사고시나리오가 아닙니다. "
               "‘가정’ 값이 들어간 후보는 계산 결과나 작성자료에 자동 반영하지 않습니다.")
    st.caption(triage["method"])
    linked = [r for r in triage["rows"] if r["linked"]]
    if not linked:
        st.info("설비의 취급제품이 물질 자료와 연결되면 순위가 나타납니다. 확인되지 않은 후보값도 ‘잠정’으로 표시해 미리 계산합니다.")
    else:
        st.dataframe([{"순위": r["rank"], "설비": _entity_label(r["facility"]), "물질": _entity_label(r["material"]),
                       "예비 지표": round(r["score"], 1), "값 상태": _state_text(r),
                       "순위를 바꾸는 값": ", ".join(FIELD_SHORT[f] for f in r["rank_critical"]),
                       "상태": r["state"]} for r in linked], hide_index=True, width="stretch")
    if triage["questions"]:
        st.subheader(f"먼저 물어볼 값 ({len(triage['questions'])})")
        st.caption("값이 없어서 임시값을 썼는데, 그 값에 따라 순위가 달라지는 것만 골랐습니다. 나머지 빈 값은 물어보지 않습니다.")
        for index, question in enumerate(triage["questions"][:MAX_EXPANDERS]):
            with st.expander(f"{_entity_label(question['facility'])} × {_entity_label(question['material'])} · {ew.LABELS[question['field']]}"):
                _question_form(project, index, question)
    elif linked:
        st.info("값이 없어서 순위가 달라지는 항목은 없습니다. 빈 값도 계산 전에는 확인해야 합니다.")
    st.caption(triage["sensitivity"])
    unlinked = [r for r in triage["rows"] if not r["linked"]]
    if unlinked:
        with st.expander(f"취급 관계를 확인하지 못한 조합 {len(unlinked)}개 (삭제하지 않고 보류)"):
            st.dataframe([{"설비": _entity_label(r["facility"]), "물질": _entity_label(r["material"]),
                           "보류 이유": ", ".join(r["blockers"][:3])} for r in unlinked[:500]], hide_index=True, width="stretch")
    if linked:
        with st.expander("조합별 근거 보기"):
            pick = st.selectbox("조합", range(len(linked)), format_func=lambda i: f"{linked[i]['rank']}위 · {_entity_label(linked[i]['facility'])} × {_entity_label(linked[i]['material'])}")
            row = linked[pick]
            st.json({"rank": row["rank"], "values": row["values"], "value_states": row["value_states"], "assumptions": row["assumptions"],
                     "conflicts": row["conflicts"], "provenance": row["sources"], "blockers": row["blockers"],
                     "rank_critical": row["rank_critical"], "rank_sensitive": row["rank_sensitive"]})


# ---------------------------------------------------------------- 4. 연결·내보내기

def _form1_payoff(project) -> None:
    """연결한 자료로 별지 제1호가 어디까지 채워졌는지, 법정 산정에 더 필요한 값이 무엇인지 보여 줍니다."""
    record = project.get_field("inventory.facilities")
    if record is None or record.status not in {"USER_CONFIRMED", "VERIFIED"}:
        return
    from engine.stage2 import cap_workspace as ws
    form = ws.resolve_form1(project)
    st.subheader("별지 제1호에 이어진 결과")
    if form.chemical_rows:
        st.dataframe([{"물질": r.get("물질명"), "CAS": r.get("CAS No."), "최대보유량(ton)": r.get("사업장 내 최대보유량(ton)"),
                       "산정근거": r.get("산정근거")} for r in form.chemical_rows], hide_index=True, width="stretch")
    needs = ew.form1_needs(project)
    if needs:
        st.caption("법정 산정(별표 4)으로 계산하려면 아래 값이 더 필요합니다. 별지 제1호의 시설 입력에서 저장하면 계산됩니다. 읽어 온 시설유형·성상·용량·비중은 미리 채워져 있습니다.")
        for need in needs:
            st.write("• " + need)


def _tab_export(project) -> None:
    data = ew.graph(project)
    info = ew.summary(project)
    legal = ew.unreviewed_legal(project)
    if legal:
        st.warning(f"법적 계산 입력값 {len(legal)}개가 자동 기입 상태입니다. 원자료를 확인하기 전에는 작성자료에 연결할 수 없습니다.")
        with st.expander("법적 계산 입력값 확인", expanded=True):
            st.dataframe([{"대상": _entity_label(s["entity"]), "항목": ew.LABELS[s["field"]],
                           "값": str(s["chosen"]["value"]), "자료": s["chosen"]["document"],
                           "위치": s["chosen"]["location"]} for s in legal], hide_index=True, width="stretch")
            checked = st.checkbox("위 값과 원자료·단위·현재 적용 여부를 모두 대조했습니다", key="legal_review_" + project.project_id)
            if st.button("법적 입력값 확인 완료", disabled=not checked):
                ew.confirm_auto(project, [s["key"] for s in legal])
                save_project(project)
                st.rerun()
    if info["critical_auto"]:
        st.warning(f"자동 기입한 핵심값 {info['critical_auto']}개를 아직 확인하지 않았습니다. ‘확인할 일’에서 먼저 보세요.")
    proposed = ew.publishing_plan(project)
    st.write("기존 작성자료에 연결할 내용")
    for key, rows in proposed.items():
        with st.expander(key, expanded=True):
            st.write("새 연결값")
            st.dataframe(rows, hide_index=True, width="stretch")
            old = project.get_field(key)
            if old:
                st.write("현재 저장값")
                st.json(old.value)
    overwrite = st.checkbox("기존 작성자료와의 차이를 검토했으며 해당 목록을 새 연결값으로 교체합니다")
    if st.button("확인한 공통정보를 작성자료에 연결", disabled=not proposed or bool(legal)):
        try:
            ew.publish(project, replace_existing=overwrite)
            save_project(project)
            st.success("연결했습니다. 아래 작성 화면에서 누락 조건과 산정값을 이어서 검토하세요.")
        except ValueError as exc:
            st.error(str(exc))
    _form1_payoff(project)
    confirmed = [{"대상": _entity_label(s["entity"]), "항목": ew.LABELS[s["field"]], "값": str(s["chosen"]["value"]),
                  "방식": ew.DECISION_LABEL.get(s["method"], "확인 완료"), "문서": s["chosen"]["document"], "위치": s["chosen"]["location"]}
                 for s in ew.slots(project) if s["chosen"]]
    with st.expander(f"확정한 사실 {len(confirmed)}개와 출처"):
        st.dataframe(confirmed, hide_index=True, width="stretch")
    for packet in ew.scenario_packets(project):
        with st.expander(packet["설비"] + " · 시나리오 입력 검토팩"):
            st.json(packet)
    st.page_link("ui/cap_workspace_page.py", label="주변 지도·사고시나리오·화학사고예방관리계획서 작성")
    st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성")
    cols = st.columns(2)
    cols[0].download_button("검토 보고서 (md)", ew.report(project).encode(), file_name="company_evidence_review.md", mime="text/markdown")
    cols[1].download_button("출처·결정 기록 (JSON)", json.dumps(data, ensure_ascii=False, indent=2).encode(),
                            file_name="company_evidence_graph.json", mime="application/json")


st.set_page_config(page_title="사업장 업무", page_icon="📂", layout="wide")
st.title("자료를 올리면 초안이 먼저 나옵니다")
st.caption("사람은 서식을 채우지 않고, 규칙이 멈춘 예외만 처리합니다.")
_active = _project_header()
_metrics(_active)
for _note in st.session_state.pop("evidence_notes", []):
    (st.error if "읽지 못" in _note else st.success)(_note)
_tabs = st.tabs(["자료 올리기", "확인할 일", "시나리오 후보", "연결·내보내기"])
with _tabs[0]:
    _tab_upload(_active)
with _tabs[1]:
    _tab_review(_active)
with _tabs[2]:
    _tab_scenarios(_active)
with _tabs[3]:
    _tab_export(_active)
