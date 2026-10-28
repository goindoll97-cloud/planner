"""사업장 업무 화면: 신입사원도 따라올 수 있게 단계별로 안내합니다.

① 자료 올리기 → ② 파일별 보완 요청 → ③ 시나리오 후보 → ④ 작성·내려받기

보완 요청은 ②의 한 표에 모으고 ③은 후보 표, ④는 작성 동작과 간단한 진행 상태만 보여 줍니다.
"""
from __future__ import annotations

import hashlib
import re

import streamlit as st

from engine.stage2 import demo_company, scenario_triage, cap_intake_guide
from engine.stage2 import cap_evidence_links, cap_fact_drafting, cap_fact_status, cap_upload_template
from engine.stage2.intake import build_intake_catalog
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import delete_all_projects, list_projects, load_attachment, load_project, save_attachment, save_project

STEPS = {1: "① 자료 올리기", 2: "② 파일별 보완 요청", 3: "③ 시나리오 후보", 4: "④ 작성·내려받기"}
DOCUMENT_TYPES = (".docx", ".pdf", ".hwpx", ".hwp", ".txt")
MISSING_FIELDS = ("product", "inventory", "pressure", "temperature", "facility_type", "substance_state")

# ---------------------------------------------------------------- 사람 말로 바꾸기

def _unit(field: str) -> str:
    match = re.search(r"\(([^)]+)\)$", ew.LABELS[field])
    return match.group(1) if match else ""


def _name(field: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", ew.LABELS[field])


def _number(value) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return str(value)
    if abs(value) >= 1e6:
        return f"{value:,.0f}"
    return f"{value:,.6g}"


def _value(field: str, value) -> str:
    unit = _unit(field)
    text = _number(value)
    if not unit or not isinstance(value, (int, float)):
        return text
    return f"{text}{unit}" if unit == "%" else f"{text} {unit}"


def _where(fact) -> str:
    """‘CSV 행 2 열 4’ 같은 내부 위치를 ‘02_equipment.csv 2번째 줄’로 바꿉니다."""
    doc, location = fact["document"], str(fact["location"])
    if doc == "담당자 입력":
        return "직접 입력"
    match = re.match(r"^(.*?)\s*행 (\d+)(?: 열 \d+)?$", location)
    if not match:
        return f"{doc} ({location})"
    place, row = match.groups()
    if place == "CSV":
        return f"{doc} {row}번째 줄"
    if doc.lower().endswith((".xlsx", ".xlsm")):
        return f"{doc} ‘{place}’ 시트 {row}번째 줄"
    return f"{doc} {place} {row}번째 줄"


def _raw_note(fact) -> str:
    """자료에 다른 단위로 적힌 값을 바꿨으면 원래 표기를 알려 줍니다 (예: 10,000 L → 10 m³)."""
    raw, value = str(fact.get("raw", "")).strip(), fact["value"]
    try:
        same = float(raw.replace(",", "")) == float(value)
    except (TypeError, ValueError):
        same = raw == str(value)
    if same or not raw:
        return ""
    try:
        raw = _number(float(raw.replace(",", "")))
    except ValueError:
        pass
    header_unit = re.search(r"\(([^)]+)\)\s*$", str(fact.get("header", "")))
    return f" (자료에는 ‘{raw}{' ' + header_unit.group(1) if header_unit else ''}’로 적혀 있음)"


class Names:
    """화면에 ‘가상 저장탱크 (TK-01)’처럼 이름과 번호를 함께 보여 줍니다."""

    def __init__(self, slots):
        self.names = {}
        for slot in slots:
            if slot["field"] == "name":
                fact = slot["chosen"] or (slot["facts"][0] if slot["facts"] else None)
                if fact and str(fact["value"]).strip():
                    self.names[slot["entity"]] = str(fact["value"]).strip()

    def __call__(self, entity: str) -> str:
        if entity == ew.SITE_ENTITY:
            return "사업장"
        if entity.startswith("detector:"):
            return "감지기 " + entity.split(":", 1)[1]
        if not entity.startswith(("facility:", "material:")):
            return entity
        code = entity.split(":", 1)[1]
        name = self.names.get(entity)
        return f"{name} ({code})" if name and name != code else code


# ---------------------------------------------------------------- 질문 모으기

def _collect(project, triage) -> dict:
    """사람에게 물어볼 것을 한곳에 모읍니다. 같은 값을 두 번 묻지 않습니다."""
    all_slots = ew.slots(project)
    queue = ew.review_queue(project)
    asked = {(i["entity"], i["field"]) for i in queue}
    rank_questions = []
    for question in triage["questions"]:
        field = question["field"]
        entity = question["material"] if field == "concentration" else question["facility"]
        if (entity, field) not in asked:
            asked.add((entity, field))
            rank_questions.append({**question, "entity": entity})
    present = {}
    for slot in all_slots:
        present.setdefault(slot["entity"], set()).add(slot["field"])
    missing = {}
    for entity in sorted(e for e in present if e.startswith("facility:")):
        fields = [f for f in MISSING_FIELDS if f not in present[entity] and (entity, f) not in asked]
        if fields:
            missing[entity] = fields
    notes = [t for t in ew.tasks(project) if not t["key"] and not t["task"].startswith("기본 운전조건 미확인")]
    return {"slots": all_slots, "names": Names(all_slots),
            "conflicts": [i for i in queue if i["kind"] == "충돌"],
            "problems": ew.problems(project),
            "held": [i for i in queue if i["kind"] == "확인 필요"],
            "rank": rank_questions, "missing": missing, "notes": notes}


def _question_count(found) -> int:
    return len(found["conflicts"]) + len(found["problems"]) + len(found["held"]) + len(found["rank"]) + len(found["missing"])


# ---------------------------------------------------------------- 공통

def _save(project, note: str | None = None) -> None:
    save_project(project)
    if note:
        st.session_state.setdefault("evidence_notes", []).append(note)
    st.rerun()


def _go(step: int, pid: str) -> None:
    st.session_state["evidence_step_" + pid] = step


def _next_button(step: int, pid: str, label: str) -> None:
    st.button(label, key=f"next_{step}_{pid}", type="primary", on_click=_go, args=(step, pid))


# ---------------------------------------------------------------- 머리

def _project_header():
    projects = list_projects()
    done = st.session_state.pop("evidence_reset_done", None)
    if done is not None:
        st.success(f"사업장 {done}곳을 모두 지웠어요. 새 사업장을 만들어 처음부터 시작하세요.")
    with st.expander("새 사업장 만들기", expanded=not projects):
        with st.form("evidence_new_project"):
            name = st.text_input("사업장 이름")
            address = st.text_input("사업장 주소")
            if st.form_submit_button("만들기"):
                try:
                    project = create_direct_cap_project(name, address=address, cap_group="")
                    save_project(project)
                    st.session_state["_stage2_active_project_id"] = project.project_id
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))
    if not projects:
        st.info("먼저 사업장을 만들어 주세요. 이름과 주소만 있으면 돼요.")
        st.stop()
    _reset_all(len(projects))
    options = {p["project_id"]: p["company_name"] for p in projects}
    current = st.session_state.get("_stage2_active_project_id")
    project_id = st.selectbox("사업장", list(options), index=list(options).index(current) if current in options else 0,
                              format_func=options.get)
    st.session_state["_stage2_active_project_id"] = project_id
    return load_project(project_id)


