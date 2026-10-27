"""사업장 업무 화면: 신입사원도 따라올 수 있게 단계별로 안내합니다.

① 자료 올리기 → ② 파일별 보완 요청 → ③ 시나리오 후보 → ④ 보내기·진행 현황

화면에는 사람 말만 씁니다. 파일 해시·내부 식별자·JSON 같은 기록은 ④의 ‘검토·감사용 기록’에만 둡니다.
"""
from __future__ import annotations

import ast
import hashlib
import json
import operator
import re
from datetime import date

import streamlit as st

from engine.stage2 import demo_company, evidence_llm, scenario_triage, scenario_workup, cap_intake_guide
from engine.stage2.intake import build_intake_catalog
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import delete_all_projects, list_projects, load_attachment, load_project, save_attachment, save_project

STEPS = {1: "① 자료 올리기", 2: "② 파일별 보완 요청", 3: "③ 시나리오 후보", 4: "④ 보내기·진행 현황"}
MAX_CARDS = 30
DOCUMENT_TYPES = (".docx", ".pdf", ".hwpx", ".txt")
MISSING_FIELDS = ("product", "inventory", "pressure", "temperature", "facility_type", "substance_state")

# 신입사원이 모를 수 있는 항목마다 한 줄 설명
HELP = {
    "product": "이 설비가 다루는 제품이에요. 물질 목록에 있는 제품 중에서 고르세요.",
    "inventory": "이 설비 안에 한 번에 들어 있을 수 있는 물질의 최대 양이에요.",
    "pressure": "평소 운전할 때의 압력이에요. 운전 기록이나 설비 사양서에서 확인하세요. kPa로 적혀 있으면 1,000으로 나눠 MPa로 적어요.",
    "temperature": "평소 운전할 때의 온도예요. 운전 기록이나 설비 사양서에서 확인하세요.",
    "facility_type": "설비가 하는 일이에요. 저장탱크는 물질을 담아 두는 탱크, 제조·사용시설은 반응기·혼합기처럼 물질을 쓰거나 만드는 설비, "
                     "보관시설은 드럼·용기를 쌓아 두는 창고예요.",
    "substance_state": "설비 안에서 물질이 어떤 상태인지예요. 대부분의 용제·산은 액체예요.",
    "capacity": "설비의 설계 용량이에요. 1 m³ = 1,000 L예요.",
    "concentration": "제품 안에 이 물질이 들어 있는 비율이에요. MSDS 3번 항목(구성성분)에 있어요.",
    "cas": "물질마다 붙는 고유 번호예요. MSDS 3번 항목에 있어요.",
    "density": "물보다 무거우면 1보다 커요. MSDS 9번 항목(물리·화학적 특성)에 있어요.",
    "process_type": "설비 안에서 물질이 반응하면 ‘반응’, 섞기만 하면 ‘단순혼합’, 그대로면 ‘변화없음’이에요.",
}

TRIAGE_STATE = {"보류": "값이 더 필요해요", "잠정": "자료 값으로 계산 (확인 전)", "예비 검토": "채운 값으로 계산"}
VALUE_STATE = {"confirmed": "채운 값", "provisional": "자료에서 읽은 값 (확인 전)",
               "assumed": "자료에 없어 임시로 넣은 값", "conflict": "자료마다 달라 큰 값을 임시로 사용", "invalid": "읽을 수 없어 임시값 사용"}


# ---------------------------------------------------------------- 사람 말로 바꾸기

def _unit(field: str) -> str:
    match = re.search(r"\(([^)]+)\)$", ew.LABELS[field])
    return match.group(1) if match else ""


def _name(field: str) -> str:
    return re.sub(r"\s*\([^)]*\)$", "", ew.LABELS[field])


def _j(word: str, with_batchim: str, without: str) -> str:
    """받침에 맞는 조사를 붙입니다 (용량이 / 운전온도가)."""
    last = str(word)[-1:] if word else ""
    has = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return f"{word}{with_batchim if has else without}"


def _q(word: str, with_batchim: str, without: str) -> str:
    """따옴표로 감싼 원문 뒤 조사 (‘상압’이라고 / ‘가스’라고)."""
    return f"‘{word}’" + _j(str(word), with_batchim, without)[len(str(word)):]


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


def _plain_reason(reason: str) -> str:
    if "충돌" in reason:
        return "자료마다 값이 달라요"
    if "단위가 없음" in reason:
        return "자료에 단위가 적혀 있지 않아요"
    if "문장 또는 AI" in reason:
        return "표가 아닌 문장(또는 AI)에서 찾은 값이에요"
    if "지정한 번호" in reason:
        return "번호 없는 문서에서 지정한 번호로 찾은 값이에요"
    if "이름으로 연결" in reason:
        return "설비번호·제품코드 없이 이름만으로 찾은 값이에요"
    if "수식" in reason:
        return "엑셀 계산식의 결과값이에요"
    if "병합" in reason:
        return "합쳐진 칸(병합 셀)에서 읽은 값이에요"
    return reason


