"""사업장 업무 화면: 신입사원도 따라올 수 있게 단계별로 안내합니다.

① 자료 올리기 → ② 질문에 답하기 → ③ 시나리오 후보 → ④ 작성 화면으로 보내기

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

from engine.stage2 import demo_company, evidence_llm, scenario_triage
from engine.stage2 import evidence_workspace as ew
from engine.stage2.direct_template import create_direct_cap_project
from engine.stage2.storage import list_projects, load_project, save_attachment, save_project

STEPS = {1: "① 자료 올리기", 2: "② 질문에 답하기", 3: "③ 시나리오 후보", 4: "④ 작성 화면으로 보내기"}
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
            "invalid": [i for i in queue if i["kind"] == "값 오류"],
            "held": [i for i in queue if i["kind"] == "확인 필요"],
            "rank": rank_questions, "missing": missing, "notes": notes}


def _question_count(found) -> int:
    return len(found["conflicts"]) + len(found["invalid"]) + len(found["held"]) + len(found["rank"]) + len(found["missing"])


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
    options = {p["project_id"]: p["company_name"] for p in projects}
    current = st.session_state.get("_stage2_active_project_id")
    project_id = st.selectbox("사업장", list(options), index=list(options).index(current) if current in options else 0,
                              format_func=options.get)
    st.session_state["_stage2_active_project_id"] = project_id
    return load_project(project_id)


def _status_line(project, found) -> None:
    info = ew.summary(project)
    if not info["documents"]:
        return
    count = _question_count(found)
    parts = [f"자료 {info['documents']}개를 읽었어요", f"값 {info['auto'] + info['person']}개를 채웠어요"]
    parts.append(f"답해 주실 질문이 {count}개 있어요" if count else "지금 답할 질문은 없어요")
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
    st.write("회사에 있는 자료를 **그대로** 올리세요. 서식을 채울 필요 없어요. "
             "프로그램이 값을 찾아 정리하고, 사람이 확인해야 할 것만 다음 단계에서 물어봐요.")
    with st.expander("어떤 자료를 올리면 되나요?"):
        st.markdown(
            "- **설비 목록·설비대장**: 설비번호, 설비 이름, 용량, 최대보유량, 운전압력·온도가 있는 엑셀·CSV\n"
            "- **물질 목록·MSDS**: 제품코드, 제품 이름, CAS 번호, 함량이 있는 엑셀·CSV·PDF\n"
            "- **운전조건표·설비 사양서**: 표가 있는 엑셀·워드(DOCX)·한글(HWPX)·PDF\n\n"
            "여러 파일을 한 번에 올려도 돼요. 같은 설비번호·제품코드끼리 알아서 묶어요. "
            "스캔한 PDF(사진)와 옛 한글 파일(HWP)은 아직 읽지 못해요.")
    uploaded = st.file_uploader("파일 선택 (여러 개 가능, 파일당 20MB 이하)",
                                type=["csv", "xlsx", "pdf", "docx", "hwpx", "txt"], accept_multiple_files=True)
    selected, hints = {}, {}
    for index, file in enumerate(uploaded or []):
        digest, detected = _classify(file.name, file.getvalue())
        if detected:
            st.write(f"✅ {file.name} — {'물질 목록·MSDS' if detected == 'material' else '설비 목록·운전 자료'}로 알아봤어요")
            selected[index] = detected
        else:
            # 파일 내용 기준 키: 다른 파일을 빼도 이미 고른 종류가 다른 파일로 옮겨 가지 않습니다
            selected[index] = st.selectbox(f"❓ {file.name} — 어떤 자료인가요?", ["선택하세요", "facility", "material"],
                                           format_func={"선택하세요": "선택하세요", "material": "물질 목록·MSDS",
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
                if selected[index] == "선택하세요":
                    raise ValueError("어떤 자료인지 골라 주세요")
                count = ew.ingest(project, file.name, file.getvalue(), selected[index], hints.get(index, ""))
                save_attachment(project.project_id, file.name, file.getvalue(), note="공통정보 추출 원문")
                save_project(project)
                st.session_state.setdefault("evidence_notes", []).append(
                    f"{file.name}: 값 {count}개를 찾았어요." if count else
                    f"{file.name}: 값을 찾지 못했어요. 스캔본이면 글자를 읽을 수 없고, 표에 설비번호·제품코드 같은 항목 이름이 있어야 해요.")
            except Exception as exc:
                why = exc if isinstance(exc, ValueError) else "파일 형식을 확인해 주세요"
                st.session_state.setdefault("evidence_notes", []).append(f"{file.name}: 읽지 못했어요 ({why}). 다른 자료는 그대로예요.")
        st.session_state["evidence_goto"] = 2   # 읽고 나면 바로 질문 단계로 (단계 위젯은 다음 실행 전에 바꿉니다)
        st.rerun()

    data = ew.graph(project)
    if data["documents"]:
        st.subheader("읽은 자료")
        names = found["names"]
        for doc in data["documents"]:
            facts = [f for f in data["facts"] if f["sha256"] == doc["sha256"]]
            targets = {f["entity"] for f in facts}
            if doc.get("needs_reading"):
                st.write(f"⚠️ {doc['name']} — 표나 값을 찾지 못했어요"
                         + (" (스캔 문서는 글자를 읽을 수 없어요)" if doc.get("needs_ocr") else ""))
            else:
                st.write(f"📄 {doc['name']} — 설비·물질 {len(targets)}개에서 값 {len(facts)}개를 찾았어요")
            with st.expander("찾은 값 보기"):
                for table in doc.get("tables", []):
                    if table["header_row"] and table["header_row"] > 1:
                        st.caption(f"위쪽 제목 줄을 건너뛰고 {table['header_row']}번째 줄을 항목 이름으로 읽었어요.")
                if doc.get("unmapped_columns"):
                    st.caption("아직 쓰지 않는 열: " + ", ".join(map(str, doc["unmapped_columns"])))
                if doc.get("rows_without_id"):
                    st.caption(f"번호·이름이 없거나 합계 줄이라 건너뛴 줄 {doc['rows_without_id']}개")
                if facts:
                    st.dataframe([{"설비·물질": names(f["entity"]), "항목": _name(f["field"]), "값": _value(f["field"], f["value"]) + _raw_note(f),
                                   "위치": _where(f)} for f in facts], hide_index=True, width="stretch")
        _next_button(2, pid, "다음: 질문에 답하기 →")
    st.divider()
    st.markdown("**연습용 가상 회사 자료**")
    cols = st.columns(2)
    cols[0].download_button("작은 자료 (파일 4개)", ew.demo_zip(), file_name="synthetic_company_evidence.zip",
                            mime="application/zip", key="demo_small")
    cols[0].caption("처음 써 볼 때. 설비 4대, 제품 2개, 일부러 넣은 문제 2개.")
    cols[1].download_button("실제와 비슷한 큰 자료 (파일 7개)", demo_company.large_demo_zip(),
                            file_name="synthetic_company_evidence_large.zip", mime="application/zip", key="demo_large")
    cols[1].caption("설비 40대, 제품 26개. 여러 시트·숨김 시트·병합 칸·단위가 다른 시트·옛 자료·한글 사양서·스캔본과 "
                    "일부러 넣은 문제 30가지. 정답표(answer_key.json)가 들어 있어요.")
    _local_llm(project, data)


def _local_llm(project, data) -> None:
    with st.expander("고급: 서술형 문서에서 AI로 값 찾기 (선택)"):
        readable = {d["sha256"]: d for d in data["documents"] if d.get("hint") and any(p.get("text", "").strip() for p in d.get("passages", []))}
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
                st.success(f"원문과 맞는 값 {outcome['accepted']}개를 찾았어요 (맞지 않아 버린 값 {outcome['rejected']}개). ‘질문에 답하기’에서 확인해 주세요.")
            except Exception as exc:
                st.error(f"AI 연결에 실패했어요: {exc}")


# ---------------------------------------------------------------- ② 질문에 답하기

def _card_conflict(project, item, names) -> None:
    slot, pid, field = item["slot"], project.project_id, item["field"]
    with st.container(border=True):
        st.markdown(f"**{names(item['entity'])}의 {_j(_name(field), '이', '가')} 자료마다 달라요.**")
        st.caption("더 최근에 만든 자료의 값을 고르세요. 잘 모르겠으면 현장 담당자에게 물어보세요.")
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


def _card_invalid(project, item, names) -> None:
    slot, pid, field = item["slot"], project.project_id, item["field"]
    fact = slot["facts"][0]
    raw = str(fact.get("raw", fact["value"]))
    with st.container(border=True):
        suggestion = None
        if "formula_uncached" in fact.get("flags", []) or raw.startswith("="):
            st.markdown(f"**{names(item['entity'])}의 {_name(field)} 칸에 숫자 대신 엑셀 계산식(`{raw}`)이 들어 있어요.**")
            st.caption(f"{_where(fact)} · 계산 결과가 파일에 저장돼 있지 않아 값을 읽을 수 없었어요.")
            suggestion = _formula_result(raw)
        elif re.search(r"\d\s*[~∼]\s*\d", raw):
            st.markdown(f"**{names(item['entity'])}의 {_j(_name(field), '이', '가')} `{raw}`처럼 범위로 적혀 있어요.**")
            st.caption(f"{_where(fact)} · 계산에는 숫자 하나가 필요해요. 실제 운전 기준 값을 적어 주세요.")
        elif field in ew.UNIT_SUFFIXES and not ew.has_unit(field, fact.get("header", "")):
            st.markdown(f"**{names(item['entity'])}의 {_name(field)} 값(`{raw}`)에 단위가 없어요.**")
            st.caption(f"{_where(fact)} · 단위를 확인해 {_unit(field)} 기준으로 적어 주세요.")
        elif field in ew.CHOICES:
            st.markdown(f"**{names(item['entity'])}의 {_name(field)}에 적힌 말(`{raw}`)이 선택지에 없어요.**")
            st.caption(f"{_where(fact)} · 아래에서 가장 가까운 것을 골라 주세요. {HELP.get(field, '')}")
        elif field == "cas":
            st.markdown(f"**{names(item['entity'])}의 CAS 번호(`{raw}`)가 올바른 번호가 아니에요.**")
            st.caption(f"{_where(fact)} · 오타일 수 있어요. MSDS 3번 항목에서 확인해 주세요.")
        else:
            st.markdown(f"**{names(item['entity'])}의 {_name(field)} 값(`{raw}`)이 너무 크거나 작아요.**")
            st.caption(f"{_where(fact)} · 단위가 맞는지 확인해 주세요. {HELP.get(field, '')}")
        reason = f"담당자 확인 ({fact['document']} 원문 ‘{raw}’)"
        if suggestion is not None:
            if st.button(f"계산하면 {_value(field, suggestion)}이에요. 이 값이 맞아요", key=f"formula_{pid}_{slot['key']}"):
                _confirm_manual(project, item["entity"], field, _number(suggestion).replace(",", ""), reason + " 계산식 결과")
        typed = _value_input(field, f"fix_{pid}_{slot['key']}", "맞는 값" + (" (다르면 직접 입력)" if suggestion is not None else ""))
        if st.button("저장", key=f"save_{pid}_{slot['key']}", disabled=not typed):
            _confirm_manual(project, item["entity"], field, typed, reason)


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
        st.caption(f"이 값에 따라 ‘{names(entity)} × {names(other)}’ 시나리오 후보의 순서가 달라져서 꼭 필요해요. {HELP.get(field, '')}")
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


def _step_questions(project, found) -> None:
    pid, names = project.project_id, found["names"]
    if not ew.graph(project)["documents"]:
        st.info("먼저 ① 자료 올리기에서 자료를 올려 주세요.")
        return
    if not _question_count(found):
        st.success("지금 답할 질문이 없어요. ③ 시나리오 후보를 확인해 보세요.")
    if _section("자료마다 값이 달라요", found["conflicts"], "같은 설비의 같은 항목이 파일마다 다르게 적혀 있어요. 맞는 값을 하나 골라 주세요."):
        for item in found["conflicts"][:MAX_CARDS]:
            _card_conflict(project, item, names)
    if _section("읽을 수 없는 값이 있어요", found["invalid"], "자료에 적힌 모양 그대로는 계산에 쓸 수 없어요."):
        for item in found["invalid"][:MAX_CARDS]:
            _card_invalid(project, item, names)
    if _section("순위를 정하려면 꼭 필요한 값", found["rank"], "자료에 없는 값 중 시나리오 후보 순위를 바꾸는 것만 골랐어요."):
        for question in found["rank"][:MAX_CARDS]:
            _card_rank(project, question, names)
    if _section("한 번 확인해 주세요", found["held"], "값은 찾았지만 자동으로 채우기엔 확실하지 않은 값이에요."):
        table_only = [i for i in found["held"] if all(f.get("method") == "table" for f in i["slot"]["facts"])]
        if len(table_only) > 3 and st.button(f"표에서 읽은 값 {len(table_only)}개가 모두 자료와 같아요", key="bulk_" + pid):
            outcome = ew.approve_bulk(project, [i["key"] for i in table_only])
            _save(project, f"{outcome['approved']}개를 확인했어요.")
        for item in found["held"][:MAX_CARDS]:
            _card_held(project, item, names)
    if _section("자료에 없는 정보", list(found["missing"]), "알고 있으면 적어 주세요. 모르면 비워 두고 관련 자료를 더 올려도 돼요."):
        materials = sorted({s["entity"] for s in found["slots"] if s["entity"].startswith("material:")})
        for entity, fields in list(found["missing"].items())[:MAX_CARDS]:
            _card_missing(project, entity, fields, names, materials)
    if found["notes"]:
        st.subheader("참고")
        for note in found["notes"]:
            st.write("• " + (names(note["entity"]) + ": " if note["entity"].startswith(("facility:", "material:")) else "")
                     + note["task"])
    _next_button(3, pid, "다음: 시나리오 후보 보기 →")


# ---------------------------------------------------------------- ③ 시나리오 후보

def _step_scenarios(project, found, triage) -> None:
    pid, names = project.project_id, found["names"]
    st.write("물질과 설비를 짝지어 **어느 조합부터 사고시나리오로 검토할지** 순서를 매겼어요. "
             "질문에 답하기 전에도 자료에서 읽은 값으로 먼저 계산해요.")
    with st.expander("순서는 어떻게 매기나요?"):
        st.markdown("최대보유량(kg) × (1 + 운전압력(MPa)) × 함량(%) ÷ 100 이 큰 조합을 먼저 보여 줘요. "
                    "많이, 높은 압력으로, 진하게 들어 있을수록 앞에 와요.\n\n"
                    "이건 **검토 순서**예요. 독성·인화성, 누출량, 날씨, 주변 주민까지 따지는 실제 사고시나리오 선정과 "
                    "피해 범위 계산은 화학사고예방관리계획서 작성 화면에서 해요.")
    linked = [r for r in triage["rows"] if r["linked"]]
    if not linked:
        st.info("설비가 어떤 제품을 다루는지 자료에서 찾으면 순서가 나와요. 설비 목록에 ‘취급제품’ 열이 있는지 확인해 주세요.")
    else:
        st.dataframe([{"순서": r["rank"], "설비": names(r["facility"]), "물질": names(r["material"]),
                       "비교 점수": round(r["score"], 1), "상태": TRIAGE_STATE.get(r["state"], r["state"])} for r in linked],
                     hide_index=True, width="stretch")
        if found["rank"]:
            st.warning(f"순서를 확실히 하려면 답해 주실 값이 {len(found['rank'])}개 있어요.")
            st.button("② 질문에 답하러 가기", key="to_questions_" + pid, on_click=_go, args=(2, pid))
        with st.expander("조합별로 어떤 값을 썼는지 보기"):
            pick = st.selectbox("조합", range(len(linked)), key="combo_" + pid,
                                format_func=lambda i: f"{linked[i]['rank']}번 · {names(linked[i]['facility'])} × {names(linked[i]['material'])}")
            row = linked[pick]
            for field in scenario_triage.SCORED_FIELDS:
                value = row["values"].get(field)
                state = VALUE_STATE.get(row["value_states"].get(field), "")
                source = row["sources"].get(field)
                where = f" — {source['document']}" if source else ""
                st.write(f"• {_name(field)}: {_value(field, value) if value is not None else '없음'} ({state}{where})")
            if row["rank_critical"]:
                st.caption("다음 값이 조금만 달라져도 이 조합의 순서가 바뀌어요: " + ", ".join(_name(f) for f in row["rank_critical"])
                           + ". ④에서 보내기 전에 한 번 더 확인해요.")
            for blocker in row["blockers"]:
                st.caption("아직 필요한 것: " + blocker.replace(": 담당자 확인", " 확인").replace(": 값 충돌", " (자료마다 다름)")
                           .replace("설비 운전온도 미확인", "운전온도"))
    unlinked = [r for r in triage["rows"] if not r["linked"]]
    if unlinked:
        with st.expander(f"어떤 물질을 쓰는지 자료로 확인되지 않은 조합 {len(unlinked)}개"):
            st.caption("지우지 않고 남겨 둬요. 설비 목록의 취급제품과 물질 목록의 제품코드가 맞으면 위 순서에 들어가요.")
            st.dataframe([{"설비": names(r["facility"]), "물질": names(r["material"])} for r in unlinked[:500]],
                         hide_index=True, width="stretch")
    _next_button(4, pid, "다음: 작성 화면으로 보내기 →")


# ---------------------------------------------------------------- ④ 작성 화면으로 보내기

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
        st.caption("법에서 정한 방식으로 보유량을 다시 계산하려면 아래 값이 더 필요해요. 작성 화면의 ‘시설 입력’에서 저장하면 계산돼요. "
                   "읽어 온 시설유형·성상·용량·비중은 미리 채워 두었어요.")
        for need in needs:
            st.write("• " + need)


TARGET_NAME = {"inventory.chemicals": "물질 목록", "inventory.facilities": "설비 목록"}


def _step_export(project, found) -> None:
    pid, names = project.project_id, found["names"]
    st.write("확인한 값을 **화학사고예방관리계획서 작성 화면**으로 보내요. 보낸 뒤에는 작성 화면에서 주변 지도, 사고시나리오, 서식을 이어서 작성해요.")
    pending = _question_count(found)
    if pending:
        st.info(f"② 질문에 아직 답하지 않은 것이 {pending}개 있어요. 답한 값만 보내지고, 나머지는 나중에 다시 보낼 수 있어요.")
    check = _final_check(project)
    if check:
        st.subheader(f"보내기 전 마지막 확인 ({len(check)})")
        st.caption("자동으로 채운 값 중 법적 계산에 쓰이거나 시나리오 순서를 바꾸는 값이에요. 회사 자료와 같은지 한 번만 봐 주세요.")
        st.dataframe([{"설비·물질": names(s["entity"]), "항목": _name(s["field"]),
                       "값": _value(s["field"], s["chosen"]["value"]) + _raw_note(s["chosen"]),
                       "읽은 곳": _where(s["chosen"])} for s in check], hide_index=True, width="stretch")
        cols = st.columns([1, 2])
        if cols[0].button("모두 자료와 같아요", key="final_ok_" + pid, type="primary"):
            ew.confirm_auto(project, [s["key"] for s in check])
            _save(project, f"{len(check)}개 값을 확인했어요.")
        with cols[1].popover("틀린 값이 있어요"):
            pick = st.selectbox("어느 값인가요?", range(len(check)), key="final_pick_" + pid,
                                format_func=lambda i: f"{names(check[i]['entity'])} · {_name(check[i]['field'])}")
            slot = check[pick]
            typed = _value_input(slot["field"], f"final_fix_{pid}_{slot['key']}", "맞는 값")
            if st.button("고치기", key="final_fix_ok_" + pid, disabled=not typed):
                _confirm_manual(project, slot["entity"], slot["field"], typed, "")
        return

    plan = ew.publishing_plan(project)
    if not plan:
        st.info("보낼 값이 아직 없어요. ① 자료를 올리고 ② 질문에 답해 주세요.")
        return
    changed = []
    for key, rows in plan.items():
        st.markdown(f"**{TARGET_NAME.get(key, key)}** — {len(rows)}개")
        st.dataframe(rows, hide_index=True, width="stretch")
        old = project.get_field(key)
        if old and old.value != rows:
            changed.append(key)
    overwrite = True
    if changed:
        overwrite = st.checkbox("작성 화면에 이미 저장된 " + ", ".join(TARGET_NAME.get(k, k) for k in changed)
                                + "이 있어요. 위 내용으로 바꿀게요", key="overwrite_" + pid)
    if st.button("작성 화면으로 보내기", type="primary", key="publish_" + pid, disabled=not overwrite):
        try:
            ew.publish(project, replace_existing=bool(changed))
            save_project(project)
            st.success("보냈어요. 아래 링크로 작성 화면에 가서 이어서 작성하세요.")
        except ValueError as exc:
            st.error(str(exc))
    _form1_payoff(project)
    st.page_link("ui/cap_workspace_page.py", label="화학사고예방관리계획서 작성 화면으로 가기 →")
    st.page_link("ui/psm_workspace_page.py", label="공정안전보고서 작성 화면으로 가기 →")
    _records(project, names)


def _records(project, names) -> None:
    with st.expander("검토·감사용 기록 (값마다 어느 파일 어디서 왔는지)"):
        st.caption("나중에 검토자가 ‘이 값 어디서 왔어요?’라고 물으면 이 기록을 보여 주세요. 파일 지문(SHA256)으로 원본이 바뀌지 않았는지 확인할 수 있어요.")
        rows = [{"설비·물질": names(s["entity"]), "항목": _name(s["field"]), "값": _value(s["field"], s["chosen"]["value"]),
                 "누가": "자동" if s["method"] == "AUTO" else "담당자 확인", "읽은 곳": _where(s["chosen"])}
                for s in ew.slots(project) if s["chosen"]]
        st.dataframe(rows, hide_index=True, width="stretch")
        cols = st.columns(2)
        cols[0].download_button("검토 보고서 내려받기", ew.report(project).encode(), file_name="company_evidence_review.md", mime="text/markdown")
        cols[1].download_button("전체 출처 기록 내려받기 (JSON)", json.dumps(ew.graph(project), ensure_ascii=False, indent=2).encode(),
                                file_name="company_evidence_graph.json", mime="application/json")


# ---------------------------------------------------------------- 화면

st.set_page_config(page_title="사업장 업무", page_icon="📂", layout="wide")
st.title("화학사고예방관리계획서 자료 정리")
st.caption("회사 자료를 올리면 프로그램이 값을 찾아 정리하고, 사람이 확인해야 할 것만 물어봐요.")
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
    st.session_state[_step_key] = 1 if not ew.graph(_active)["documents"] else (2 if _question_count(_found) else 3)
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