def _reset_all(count) -> None:
    """연습을 처음부터 다시 할 때: 사업장을 모두 지웁니다(승인한 규정 DB·법령 자료는 그대로)."""
    with st.expander("사업장 모두 지우고 처음부터 하기"):
        st.warning(f"저장된 사업장 {count}곳과 그 안의 올린 파일·답변·작성 내용·버전이 모두 지워지고 되돌릴 수 없어요. "
                   "승인해 둔 규정 DB와 내려받은 법령 자료는 지우지 않아요.")
        sure = st.checkbox("모두 지우는 것을 확인했어요", key="evidence_reset_all_confirm")
        if st.button("사업장 모두 지우기", disabled=not sure, key="evidence_reset_all"):
            removed = delete_all_projects()
            st.session_state.clear()
            st.session_state["evidence_reset_done"] = removed
            st.rerun()


def _status_line(project, found) -> None:
    info = ew.summary(project)
    if not info["documents"]:
        return
    count = len(_correction_rows(project, found))
    parts = [f"자료 {info['documents']}개를 읽었어요", f"값 {info['auto'] + info['person']}개를 채웠어요"]
    unread = sum(bool(d.get("needs_reading")) for d in ew.documents(project))
    parts.append(f"보완·확인할 항목 {count}개" if count else "자료에서 확인할 항목이 없어요")
    if unread:
        parts.append(f"읽지 못한 파일 {unread}개는 확인이 필요해요")
    st.markdown(" · ".join(parts))


# ---------------------------------------------------------------- ① 자료 올리기

def _classify(name: str, content: bytes) -> tuple[str, str | None]:
    """(내용 해시, 종류). 분류 결과는 엔진이 내용 해시로 보관하므로 다시 그려도 파일을 다시 읽지 않습니다."""
    digest = hashlib.sha256(content).hexdigest()
    try:
        return digest, ew.classify_document(name, content)
    except Exception:
        return digest, None