_SAFE_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def _formula_result(raw: str):
    """‘=1500+500’처럼 숫자와 사칙연산만 있는 엑셀 식이면 계산한 값을 제안합니다. 셀 참조가 있으면 None."""
    text = str(raw).strip().lstrip("=").replace(",", "")
    if not text or not re.fullmatch(r"[\d+\-*/(). ]+", text):
        return None

    def walk(node):
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_OPS:
            return _SAFE_OPS[type(node.op)](walk(node.left), walk(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            return -walk(node.operand)
        raise ValueError
    try:
        return float(walk(ast.parse(text, mode="eval")))
    except (ValueError, SyntaxError, ZeroDivisionError, TypeError):
        return None


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


def _final_check(project) -> list:
    """보내기 전에 사람이 한 번은 봐야 하는 자동 기입값: 법적 계산 입력 + 순위를 바꾸는 값."""
    items = {s["key"]: s for s in ew.unreviewed_legal(project)}
    items.update({s["key"]: s for s in ew.critical_auto(project)})
    return list(items.values())


# ---------------------------------------------------------------- 공통

def _save(project, note: str | None = None) -> None:
    save_project(project)
    if note:
        st.session_state.setdefault("evidence_notes", []).append(note)
    st.rerun()


def _confirm_manual(project, entity, field, value, reason) -> None:
    try:
        ew.add_manual(project, entity, field, value, reason or f"담당자 직접 입력 ({date.today().isoformat()})", confirm=True)
    except ValueError as exc:
        st.error(f"저장하지 못했어요: {exc}")
        return
    _save(project, f"{_name(field)} 값을 저장했어요.")


def _value_input(field: str, key: str, label: str | None = None):
    label = label or f"{_name(field)}" + (f" ({_unit(field)})" if _unit(field) else "")
    if field in ew.CHOICES:
        choice = st.selectbox(label, ["모름"] + list(ew.CHOICES[field]), key=key, help=HELP.get(field))
        return "" if choice == "모름" else choice
    return st.text_input(label, key=key, placeholder="예: 2000" if field == "inventory" else "", help=HELP.get(field)).strip()


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
        st.caption("회사에 그대로 전달할 자료 요청 목록입니다. 작성수준을 아직 확인하지 않았다면 1·2군 후보 항목을 함께 보여 줍니다. "
                   "업로드만으로 서식이 완성되지는 않으며, 읽지 못한 자료는 보완 요청에 남습니다.")
        cols = st.columns(2)
        cols[0].download_button("전체 준비자료 목록 TXT", cap_intake_guide.guidance_text(group),
                                file_name="화학사고예방관리계획서_회사자료_요청목록.txt", mime="text/plain", key="cap_request_txt")
        cols[1].download_button("전체 준비자료 목록 한글(HWPX)", cap_intake_guide.guidance_hwpx(group),
                                file_name="화학사고예방관리계획서_회사자료_요청목록.hwpx",
                                mime="application/hwp+zip", key="cap_request_hwpx")
        st.markdown("**우선 모을 파일**: 설비목록·설비대장(설비번호·공장·용량·최대보유량), 물질목록·제품별 SDS(CAS·함량), "
                    "운전조건표·설비사양서(압력·온도·단위), 공정설명서, 안전설비·비상대응 자료, 주변현황·평가 근거.")
        rows = cap_intake_guide.checklist(group)
        st.dataframe([{"구역": r["section"], "필요한 내용": r["label"],
                       "준비할 자료 예시": " / ".join(r["evidence"]) or r["details"],
                       "작성수준": "·".join(r["levels"])} for r in rows], hide_index=True, width="stretch")
        st.caption("HWPX는 읽을 수 있습니다. 옛 한글 HWP는 한글에서 HWPX 또는 텍스트 PDF로 다시 저장하세요. "
                   "사진으로 스캔된 PDF는 문자 인식과 원본 확인이 필요합니다.")
    uploaded = st.file_uploader("파일 선택 (여러 개 가능, 파일당 20MB 이하)",
                                type=["csv", "xlsx", "pdf", "docx", "hwpx", "hwp", "txt"], accept_multiple_files=True)
    selected, hints = {}, {}
    for index, file in enumerate(uploaded or []):
        if file.name.lower().endswith(".hwp"):
            st.error(f"{file.name}: 이 파일은 구형 HWP라 읽지 못합니다. 한글에서 HWPX 또는 텍스트 PDF로 저장해 다시 올려 주세요.")
            selected[index] = "unsupported"
            continue
        digest, detected = _classify(file.name, file.getvalue())
        if detected:
            st.write(f"✅ {file.name} — {'물질 목록·MSDS' if detected == 'material' else '설비 목록·운전 자료'}로 알아봤어요")
            selected[index] = detected
        else:
            # 파일 내용 기준 키: 다른 파일을 빼도 이미 고른 종류가 다른 파일로 옮겨 가지 않습니다
            selected[index] = st.selectbox(f"{file.name} — 자료 유형", ["reference", "facility", "material"],
                                           format_func={"reference": "기타 작성 근거자료 (원본 보관·보완 검토)", "material": "물질 목록·MSDS",
                                                        "facility": "설비 목록·운전 자료"}.get,
                                           key=f"kind_{pid}_{digest[:16]}")
        if file.name.lower().endswith(DOCUMENT_TYPES):
            # 번호는 파일마다 따로 받습니다. 한 칸을 모든 파일에 쓰면 다른 파일의 값이 엉뚱한 설비로 붙습니다.
            hints[index] = st.text_input(f"↳ {file.name}이 설비 한 대·제품 하나의 문서라면 그 번호 (선택)",
                                         placeholder="예: RX-205, P-07", key=f"hint_{pid}_{digest[:16]}",
                                         help="사양서·MSDS처럼 표에 번호가 없는 문서일 때만 적으세요. "
                                              "적으면 문서 속 ‘운전압력(MPa): 0.35’ 같은 문장도 읽어요.").strip()
    if st.button("자료 읽기", type="primary", disabled=not uploaded, key="read_" + pid):
        for index, file in enumerate(uploaded):
            try:
                if selected[index] == "unsupported":
                    continue
                if selected[index] == "reference":
                    ew.register_reference(project, file.name, file.getvalue())
                    save_attachment(project.project_id, file.name, file.getvalue(), note="작성 근거자료; 자동 추출·서식 연결 미완료")
                    save_project(project)
                    st.session_state.setdefault("evidence_notes", []).append(
                        f"{file.name}: 원본만 보관했어요. 서식 값으로 연결되지 않았습니다. 파일별 보완 요청을 확인하세요.")
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
    cols = st.columns(3)
    cols[0].download_button("작은 자료 (파일 4개)", ew.demo_zip(), file_name="synthetic_company_evidence.zip",
                            mime="application/zip", key="demo_small")
    cols[0].caption("처음 써 볼 때. 설비 4대, 제품 2개, 일부러 넣은 문제 2개.")
    cols[1].download_button("실제와 비슷한 큰 자료 (파일 7개)", demo_company.large_demo_zip(),
                            file_name="synthetic_company_evidence_large.zip", mime="application/zip", key="demo_large")
    cols[1].caption("설비 40대, 제품 26개. 여러 시트·숨김 시트·병합 칸·단위가 다른 시트·옛 자료·한글 사양서·스캔본과 "
                    "일부러 넣은 문제 30가지. 정답표(answer_key.json)가 들어 있어요.")
    from engine.stage2 import demo_full_company

    with cols[2]:
        real_address = st.text_input("실제 주소로 해 보기 (선택)", key="demo_full_address",
                                     placeholder="예: 도로명주소",
                                     help="넣으면 이 가상 회사가 그 주소에 있다고 보고 자료를 만들어요. 별지 제8호 주변 보호대상은 "
                                          "지어낸 목록 대신 그 주소로 지도 조회를 해서 채워요(브이월드 키 필요). 회사·설비 값은 그대로 허구예요.")
        complex_name = st.text_input("그 주소의 산업단지 (선택)", key="demo_full_complex", placeholder="없으면 비워 두세요 → 해당 없음",
                                     disabled=not real_address.strip())
        package = demo_full_company.full_demo_zip(real_address, complex_name if real_address.strip() else "")
        count = len(demo_full_company.files(real_address, complex_name if real_address.strip() else ""))
        st.download_button(f"계획서 끝까지 연습 자료 (파일 {count}개)", package,
                           file_name="synthetic_company_full_plan.zip", mime="application/zip", key="demo_full")
        st.caption("제품 3개·설비 4대의 가상 회사. 회사 근거자료와 정답표가 들어 있습니다. "
                   "현재 자동 추출 범위는 일부 공통정보뿐입니다. 파일별 보완 요청과 서식 미연결 항목을 확인하세요."
                   + (" 주소를 넣었으니 별지 제8호는 실제 지도 조회로 채워요." if real_address.strip() else ""))
    with st.expander("회사 자료처럼 복잡한 파일로 별도 시험하기"):
        st.caption("두 공장의 같은 설비번호, 한 제품의 여러 CAS 성분, 구버전·개정 자료의 충돌을 넣었어요. "
                   "위 계획서 작성용 자료와 섞지 말고 새 연습 사업장에 올리세요. 정답표와 비교해 누락·합침을 확인합니다.")
        st.download_button("현장형 예외 자료와 정답표 받기", demo_full_company.stress_demo_zip(),
                           file_name="synthetic_company_stress_audit.zip", mime="application/zip", key="stress_audit")
    _local_llm(project)


def _reading_report(project, doc, facts, names, reasons) -> None:
    """파일 하나의 읽기 결과: 읽은 표, 쓴 열·못 쓴 열, 건너뛴 줄, 쓸 수 없는 칸과 그 이유."""
    pid, sha = project.project_id, doc["sha256"]
    unusable = [f for f in facts if f["id"] in reasons]
    skipped = sum(t.get("skipped_count", 0) for t in doc.get("tables", []))
    if doc.get("needs_reading"):
        st.write(f"⚠️ **{doc['name']}** — {doc.get('problem') or '읽을 수 있는 값을 찾지 못했어요.'}")
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
        for table in doc.get("tables", []):
            place = "" if table["location"] == "CSV" else f"‘{table['location']}’ "
            if table.get("header_row") is None:
                st.markdown(f"- {place}표: 읽지 못함 — {table.get('problem', '항목 이름 줄을 찾지 못함')}")
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


def _local_llm(project) -> None:
    with st.expander("고급: 서술형 문서에서 AI로 값 찾기 (선택)"):
        readable = {d["sha256"]: d for d in ew.documents(project) if d.get("hint") and any(p.get("text", "").strip() for p in d.get("passages", []))}
        st.caption("내 컴퓨터에서 돌아가는 AI만 써요. 문서를 밖으로 보내지 않아요. AI가 찾은 값은 원문과 맞는지 검사하고, "
                   "그래도 사람이 하나씩 확인하기 전에는 쓰지 않아요.")
        if not readable:
            st.info("번호가 없는 문서 칸에 설비번호·제품코드를 적고 PDF·워드·한글·TXT 문서를 먼저 올려 주세요.")
            return
        doc_id = st.selectbox("읽을 문서", list(readable), format_func=lambda k: readable[k]["name"])
        if st.button("AI로 값 찾기"):
            try:
                from engine.stage2.local_llm import build_local_llm_client, local_llm_config_from_sources
                outcome = evidence_llm.propose(project, doc_id, build_local_llm_client(local_llm_config_from_sources()))
                save_project(project)
                st.success(f"원문과 맞는 값 {outcome['accepted']}개를 찾았어요 (맞지 않아 버린 값 {outcome['rejected']}개). 파일별 보완 요청에서 확인해 주세요.")
            except Exception as exc:
                st.error(f"AI 연결에 실패했어요: {exc}")


# ---------------------------------------------------------------- ② 파일별 보완 요청

def _card_conflict(project, item, names) -> None:
    slot, pid, field = item["slot"], project.project_id, item["field"]
    with st.container(border=True):
        st.markdown(f"**{names(item['entity'])}의 {_j(_name(field), '이', '가')} 자료마다 달라요.**")
        st.caption("파일 이름이나 날짜만으로 정하지 마세요. 현재 설비에 실제로 적용되는 값을 원자료·현장 담당자와 확인해 고르세요. 모르면 그대로 두어도 돼요.")
        facts = {f["id"]: f for f in slot["facts"] if ew.value_problem(field, f["value"]) is None}
        for bad in (f for f in slot["facts"] if f["id"] not in facts):
            st.caption(f"{_where(bad)}에는 ‘{bad.get('raw', bad['value'])}’로 적혀 있어 그대로는 고를 수 없어요 "
                       "(범위·글자·계산식이에요). 맞는 값이 아래에 없으면 직접 적어 주세요.")
        options = list(facts) + ["직접"]
        choice = st.radio("어느 값이 맞나요?", options, key=f"pick_{pid}_{slot['key']}",
                          format_func=lambda i: "둘 다 아니에요 (직접 입력)" if i == "직접"
                          else f"{_value(field, facts[i]['value'])} — {_where(facts[i])}{_raw_note(facts[i])}")
        typed = _value_input(field, f"typed_{pid}_{slot['key']}", "맞는 값") if choice == "직접" else ""
        if st.button("이 값으로 정하기", key=f"ok_{pid}_{slot['key']}"):
            if choice == "직접":
                _confirm_manual(project, item["entity"], field, typed, "")
            else:
                try:
                    ew.approve(project, slot["key"], choice)
                except ValueError as exc:
                    st.error(str(exc))
                    return
                _save(project, f"{names(item['entity'])}의 {_j(_name(field), '을', '를')} {_value(field, facts[choice]['value'])}로 정했어요.")


def _card_problem(project, group, names) -> None:
    """그대로 쓸 수 없는 값. 원인을 추측하지 않고 파일·위치·적힌 글자·걸린 검사만 알려 줍니다.
    같은 열(단위)과 같은 표기는 한 번만 묻고, 답은 같은 경우 전체와 앞으로 올리는 자료에 적용합니다."""
    pid, field, facts, raw = project.project_id, group["field"], group["facts"], group["raw"]
    first = facts[0]
    gid = hashlib.sha256(json.dumps([group["kind"], field, raw, group["sha256"], group["header"], first["id"]],
                                    ensure_ascii=False).encode()).hexdigest()[:12]
    others = f" 외 {len(facts) - 1}곳" if len(facts) > 1 else ""
    with st.container(border=True):
        if group["kind"] == "column":
            st.markdown(f"**{first['document']}의 ‘{group['header']}’ 열에 단위가 없어요.**")
            st.caption(f"이 열의 값 {len(facts)}개(예: {', '.join(f['raw'] for f in facts[:3])})를 계산에 쓰려면 단위가 필요해요. "
                       "한 번 고르면 이 열 전체에 적용돼요.")
            unit = st.radio("이 열의 단위", ew.UNIT_CHOICES.get(field, ()), horizontal=True, key=f"unit_{pid}_{gid}")
            if st.button("이 열에 적용", key=f"unit_ok_{pid}_{gid}"):
                try:
                    changed = ew.learn_unit(project, group["sha256"], group["header"], unit)
                except ValueError as exc:
                    st.error(str(exc))
                    return
                _save(project, f"‘{group['header']}’ 열 {changed}칸에 단위 {unit}를 적용했어요.")
            return
        if group["kind"] == "text" and len(facts) > 1:
            st.markdown(f"**{_name(field)} 칸에 {_q(raw, '이라고', '라고')} 적힌 곳이 {len(facts)}곳 있어요.**")
        else:
            st.markdown(f"**{names(first['entity'])}의 {_name(field)} 칸에 {_q(raw, '이라고', '라고')} 적혀 있어요.**")
        st.caption(f"{_where(first)}{others} · {group['reason']}.")
        if len(facts) > 1:
            with st.expander(f"{len(facts)}곳 모두 보기"):
                st.dataframe([{"설비·물질": names(f["entity"]), "읽은 곳": _where(f)} for f in facts], hide_index=True, width="stretch")
        reason = f"담당자 확인 ({first['document']} 원문 ‘{raw}’)"
        if len(group["keys"]) == 1:
            # 같은 설비·항목에 다른 자료가 쓸 수 있는 값을 갖고 있으면 참고로 보여 주고 바로 고를 수 있게 합니다.
            slot = next((s for s in ew.slots(project) if s["key"] == group["keys"][0]), None)
            usable = [f for f in (slot["facts"] if slot else []) if ew.value_problem(field, f["value"]) is None]
            for index, other in enumerate(usable[:3]):
                st.caption(f"참고: 다른 자료({_where(other)})에는 {_value(field, other['value'])}{_raw_note(other)}")
                if st.button(f"{_value(field, other['value'])}로 정하기", key=f"use_{pid}_{gid}_{index}"):
                    ew.approve(project, slot["key"], other["id"])
                    _save(project, f"{names(first['entity'])}의 {_j(_name(field), '을', '를')} {_value(field, other['value'])}로 정했어요.")
        if group["kind"] == "single":
            suggestion = _formula_result(raw) if raw.startswith("=") else None
            if suggestion is not None:
                st.caption(f"참고: 식에 숫자와 사칙연산만 있어 계산하면 {_value(field, suggestion)}이에요.")
                if st.button(f"{_value(field, suggestion)}로 저장", key=f"formula_{pid}_{gid}"):
                    _confirm_manual(project, first["entity"], field, _number(suggestion).replace(",", ""), reason + " 계산식 결과")
            typed = _value_input(field, f"fix_{pid}_{gid}", "맞는 값")
            if st.button("저장", key=f"save_{pid}_{gid}", disabled=not typed):
                _confirm_manual(project, first["entity"], field, typed, reason)
            return
        typed = _value_input(field, f"fix_{pid}_{gid}", f"{_q(raw, '은', '는')} 무엇인가요?")
        apply_all = st.checkbox(f"같은 표기 {len(facts)}곳과 앞으로 올리는 자료에도 적용" if len(facts) > 1
                                else "앞으로 올리는 자료의 같은 표기에도 적용", value=True, key=f"all_{pid}_{gid}")
        if st.button("저장", key=f"save_{pid}_{gid}", disabled=not typed):
            if not apply_all:
                _confirm_manual(project, first["entity"], field, typed, reason)
                return
            try:
                changed = ew.learn_value(project, field, raw, typed)
            except ValueError as exc:
                st.error(f"저장하지 못했어요: {exc}")
                return
            _save(project, f"{_q(raw, '을', '를')} {typed}(으)로 정해 {changed}칸에 적용했어요.")


def _card_held(project, item, names) -> None:
    slot, pid, field = item["slot"], project.project_id, item["field"]
    fact = slot["facts"][0]
    with st.container(border=True):
        st.markdown(f"**{names(item['entity'])}의 {_name(field)}: {_value(field, fact['value'])}**{_raw_note(fact)}")
        why = ", ".join(dict.fromkeys(_plain_reason(r) for r in item["reasons"])) or "한 번 확인이 필요한 값이에요"
        st.caption(f"{_where(fact)} · {why}. 자료와 같으면 ‘맞아요’를 눌러 주세요.")
        cols = st.columns([1, 3])
        if cols[0].button("맞아요", key=f"yes_{pid}_{slot['key']}"):
            try:
                ew.approve(project, slot["key"], fact["id"])
            except ValueError as exc:
                st.error(str(exc))
                return
            _save(project)
        with cols[1].popover("다른 값이에요"):
            typed = _value_input(field, f"other_{pid}_{slot['key']}", "맞는 값")
            if st.button("저장", key=f"other_ok_{pid}_{slot['key']}", disabled=not typed):
                _confirm_manual(project, item["entity"], field, typed, "")


def _card_rank(project, question, names) -> None:
    pid, field, entity = project.project_id, question["field"], question["entity"]
    key = f"rank_{pid}_{entity}_{field}"
    with st.container(border=True):
        other = question["material"] if entity == question["facility"] else question["facility"]
        st.markdown(f"**{names(entity)}의 {_j(_name(field), '이', '가')} 자료에 없어요.**")
        st.caption(f"‘{names(entity)} × {names(other)}’를 포함한 후보들의 순서에 영향을 줄 수 있어요. {HELP.get(field, '')}")
        typed = _value_input(field, key + "_in")
        if st.button("저장", key=key + "_ok", disabled=not typed):
            _confirm_manual(project, entity, field, typed, "")


def _card_missing(project, entity, fields, names, materials) -> None:
    pid = project.project_id
    with st.container(border=True):
        st.markdown(f"**{names(entity)}** — 자료에 없는 정보: " + ", ".join(_name(f) for f in fields))
        with st.form(f"missing_{pid}_{entity}"):
            values = {}
            for field in fields:
                if field == "product" and materials:
                    pick = st.selectbox("다루는 제품", ["모름"] + materials, format_func=lambda m: m if m == "모름" else names(m),
                                        help=HELP["product"], key=f"missing_{pid}_{entity}_product")
                    values[field] = "" if pick == "모름" else pick.split(":", 1)[1]
                else:
                    values[field] = _value_input(field, f"missing_{pid}_{entity}_{field}")
            st.caption("아는 것만 적으세요. 비워 둔 항목은 나중에 자료를 더 올리거나 다시 적으면 돼요.")
            if st.form_submit_button("저장"):
                filled = {f: v for f, v in values.items() if v}
                errors = []
                for field, value in filled.items():
                    try:
                        ew.add_manual(project, entity, field, value, f"담당자 직접 입력 ({date.today().isoformat()})", confirm=True)
                    except ValueError as exc:
                        errors.append(f"{_name(field)}: {exc}")
                if errors:
                    st.error("저장하지 못한 항목이 있어요 — " + " / ".join(errors))
                elif filled:
                    _save(project, f"{names(entity)} 정보 {len(filled)}개를 저장했어요.")


def _section(title: str, items: list, caption: str) -> bool:
    if not items:
        return False
    st.subheader(f"{title} ({len(items)})")
    st.caption(caption)
    return True


def _visible(items, key):
    """질문이 많을 때 뒤쪽 질문도 선택해 볼 수 있게 합니다."""
    entries = list(items)
    if len(entries) <= MAX_CARDS:
        return entries
    pages = (len(entries) + MAX_CARDS - 1) // MAX_CARDS
    page = st.selectbox("볼 질문 묶음", range(pages), key=key,
                        format_func=lambda i: f"{i + 1}/{pages} 묶음 · {i * MAX_CARDS + 1}~{min((i + 1) * MAX_CARDS, len(entries))}번")
    st.caption(f"전체 {len(entries)}개 중 이 묶음의 질문을 보여 줍니다. 다음 묶음도 확인해 주세요.")
    return entries[page * MAX_CARDS:(page + 1) * MAX_CARDS]


def _correction_rows(project, found) -> list[dict]:
    """파일·위치·항목·수정 지시를 한 줄씩 적는다. 추정된 원본은 쓰지 않는다."""
    rows = []

    def add(source, item, detail, action):
        rows.append({"파일·위치": source, "항목": item, "확인된 문제": detail, "수정 요청": action})

    for doc in ew.documents(project):
        if doc.get("needs_reading"):
            add(doc["name"], "문서 읽기", doc.get("problem") or "값을 연결하지 못했습니다.",
                "스캔본은 OCR을 적용하세요. 근거자료라면 서식에 필요한 내용을 확인하고 해당 문서·원본을 제출하세요.")
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
    for req in build_intake_catalog(project):
        if req.system not in {"CAP", "COMMON"} or req.coverage_status in {"확인", "해당 없음"}:
            continue
        missing = ", ".join(req.missing_labels or (req.label,))
        add(" / ".join(req.suggested_evidence) or "근거 파일 미지정", req.label,
            f"작성 항목에 {missing} 값이 아직 연결되지 않았습니다. 업로드한 자료에 있어도 자동 연결되지 않았을 수 있습니다.",
            "해당 근거자료와 최신본·적용범위를 확인해 제출하고 작성 화면에서 연결·확정하세요.")
    return rows


def _step_questions(project, found) -> None:
    pid, names = project.project_id, found["names"]
    if not ew.documents(project):
        st.info("먼저 ① 자료 올리기에서 자료를 올려 주세요.")
        return
    rows = _correction_rows(project, found)
    st.markdown("**파일별 수정 요청**")
    st.caption("원본 파일을 고쳐 한 번에 다시 올리세요. ‘작성 항목에 연결되지 않음’은 그 값이 회사 자료에 없다는 뜻이 아닙니다.")
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
        text_report = "파일·위치 | 항목 | 확인된 문제 | 수정 요청\n" + "\n".join(
            " | ".join(str(row[k]).replace("\n", " ") for k in ("파일·위치", "항목", "확인된 문제", "수정 요청")) for row in rows)
        st.download_button("회사에 보낼 수정 요청 TXT", text_report.encode("utf-8-sig"),
                           file_name="회사자료_파일별_수정요청.txt", mime="text/plain", key="corrections_" + pid)
    else:
        st.success("현재 연결된 자료에서 수정 요청을 찾지 못했습니다. 법정 판정과 서식 확인은 별도로 진행하세요.")
    with st.expander("파일을 바로 고칠 수 없을 때만 직접 확인·입력"):
        _inline_review(project, found)
    _next_button(3, pid, "다음: 시나리오 후보 보기 →")


def _inline_review(project, found) -> None:
    pid, names = project.project_id, found["names"]
    unmapped = [d for d in ew.documents(project) if d.get("unmapped_columns")]
    if unmapped:
        st.info(f"프로그램이 모르는 열이 있는 파일이 {len(unmapped)}개 있어요. ① 자료 올리기의 ‘읽기 결과 보기’에서 필요한 열을 먼저 "
                "지정하면, 자료에 없다고 묻는 질문이 줄어들 수 있어요.")
        st.button("① 읽기 결과 보러 가기", key="to_report_" + pid, on_click=_go, args=(1, pid))
    if not _question_count(found):
        if any(d.get("needs_reading") for d in ew.documents(project)):
            st.warning("답할 질문은 없지만 읽지 못한 파일이 있어요. ① 자료 올리기에서 해당 파일을 확인해 주세요.")
        else:
            st.success("지금 답할 질문이 없어요. ③ 시나리오 후보를 확인해 보세요.")
    if _section("자료마다 값이 달라요", found["conflicts"], "같은 설비의 같은 항목이 파일마다 다르게 적혀 있어요. 맞는 값을 하나 골라 주세요."):
        for item in _visible(found["conflicts"], "conflict_page_" + pid):
            _card_conflict(project, item, names)
    if _section("그대로 쓸 수 없는 값", found["problems"],
                "어느 파일 어디에 무엇이 적혀 있었고 어떤 검사에 걸렸는지 보여 줘요. 같은 열과 같은 표기는 한 번만 물어요."):
        for group in _visible(found["problems"], "problem_page_" + pid):
            _card_problem(project, group, names)
    if _section("순위를 정하려면 꼭 필요한 값", found["rank"], "자료에 없는 값 중 시나리오 후보 순위를 바꾸는 것만 골랐어요."):
        for question in _visible(found["rank"], "rank_page_" + pid):
            _card_rank(project, question, names)
    if _section("한 번 확인해 주세요", found["held"], "값은 찾았지만 자동으로 채우기엔 확실하지 않은 값이에요."):
        table_only = [i for i in found["held"] if all(f.get("method") == "table" for f in i["slot"]["facts"])]
        checked = st.checkbox("표에서 읽은 값들의 원자료를 확인했어요", key="bulk_check_" + pid) if len(table_only) > 3 else False
        if len(table_only) > 3 and st.button(f"확인한 표 값 {len(table_only)}개 저장", key="bulk_" + pid, disabled=not checked):
            outcome = ew.approve_bulk(project, [i["key"] for i in table_only])
            _save(project, f"{outcome['approved']}개를 확인했어요.")
        for item in _visible(found["held"], "held_page_" + pid):
            _card_held(project, item, names)
    if _section("자료에 없는 정보", list(found["missing"]), "알고 있으면 적어 주세요. 모르면 비워 두고 관련 자료를 더 올려도 돼요."):
        materials = sorted({s["entity"] for s in found["slots"] if s["entity"].startswith("material:")})
        for entity, fields in _visible(found["missing"].items(), "missing_page_" + pid):
            _card_missing(project, entity, fields, names, materials)
    if found["notes"]:
        st.subheader("참고")
        for note in found["notes"]:
            st.write("• " + (names(note["entity"]) + ": " if note["entity"].startswith(("facility:", "material:")) else "")
                     + note["task"])


# ---------------------------------------------------------------- ③ 시나리오 후보

def _step_scenarios(project, found, triage) -> None:
    pid, names = project.project_id, found["names"]
    workup = scenario_workup.compile_workup(project, triage)
    st.write("물질과 설비를 짝지어 **어느 조합부터 사고시나리오로 검토할지** 순서를 매겼어요. "
             "파일 보완 전에도 자료에서 읽은 값으로 먼저 계산해요.")
    with st.expander("순서는 어떻게 매기나요?"):
        st.markdown("최대보유량(kg) × (1 + 운전압력(MPa)) × 함량(%) ÷ 100 이 큰 조합을 먼저 보여 줘요. "
                    "많이, 높은 압력으로, 진하게 들어 있을수록 앞에 와요.\n\n"
                    "이건 **검토 순서**예요. 독성·인화성, 누출량, 날씨, 주변 주민까지 따지는 실제 사고시나리오 선정과 "
                    "피해 범위 계산은 화학사고예방관리계획서 작성 화면에서 해요.")
    linked = [r for r in triage["rows"] if r["linked"]]
    packets = [p for p in workup["packets"] if p["linked"]]
    if not linked:
        st.info("설비가 어떤 제품을 다루는지 자료에서 찾으면 순서가 나와요. 설비 목록에 ‘취급제품’ 열이 있는지 확인해 주세요.")
    else:
        st.dataframe([{"순서": r["rank"], "설비": names(r["facility"]), "물질": names(r["material"]),
                       "비교 점수": round(r["score"], 1), "상태": TRIAGE_STATE.get(r["state"], r["state"])} for r in linked],
                     hide_index=True, width="stretch")
        st.caption(f"검토할 조합 {len(packets)}개 · 자료 확인이 남은 조합 {sum(p['state'] != '예비 검토' for p in packets)}개")
        if found["rank"]:
            st.warning(f"순서를 확실히 하려면 답해 주실 값이 {len(found['rank'])}개 있어요.")
            st.button("② 파일별 보완 요청 보기", key="to_questions_" + pid, on_click=_go, args=(2, pid))
        with st.expander("조합별로 어떤 값을 썼는지 보기"):
            pick = st.selectbox("조합", range(len(linked)), key="combo_" + pid,
                                format_func=lambda i: f"{linked[i]['rank']}번 · {names(linked[i]['facility'])} × {names(linked[i]['material'])}")
            row = linked[pick]
            packet = packets[pick]
            st.info("다음 할 일: " + packet["action"])
            for field in scenario_triage.SCORED_FIELDS:
                value = row["values"].get(field)
                state = VALUE_STATE.get(row["value_states"].get(field), "")
                source = row["sources"].get(field)
                where = f" — {source['document']}" if source else ""
                st.write(f"• {_name(field)}: {_value(field, value) if value is not None else '없음'} ({state}{where})")
                if field in row["assumptions"]:
                    st.caption("가정한 이유: " + row["assumptions"][field]["basis"] + " · 실제 계산에는 사용하지 않아요.")
            if row["rank_critical"]:
                st.caption("다음 값이 달라지면 후보들 사이의 순서가 바뀔 수 있어요: " + ", ".join(_name(f) for f in row["rank_critical"])
                           + ". ④에서 보내기 전에 한 번 더 확인해요.")
            for blocker in row["blockers"]:
                st.caption("아직 필요한 것: " + blocker.replace(": 담당자 확인", " 확인").replace(": 값 충돌", " (자료마다 다름)")
                           .replace("설비 운전온도 미확인", "운전온도"))
            st.markdown("**사고시나리오를 만들기 전에 추가로 확인할 것**")
            for check in packet["next_checks"]:
                st.write("• " + check)
        st.download_button("시나리오 후보 검토 초안 내려받기", scenario_workup.markdown(workup, project.company_name).encode(),
                           file_name="scenario_candidate_review.md", mime="text/markdown", key="scenario_review_" + pid)
    unlinked = [r for r in triage["rows"] if not r["linked"]]
    if unlinked:
        with st.expander(f"어떤 물질을 쓰는지 자료로 확인되지 않은 조합 {len(unlinked)}개"):
            st.caption("지우지 않고 남겨 둬요. 설비 목록의 취급제품과 물질 목록의 제품코드가 맞으면 위 순서에 들어가요.")
            st.dataframe([{"설비": names(r["facility"]), "물질": names(r["material"])} for r in unlinked[:500]],
                         hide_index=True, width="stretch")
    _next_button(4, pid, "다음: 보내기·진행 현황 →")


# ---------------------------------------------------------------- ④ 보내기·진행 현황

def _form1_payoff(project) -> None:
    """보낸 자료로 별지 제1호가 어디까지 채워졌는지, 법정 산정에 더 필요한 값이 무엇인지 보여 줍니다."""
    record = project.get_field("inventory.facilities")
    if record is None or record.status not in {"USER_CONFIRMED", "VERIFIED"}:
        return
    from engine.stage2 import cap_workspace as ws
    form = ws.resolve_form1(project)
    st.subheader("별지 제1호(취급 화학물질 목록)에 들어간 내용")
    if form.chemical_rows:
        st.dataframe([{"물질": r.get("물질명"), "CAS 번호": r.get("CAS No."), "최대보유량(ton)": r.get("사업장 내 최대보유량(ton)"),
                       "계산 근거": r.get("산정근거")} for r in form.chemical_rows], hide_index=True, width="stretch")
    needs = ew.form1_needs(project)
    if needs:
        st.caption("법에서 정한 방식으로 보유량을 다시 계산하려면 아래 값이 더 필요해요. ‘사업장·물질·시설 작성’ 화면 별지 제1호의 ‘시설 입력’에서 저장하면 계산돼요. "
                   "읽어 온 시설유형·성상·용량·비중은 미리 채워 두었어요.")
        for need in needs:
            st.write("• " + need)


TARGET_NAME = {"inventory.chemicals": "물질 목록", "inventory.facilities": "설비 목록",
               "cap.chemical.details": "별지 제6호 물질 표", "cap.workspace.facilities": "별지 제1호 시설 표"}


def _step_export(project, found) -> None:
    """확인한 값을 작성자료로 보내고, 문서별로 남은 일을 한곳에서 보여 줍니다(여기만 따라가면 되도록)."""
    st.write("확인한 값을 **작성자료**로 보내요. 보낸 뒤에는 아래 진행 현황에서 남은 일을 보고 ‘이어서 작성’을 누르면 돼요.")
    _send(project, found)
    st.divider()
    _progress_board(project)
    _records(project, found["names"])


def _progress_board(project) -> None:
    from engine.stage2 import cap_judgement
    from ui import cap_common

    shown = False
    if project.cap_in_scope or cap_judgement.undecided(project):
        cap_common.render_progress(project, key_prefix="hub_" + project.project_id)
        shown = True
    if project.psm_in_scope:
        from engine.stage2 import report_export as rx

        try:
            state = rx.evaluate(project, "PSM")
            left = state.hold + state.review
            st.markdown("**공정안전보고서** — " + (f"보완할 것 {left}건" if left else "점검을 확정하면 내려받을 수 있어요"))
        except ValueError:
            pass
        st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성 화면으로 가기 →")
        shown = True
    if not shown:
        st.caption("이 사업장은 아직 작성할 문서가 정해지지 않았어요. ‘사업장 판정하기’에서 확인하세요.")


def _restore_excluded(project) -> None:
    """별지에서 지워 제외한 대상. 실수로 지웠으면 되살릴 수 있게 합니다."""
    gone = ew.excluded(project)
    if not gone:
        return
    with st.expander(f"별지에서 지워 제외한 대상 {len(gone)}개"):
        st.caption("별지 제1·6호에서 행을 지우면 자료 접수에서도 제외돼 다시 보내지 않아요. 실수였다면 되살리세요.")
        names = Names(ew.slots(project))
        for entity in gone:
            cols = st.columns([4, 1])
            cols[0].write(entity.split(":", 1)[1] + (" (설비)" if entity.startswith("facility:") else " (물질)"))
            if cols[1].button("되살리기", key=f"restore_{project.project_id}_{entity}"):
                ew.restore(project, entity)
                _save(project, f"{names(entity)}을(를) 다시 포함했어요.")


def _send(project, found) -> None:
    pid, names = project.project_id, found["names"]
    pending = _question_count(found)
    if pending:
        st.info(f"② 아직 보완·확인하지 않은 값 {pending}개가 있어요. 확인한 값만 연결되고 나머지는 보류됩니다.")
    check = _final_check(project)
    if check:
        groups = {}
        for slot in check:
            source = slot["chosen"]["sha256"]
            groups.setdefault(source, []).append(slot)
        st.subheader(f"보내기 전 마지막 확인 · 파일 {len(groups)}개")
        st.caption("자동으로 채운 중요한 값은 파일별로 확인해요. 지금 모르면 확인하지 않고 원자료를 다시 살펴보세요.")
        source = st.selectbox("확인할 파일", list(groups), key="final_source_" + pid,
                              format_func=lambda key: f"{groups[key][0]['chosen']['document']} · {len(groups[key])}개 값")
        selected = groups[source]
        st.caption(f"이 파일에서 확인할 값 {len(selected)}개 · 전체 남은 값 {len(check)}개")
        st.dataframe([{"설비·물질": names(s["entity"]), "항목": _name(s["field"]),
                       "값": _value(s["field"], s["chosen"]["value"]) + _raw_note(s["chosen"]),
                       "읽은 곳": _where(s["chosen"])} for s in selected], hide_index=True, width="stretch")
        checked = st.checkbox("이 파일의 값과 원자료·단위·현재 적용 여부를 확인했어요", key="final_check_" + pid + "_" + source)
        cols = st.columns([1, 2])
        if cols[0].button("이 파일의 값 저장", key="final_ok_" + pid, type="primary", disabled=not checked):
            ew.confirm_auto(project, [s["key"] for s in selected])
            _save(project, f"{len(selected)}개 값을 확인했어요.")
        with cols[1].popover("틀린 값이 있어요"):
            pick = st.selectbox("어느 값인가요?", range(len(selected)), key="final_pick_" + pid,
                                format_func=lambda i: f"{names(selected[i]['entity'])} · {_name(selected[i]['field'])}")
            slot = selected[pick]
            typed = _value_input(slot["field"], f"final_fix_{pid}_{slot['key']}", "맞는 값")
            if st.button("고치기", key="final_fix_ok_" + pid, disabled=not typed):
                _confirm_manual(project, slot["entity"], slot["field"], typed, "")
        return

    if not ew.publishing_plan(project):
        st.info("보낼 값이 아직 없어요. ① 자료를 올리고 ② 파일별 보완 요청을 확인해 주세요.")
        return
    st.caption("같은 설비번호·CAS 번호의 행에 합쳐요. 별지에서만 적은 칸(분자량·형상 치수 등)은 그대로 두고, "
               "자료마다 달라 아직 정하지 않은 값은 비워요. 별지 제1·6호에서 고친 값은 이미 여기에 반영돼 있어요.")
    preview = ew.publish_preview(project)
    changed = [key for key, rows in preview.items() if (project.get_field(key) or None) is None or project.get_field(key).value != rows]
    replaced = [key for key in changed if project.get_field(key) is not None]
    for key in ("inventory.chemicals", "inventory.facilities"):
        if key in preview:
            st.markdown(f"**{TARGET_NAME[key]}** — {len(preview[key])}개" + ("" if key in changed else " · 바뀐 것 없음"))
            st.dataframe(preview[key], hide_index=True, width="stretch")
    for key in ("cap.workspace.facilities", "cap.chemical.details"):
        if key in changed:
            st.caption(f"{TARGET_NAME[key]}에도 같은 값을 합쳐요.")
    _restore_excluded(project)
    if not changed:
        st.success("이미 보낸 내용과 같아요. 보낼 것이 없어요.")
        return
    overwrite = True
    if replaced:
        overwrite = st.checkbox("이미 저장된 " + ", ".join(TARGET_NAME.get(k, k) for k in replaced)
                                + "에 위 내용을 합칠게요", key="overwrite_" + pid)
    if st.button("작성자료로 보내기", type="primary", key="publish_" + pid, disabled=not overwrite):
        try:
            ew.publish(project, replace_existing=True)
            save_project(project)
            st.success("보냈어요. 아래 진행 현황에서 ‘이어서 작성’을 누르세요.")
        except ValueError as exc:
            st.error(str(exc))
    _form1_payoff(project)


def _records(project, names) -> None:
    with st.expander("검토·감사용 기록 (값마다 어느 파일 어디서 왔는지)"):
        st.caption("나중에 검토자가 ‘이 값 어디서 왔어요?’라고 물으면 이 기록을 보여 주세요. 파일 지문으로 원본이 바뀌지 않았는지 확인할 수 있어요.")
        rows = [{"설비·물질": names(s["entity"]), "항목": _name(s["field"]), "값": _value(s["field"], s["chosen"]["value"]),
                 "누가": "자동" if s["method"] == "AUTO" else "담당자 확인", "읽은 곳": _where(s["chosen"])}
                for s in ew.slots(project) if s["chosen"]]
        st.dataframe(rows, hide_index=True, width="stretch")
        cols = st.columns(2)
        cols[0].download_button("검토 보고서 내려받기", ew.report(project).encode(), file_name="company_evidence_review.md", mime="text/markdown")
        cols[1].download_button("전체 출처 기록 내려받기 (JSON)", json.dumps(ew._read(project), ensure_ascii=False, indent=2).encode(),
                                file_name="company_evidence_graph.json", mime="application/json")


# ---------------------------------------------------------------- 화면

st.set_page_config(page_title="사업장 업무", page_icon="📂", layout="wide")
st.title("화학사고예방관리계획서 자료 정리")
st.caption("회사 자료를 올리면 값을 찾아 정리하고, 파일별 수정·확인 요청을 보여 줍니다.")
_active = _project_header()
_triage = scenario_triage.evaluate(_active)
_found = _collect(_active, _triage)
_status_line(_active, _found)
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