def _step_upload(project, found) -> None:
    pid = project.project_id
    st.write("회사 자료를 한 번에 올리세요. 파일별로 읽힌 값과 보완할 부분을 알려 드립니다.")
    with st.expander("어떤 자료를 올리면 되나요?"):
        group = project.cap_group if project.cap_group in {"1군", "2군"} else ""
        st.info(cap_intake_guide.conditional_notice(group))
        st.caption("작성수준 판정 전에는 두 군의 자료를 함께 준비하세요. 목록은 작성요건에 맞춘 자료 요청용이며, "
                   "업로드만으로 서식이 완성되지는 않습니다.")
        cols = st.columns(2)
        cols[0].download_button("전체 준비자료 목록 한글(HWP)", cap_intake_guide.guidance_hwp(),
                                file_name="화학사고예방관리계획서_회사자료_요청목록.hwp",
                                mime="application/octet-stream", key="cap_request_hwp")
        try:
            pdf_content = cap_intake_guide.guidance_pdf()
        except RuntimeError as exc:
            st.warning(f"PDF를 만들지 못했습니다: {exc}")
        else:
            cols[1].download_button("전체 준비자료 목록 PDF", pdf_content,
                                    file_name="화학사고예방관리계획서_회사자료_요청목록.pdf",
                                    mime="application/pdf", key="cap_request_pdf")
        st.markdown("**우선 모을 파일**: 설비목록·설비대장(설비번호·공장·용량·최대보유량), 물질목록·제품별 SDS(CAS·함량), "
                    "운전조건표·설비사양서(압력·온도·단위), 공정설명서, 안전설비·비상대응 자료, 주변현황·평가 근거.")
        st.caption("서술형 계획서는 직접 쓰지 않아도 됩니다. 단답형 정보를 올리면 프로그램이 초안을 작성하고 ④에서 AI로 다듬을 수 있어요.")
        for label, rows in cap_intake_guide.grouped_checklist():
            st.markdown(f"#### {label}")
            st.dataframe([{"구역": cap_intake_guide.form_zone(r), "필요한 내용": r["label"],
                           "준비할 자료 예시": " / ".join(r["evidence"]) or r["details"]}
                          for r in rows], hide_index=True, width="stretch")
        st.caption("HWP 5.0과 HWPX는 읽을 수 있습니다. 암호화·구형 HWP가 열리지 않으면 한글에서 HWPX로 저장하세요. "
                   "사진으로 스캔된 PDF는 문자 인식과 원본 확인이 필요합니다.")
    uploaded = st.file_uploader("파일 선택 (여러 개 가능, 파일당 20MB 이하)",
                                type=["csv", "xlsx", "pdf", "docx", "hwpx", "hwp", "txt"], accept_multiple_files=True)
    selected, hints = {}, {}
    for index, file in enumerate(uploaded or []):
        digest, detected = _classify(file.name, file.getvalue())
        if detected:
            st.write(f"✅ {file.name} — {KIND_NAMES.get(detected, detected)}로 알아봤어요")
            selected[index] = detected
        else:
            # 파일 내용 기준 키: 다른 파일을 빼도 이미 고른 종류가 다른 파일로 옮겨 가지 않습니다
            selected[index] = st.selectbox(f"{file.name} — 자료 유형", ["reference", "facility", "material", "site"],
                                           format_func={"reference": "기타 작성 근거자료 (원본 보관·보완 검토)", "material": "물질 목록·MSDS",
                                                        "facility": "설비 목록·운전 자료",
                                                        "site": "사업장 일반정보·공정 설명"}.get,
                                           key=f"kind_{pid}_{digest[:16]}")
        if file.name.lower().endswith(DOCUMENT_TYPES):
            # 번호는 파일마다 따로 받습니다. 한 칸을 모든 파일에 쓰면 다른 파일의 값이 엉뚱한 설비로 붙습니다.
            hints[index] = st.text_input(f"↳ {file.name}이 설비 한 대·제품 하나의 문서라면 그 번호 (선택)",
                                         placeholder="예: RX-205, P-07", key=f"hint_{pid}_{digest[:16]}",
                                         help="사양서·MSDS처럼 표에 번호가 없는 문서일 때만 적으세요. "
                                              "적으면 문서 속 ‘운전압력(MPa): 0.35’ 같은 문장도 읽어요.").strip()
    if st.button("자료 읽기", type="primary", disabled=not uploaded, key="read_" + pid):
        before = cap_fact_status.snapshot(project)
        for index, file in enumerate(uploaded):
            try:
                if ew.replace_same_name(project, file.name, file.getvalue()):      # 고친 파일을 다시 올린 경우
                    st.session_state.setdefault("evidence_notes", []).append(
                        f"{file.name}: 예전에 올린 같은 이름의 파일을 새 파일로 바꿨어요.")
                if selected[index] == "reference":
                    ew.register_reference(project, file.name, file.getvalue())
                    save_attachment(project.project_id, file.name, file.getvalue(), note="작성 근거자료; 항목·값 표의 서식 연결 결과 확인")
                    save_project(project)
                    doc = next((d for d in ew.documents(project) if d["sha256"] == hashlib.sha256(file.getvalue()).hexdigest()), None)
                    scanned = bool(doc and doc.get("needs_ocr"))
                    linked = len(doc.get("links", [])) if doc else 0
                    st.session_state.setdefault("evidence_notes", []).append(
                        f"{file.name}: 글자가 없어 OCR이 필요합니다." if scanned else
                        f"{file.name}: 서식 항목 {linked}개를 연결했어요. 확인할 값과 충돌 여부를 읽기 결과에서 확인하세요." if linked else
                        f"{file.name}: 원본은 읽었지만 서식에 연결할 항목·값 표를 찾지 못했어요.")
                    continue
                count = ew.ingest(project, file.name, file.getvalue(), selected[index], hints.get(index, ""))
                save_attachment(project.project_id, file.name, file.getvalue(), note="공통정보 추출 원문")
                save_project(project)
                st.session_state.setdefault("evidence_notes", []).append(
                    f"{file.name}: 값 {count}개를 찾았어요." if count else
                    f"{file.name}: 값을 찾지 못했어요. 스캔본이면 글자를 읽을 수 없고, 표에 설비번호·제품코드 같은 항목 이름이 있어야 해요.")
            except Exception as exc:
                why = exc if isinstance(exc, ValueError) else "파일 형식을 확인해 주세요"
                st.session_state.setdefault("evidence_notes", []).append(f"{file.name}: 읽지 못했어요 ({why}). 다른 자료는 그대로예요.")
        delta = cap_fact_status.change(before, cap_fact_status.snapshot(project))
        st.session_state["evidence_change"] = "이번에 올린 파일로 " + cap_fact_status.change_text(delta)
        st.session_state["evidence_goto"] = 2
        st.rerun()

    docs = ew.documents(project)
    if docs:
        st.subheader("읽은 자료")
        st.caption("파일마다 어디를 읽었고, 무엇을 못 읽었으며 왜 그런지 보여 줘요.")
        by_doc = {}
        for fact in ew.graph_facts(project):
            by_doc.setdefault(fact["sha256"], []).append(fact)
        reasons = {f["id"]: g["reason"] for g in found["problems"] for f in g["facts"]}
        for doc in docs:
            _reading_report(project, doc, by_doc.get(doc["sha256"], []), found["names"], reasons)
        _next_button(2, pid, "다음: 파일별 보완 요청 →")
    st.divider()
    st.markdown("**연습용 가상 회사 자료**")
    st.download_button("실제와 비슷한 큰 가상자료 받기", demo_company.combined_demo_zip(),
                       file_name="synthetic_company_evidence_large_combined.zip", mime="application/zip", key="demo_combined")
    st.caption("제품·설비 목록과 운전조건, HWPX 사양서, 스캔본, 두 공장의 중복 설비번호, 혼합물 성분, "
               "구버전·개정 자료의 충돌을 한 묶음에 넣었습니다. ZIP의 01~12번 회사자료를 한 번에 올리고 "
               "README와 answer_key.json으로 오류·누락을 확인하세요. 실제 주소·주변시설 자료는 포함하지 않았습니다.")


def _reading_report(project, doc, facts, names, reasons) -> None:
    """파일 하나의 읽기 결과: 읽은 표, 쓴 열·못 쓴 열, 건너뛴 줄, 쓸 수 없는 칸과 그 이유."""
    pid, sha = project.project_id, doc["sha256"]
    unusable = [f for f in facts if f["id"] in reasons]
    skipped = sum(t.get("skipped_count", 0) for t in doc.get("tables", []))
    if doc.get("needs_reading"):
        icon = "📎" if doc.get("kind") == "reference" and not doc.get("needs_ocr") else "⚠️"
        st.write(f"{icon} **{doc['name']}** — {doc.get('problem') or '읽을 수 있는 값을 찾지 못했어요.'}")
    else:
        parts = [f"값 {len(facts)}개"]
        if doc.get("unmapped_columns"):
            parts.append(f"못 쓴 열 {len(doc['unmapped_columns'])}개")
        if skipped:
            parts.append(f"건너뛴 줄 {skipped}개")
        if unusable:
            parts.append(f"그대로 쓸 수 없는 칸 {len(unusable)}개")
        st.write(f"📄 **{doc['name']}** — " + " · ".join(parts))
    with st.expander("읽기 결과 보기"):
        if st.button("이 파일 빼기", key=f"remove_{pid}_{sha[:12]}",
                     help="잘못 올린 파일이나 예전 판을 빼면 그 파일에서 읽은 값도 함께 빠져요."):
            ew.remove_document(project, sha)
            _save(project, f"{doc['name']}을(를) 뺐어요. 이 파일에서 읽은 값도 빠졌어요.")
        for link in doc.get("links", []):           # 근거자료의 항목·값 표에서 바로 연결한 서식 칸
            record = project.get_field(link["key"])
            if record is None:
                continue
            source = f"{link['location']} · {link['label']}: {link['value']}"
            if record.status == "HOLD" or (not cap_evidence_links.linked(record) and str(record.value) != str(link["value"])):
                st.warning(f"{source} — 다른 자료와 값이 다릅니다. 맞는 값으로 파일을 고쳐 다시 올려 주세요.")
            else:
                st.write(f"✅ {source} — 초안에 넣음")
        for table in doc.get("tables", []):
            place = "" if table["location"] == "CSV" else f"‘{table['location']}’ "
            if table.get("kind") == "site" and table.get("columns"):
                st.markdown(f"- {place}표: 항목·값 표로 보고 {len(table['columns'])}개 항목을 읽었어요: "
                            + ", ".join(c["header"] for c in table["columns"]))
                continue
            if table.get("header_row") is None:
                st.markdown(f"- {place}표: 읽지 않음 — {table.get('problem', '항목 이름 줄을 찾지 못함')}")
                continue
            used = [c for c in table.get("columns", []) if c["field"]]
            st.markdown(f"- {place}표: {table['header_row']}번째 줄을 항목 이름으로 보고 아래 {table['rows']}줄을 읽었어요. "
                        "쓴 열: " + ", ".join(c["header"] + ("(번호)" if c["field"] == "id" else "") for c in used))
            for row in table.get("skipped", [])[:10]:
                st.caption(f"　건너뛴 줄: {row['row']}번째 줄 ‘{row['text']}’ — {row['reason']}")
            if table.get("skipped_count", 0) > 10:
                st.caption(f"　건너뛴 줄 {table['skipped_count'] - 10}개 더 있음")
        if doc.get("unmapped_columns"):
            st.markdown("**못 쓴 열** — 프로그램이 모르는 항목 이름이에요. 필요한 열이면 무엇인지 골라 주세요. 한 번 고르면 같은 이름의 열은 모두 그렇게 읽어요.")
            choices = {}
            for header in doc["unmapped_columns"]:
                choices[header] = st.selectbox(f"‘{header}’ 열은", ["쓰지 않음"] + list(ew.LABELS), format_func=lambda k: k if k == "쓰지 않음" else ew.LABELS[k],
                                               key=f"col_{pid}_{sha[:12]}_{header}")
            picked = {h: f for h, f in choices.items() if f != "쓰지 않음"}
            if st.button("지정하고 다시 읽기", key=f"col_ok_{pid}_{sha[:12]}", disabled=not picked):
                _remap_columns(project, picked)
        if unusable:
            st.markdown("**그대로 쓸 수 없는 칸** — 원본 파일을 수정해 다시 올려 주세요.")
            st.dataframe([{"읽은 곳": _where(f), "항목": _name(f["field"]), "적힌 글자": f["raw"], "이유": reasons[f["id"]]}
                          for f in unusable[:200]], hide_index=True, width="stretch")
        if facts:
            st.markdown("**찾은 값**")
            st.dataframe([{"설비·물질": names(f["entity"]), "항목": _name(f["field"]), "값": _value(f["field"], f["value"]) + _raw_note(f),
                           "위치": _where(f)} for f in facts[:300]], hide_index=True, width="stretch")
            if len(facts) > 300:
                st.caption(f"앞 300개만 보여 줘요 (전체 {len(facts)}개).")


def _remap_columns(project, picked) -> None:
    """모르는 머리글을 항목으로 지정하고, 그 머리글이 있던 파일을 보관한 원본에서 다시 읽습니다."""
    targets = set()
    for header, field in picked.items():
        targets.update(ew.learn_column(project, header, field))
    missing = []
    for sha in targets:
        content = load_attachment(project.project_id, sha)
        name = next((d["name"] for d in ew.documents(project) if d["sha256"] == sha), sha[:8])
        if content is None:
            missing.append(name)
            continue
        ew.reingest(project, sha, content)
    note = f"열 {len(picked)}개를 지정하고 파일 {len(targets) - len(missing)}개를 다시 읽었어요."
    if missing:
        note += " 원본이 없어 다시 읽지 못한 파일: " + ", ".join(missing) + " (같은 파일을 다시 올려 주세요)"
    _save(project, note)


# ---------------------------------------------------------------- ② 파일별 보완 요청

def _correction_rows(project, found) -> list[dict]:
    """파일·위치·항목·수정 지시를 한 줄씩 적는다. 추정된 원본은 쓰지 않는다."""
    rows = []

    def add(source, item, detail, action):
        rows.append({"파일·위치": source, "항목": item, "확인된 문제": detail, "수정 요청": action})

    for doc in ew.documents(project):
        if doc.get("needs_reading"):
            is_reference = doc.get("kind") == "reference" and not doc.get("needs_ocr")
            add(doc["name"], "서식 값 연결" if is_reference else "문서 읽기",
                doc.get("problem") or "값을 연결하지 못했습니다.",
                "서식 항목 이름(예: 대표자, 사업자 등록번호)과 값을 2열 표로 적어 다시 올리세요." if is_reference else
                "스캔본은 OCR을 적용하세요. 항목명·번호를 확인해 원본을 다시 제출하세요.")
        for link in doc.get("links", []):
            record = project.get_field(link["key"])
            if record and (record.status == "HOLD" or
                           (not cap_evidence_links.linked(record) and str(record.value) != str(link["value"]))):
                add(f"{doc['name']} · {link['location']}", link["label"],
                    "같은 항목의 값이 다른 자료와 다릅니다.",
                    "맞는 값을 원본에서 확인하고 잘못된 파일을 고쳐 다시 올려 주세요.")
        for table in doc.get("tables", []):
            for skipped in table.get("skipped", []):
                add(f"{doc['name']} · {table['location']} {skipped['row']}행", "설비·제품 번호",
                    skipped["reason"], "설비번호 또는 제품코드를 원본 행에 기재한 뒤 다시 올려 주세요.")
        for column in doc.get("unmapped_columns", []):
            add(doc["name"], column + " 열", "알 수 없는 항목 이름", "열 이름과 뜻·단위를 확인해 원본을 수정한 뒤 다시 올려 주세요.")
    for item in found["conflicts"]:
        facts = item["slot"]["facts"]
        add(" / ".join(dict.fromkeys(_where(f) for f in facts)),
            f"{found['names'](item['entity'])} · {_name(item['field'])}",
            "자료마다 값이 다릅니다: " + ", ".join(_value(item["field"], f["value"]) for f in facts[:5]),
            "현재 적용되는 개정본을 확인하고 파일의 값을 바로잡아 다시 올려 주세요. 확인 전에는 자동 확정되지 않습니다.")
    for group in found["problems"]:
        fact = group["facts"][0]
        add(_where(fact), _name(group["field"]), f"‘{group['raw']}’: {group['reason']}",
            "숫자·단위·표기와 적용 대상을 원본에서 수정한 뒤 다시 올려 주세요.")
    for entity, fields in found["missing"].items():
        add("설비대장·운전조건표 (해당 파일 위치 미확인)", found["names"](entity),
            "자료에서 " + ", ".join(_name(field) for field in fields) + " 항목을 찾지 못했습니다.",
            "해당 설비번호의 누락 열을 원본에 기재해 올려 주세요.")
    for question in found["rank"]:
        add("설비대장·물질목록 (해당 파일 위치 미확인)", found["names"](question["entity"]),
            f"시나리오 우선순위에 영향을 줄 {_name(question['field'])} 값을 확인하지 못했습니다.",
            "해당 물질·설비의 값을 단위와 함께 원본에 기재해 올려 주세요.")
    for item in found["held"]:
        fact = item["slot"]["facts"][0]
        add(_where(fact), _name(item["field"]), "출처·단위·법적 판단용 값의 확인이 필요합니다.",
            "원본과 현장 적용 여부를 확인하고 최신본을 다시 올리거나 아래 확인 절차를 이용하세요.")
    narrative_keys = cap_fact_drafting.input_requirement_keys(project.cap_group)
    for req in build_intake_catalog(project):
        if req.requirement_key in narrative_keys:
            continue  # 문장 제출을 요구하지 않음: 단답형 누락·충돌은 사실 표에서 안내
        if req.system not in {"CAP", "COMMON"} or req.coverage_status in {"확인", "해당 없음"}:
            continue
        missing = ", ".join(req.missing_labels or (req.label,))
        add(" / ".join(req.suggested_evidence) or "근거 파일 미지정", req.label,
            f"작성 항목에 {missing} 값이 아직 연결되지 않았습니다. 업로드한 자료에 있어도 자동 연결되지 않았을 수 있습니다.",
            "해당 근거자료와 최신본·적용범위를 확인해 파일에 적어 다시 올려 주세요.")
    return rows


KIND_NAMES = {"material": "물질 목록·SDS", "facility": "설비 목록·운전 자료", "site": "사업장 일반정보·공정 설명",
              "detector": "가스감지기 명세", "target": "주변 보호대상 조사표",
              "mixed": "여러 종류가 든 묶음 파일(시트마다 따로 읽음)"}
DOC_NAMES = {"CAP": "화학사고예방관리계획서", "PSM": "공정안전보고서"}


def _coverage_panel(project, found) -> None:
    """보완 요청을 필요한 사실 표 한 곳에 모읍니다."""
    st.markdown("**화학사고예방관리계획서에 필요한 사실**")
    st.caption("고칠 점을 확인하고 ①에서 수정한 파일을 같은 이름으로 다시 올리세요. 수정 내용을 따로 적을 필요는 없어요.")
    rows = cap_fact_status.fact_rows(project, docs=("CAP",))
    visible = []
    filenames = [d["name"] for d in ew.documents(project)]
    generated = cap_fact_drafting.generated_fact_ids(project.cap_group)
    for row in rows:
        if row["_id"] in generated:
            continue
        if not row["_company"]:
            continue
        source = row["출처"]
        files = [name for name in filenames if name in source]
        visible.append({"상태": row["상태"], "사실": row["사실"], "쓰이는 곳": row["쓰이는 곳"],
                        "올린 파일": " / ".join(files), "고칠 점": row["고칠 점"]})
    for row in _correction_rows(project, found):
        files = [name for name in filenames if name in row["파일·위치"]]
        entry = {"상태": "확인", "사실": row["항목"], "쓰이는 곳": "",
                 "올린 파일": " / ".join(files),
                 "고칠 점": row["확인된 문제"] + " " + row["수정 요청"]}
        if not any(r["사실"] == entry["사실"] and r["고칠 점"] == entry["고칠 점"] for r in visible):
            visible.append(entry)
    if project.cap_in_scope:
        from engine.stage2 import report_export
        try:
            state = report_export.evaluate(project, "CAP")
            for issue in (*state.text_issues, *state.manual_issues):
                if issue.status == "PASS":
                    continue
                sources = []
                for key in issue.field_keys:
                    record = project.get_field(key)
                    if record:
                        sources.extend(ref.source_name for ref in record.evidence if ref.source_name in filenames)
                entry = {"상태": "보완", "사실": issue.legal_item, "쓰이는 곳": "",
                         "올린 파일": " / ".join(dict.fromkeys(sources)), "고칠 점": issue.message}
                if not any(r["사실"] == entry["사실"] and r["고칠 점"] == entry["고칠 점"] for r in visible):
                    visible.append(entry)
        except Exception:
            st.error("문서 검증 결과를 확인하지 못했어요. 보완 요청이 전부 확인된 상태는 아닙니다.")
    st.dataframe(visible, hide_index=True, width="stretch")
    _template_download(project, project.cap_group)


def _template_download(project, group: str) -> None:
    st.caption("빈칸 전용 엑셀 양식의 값 칸을 예시 옆에서 채운 뒤, 파일명 그대로 ①에 올리세요. 같은 이름의 이전 파일은 자동 교체됩니다.")
    st.download_button("빈칸 전용 엑셀 양식 내려받기", cap_upload_template.build(project, group=group, docs=("CAP",)),
                       file_name=cap_upload_template.FILENAME, key="template_" + project.project_id,
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


def _step_questions(project, found) -> None:
    pid = project.project_id
    if not ew.documents(project):
        st.info("먼저 ① 자료 올리기에서 자료를 올려 주세요.")
        return
    _coverage_panel(project, found)
    _next_button(3, pid, "다음: 시나리오 후보 보기 →")


# ---------------------------------------------------------------- ③ 시나리오 후보

def _step_scenarios(project, found, triage) -> None:
    pid, names = project.project_id, found["names"]
    linked = [r for r in triage["rows"] if r["linked"]]
    st.dataframe([{"순서": r["rank"], "설비": names(r["facility"]), "물질": names(r["material"]),
                   "인식한 파일": " / ".join(dict.fromkeys(source["document"] for source in r["sources"].values() if source)),
                   "비교 점수": round(r["score"], 1)} for r in linked], hide_index=True, width="stretch")
    _next_button(4, pid, "다음: 작성·내려받기 →")


# ---------------------------------------------------------------- ④ 작성·내려받기


def _step_export(project, found) -> None:
    """확인한 값을 작성자료로 보내고, 문서별로 남은 일을 한곳에서 보여 줍니다(여기만 따라가면 되도록)."""
    st.caption("읽은 자료로 초안을 작성합니다. 부족한 자료는 ②에서 확인하세요.")
    if st.button("작성하기", type="primary", key="write_" + project.project_id):
        _auto_publish(project)
        st.success("초안을 작성했어요. 아래에서 내려받으세요.")
    st.caption("서술형 초안 " + str(sum(bool(i.company_text or i.draft) for system in cap_fact_drafting.systems(project) for i in cap_fact_drafting.items(project, system))) + "개 작성됨")
    _narrative_drafts(project)
    from ui.report_export_panel import render_workspace_download
    render_workspace_download(project)


def _auto_publish(project) -> None:
    """회사 파일에서 읽은 값을 작성자료(초안)에 자동으로 반영합니다. 사람의 승인 단계는 없습니다.
    서술형 항목도 근거 사실이 있으면 규칙 초안을 바로 만들어 둡니다(AI 다듬기는 ④에서 따로)."""
    changed = False
    # 파일을 새로 올리면 이전에 반영한 값이 보류로 바뀌므로, 값이 같아도 확정 상태가 아니면 다시 반영합니다.
    if ew.needs_publish(project):
        try:
            ew.publish(project, replace_existing=True)
            changed = True
        except ValueError:
            pass
    if project.cap_in_scope or project.psm_in_scope:
        try:
            changed = cap_fact_drafting.refresh_rule_drafts(project) > 0 or changed
        except Exception:          # 서술형 초안 문제로 화면이 멈추지 않게
            pass
        try:                       # 사고시나리오 결과도 새 파일로 다시 계산(‘사고시나리오 결과’ 화면에서 확인)
            from engine.stage2 import scenario_pipeline

            if scenario_pipeline.needs_refresh(project):
                scenario_pipeline.refresh(project)
                changed = True
        except Exception:
            pass
    if changed:
        save_project(project)


def _narrative_drafts(project) -> None:
    """사전관리방침·비상대응계획 서술형: 회사 파일의 사실로 쓴 초안 현황과 다시 만들기."""
    systems = cap_fact_drafting.systems(project)
    if not systems:
        return
    pid = project.project_id
    tables = [(system, cap_fact_drafting.rows(project, system)) for system in systems]
    if not any(rows for _, rows in tables):
        return
    use_ai = st.checkbox("AI를 이용해서 작성하기 (서술형만)", key="fact_ai_" + pid)
    client = None
    if use_ai:
        from ui.narrative_panel import _local_config

        config, probe, build = _local_config("fact_" + pid)
        if probe is not None and probe.ready:
            client = build(config)
        else:
            st.warning("로컬 AI 연결을 확인해 주세요.")
    progress_key = "narrative_progress_" + pid
    previous = st.session_state.get(progress_key)
    if previous and previous[1]:
        st.progress(previous[0] / previous[1], text=f"서술형 {previous[0]}/{previous[1]}개 완료 (100%)")
    if st.button("AI로 서술형 작성하기" if use_ai else "서술형 작성하기", key="fact_drafts_" + pid, disabled=use_ai and client is None):
        bar = st.progress(0, text="작성할 서술형 항목을 확인하고 있어요.")

        def report_progress(done, total, label):
            percent = round(done / total * 100) if total else 0
            text = f"서술형 {done}/{total}개 완료 ({percent}%)"
            if label:
                text += f" · {done + 1}번째 작성 중: {label}"
            bar.progress(done / total if total else 0, text=text)

        results = cap_fact_drafting.generate(project, client, refresh=True, on_progress=report_progress)
        st.session_state[progress_key] = (len(results), len(results))
        save_project(project)
        checks = sum(r["checks"] for r in results)
        st.session_state.setdefault("evidence_notes", []).append(
            (f"서술형 초안 {len(results)}개를 만들었어요." + (f" ‘[확인 필요]’ {checks}곳을 채워 주세요." if checks else ""))
            if results else "작성할 서술형이 없어요. 완성 문서는 그대로 사용하며, 근거가 없는 항목은 ②에서 필요한 자료를 확인해 주세요.")
        st.rerun()


# ---------------------------------------------------------------- 화면

st.set_page_config(page_title="사업장 업무", page_icon="📂", layout="wide")
st.title("화학사고예방관리계획서 자료 정리")
st.caption("회사 자료를 올리면 값을 찾아 정리하고, 파일별 수정·확인 요청을 보여 줍니다.")
_active = _project_header()
_triage = scenario_triage.evaluate(_active)
_found = _collect(_active, _triage)
_auto_publish(_active)
_status_line(_active, _found)
_change = st.session_state.pop("evidence_change", None)
if _change:
    (st.warning if "새 충돌 0개" not in _change and "새 충돌은 없어요" not in _change else st.info)(_change)
for _note in st.session_state.pop("evidence_notes", []):
    (st.error if "읽지 못" in _note else st.warning if "찾지 못" in _note else st.success)(_note)

_step_key = "evidence_step_" + _active.project_id
if "evidence_goto" in st.session_state:
    st.session_state[_step_key] = st.session_state.pop("evidence_goto")
if _step_key not in st.session_state:
    st.session_state[_step_key] = 1 if not ew.documents(_active) else (2 if _correction_rows(_active, _found) else 3)
# 단계 이름은 고정합니다: 이름이 바뀌면 위젯이 새로 만들어져 보던 단계가 처음으로 돌아갈 수 있습니다.
_step = st.radio("단계", list(STEPS), key=_step_key, horizontal=True, label_visibility="collapsed", format_func=STEPS.get)
st.divider()
if _step == 1:
    _step_upload(_active, _found)
elif _step == 2:
    _step_questions(_active, _found)
elif _step == 3:
    _step_scenarios(_active, _found, _triage)
else:
    _step_export(_active, _found)
