"""사고시나리오를 회사 파일에서 끝까지: 선정 → 피해반경·장외거리 → 보호대상 집계 → 시설빈도 → 공정안전보고서 별지 제19호의2.

사람은 화면에서 시나리오를 고르거나 숫자를 적지 않습니다.
- 대상 설비는 규정수량 비교(규정 제23조, 별표 2)로 프로그램이 정하고, 사고유형은 물질의 독성 구분·폭발한계로 정합니다.
- 바꾸고 싶으면 회사 작성용 엑셀의 ‘사고시나리오 검토’ 시트의 ‘선정할 사고유형’(‘선정 안 함’ 포함)·‘공정안전보고서 시나리오 구분’ 열을 고쳐 다시 올립니다.
- 액위·경계까지 거리·연소열 같은 계산 입력과 개시사건 개수·완화장치도 같은 파일에서 읽습니다.
- 보호대상은 별지 제8호 목록(주변 보호대상 조사표)에서 옵니다.
숫자는 모두 계산 엔진(cap_release_workspace·cap_impact_workspace·psm_form19_2_workspace)에서 나옵니다. AI는 선정 근거
문장을 다듬는 데만 쓰고, 근거에 없는 숫자·설비번호는 [확인 필요]로 바꿉니다. 결과는 언제나 초안입니다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from hashlib import sha256
import json
import re
from typing import Any, Mapping

from . import cap_form14_workspace as f14
from . import cap_impact_workspace as iw
from . import cap_scenario_workspace as sc
from . import evidence_workspace as ew
from . import psm_form19_2_workspace as f19
from .project import CONFIRMED_STATUSES, EvidenceRef, Stage2Project

INPUT_KEY = ew.SCENARIO_INPUT_KEY
FREQUENCY_INPUT_KEY = ew.FREQUENCY_INPUT_KEY
WEATHER_INPUT_KEY = "psm.risk.weather_inputs"
REASON_DRAFT_KEY = "cap.workspace.scenario_reason_drafts"
KIND_COLUMN, REASON_COLUMN, PSM_COLUMN = "선정할 사고유형", "시나리오 선정 근거", "공정안전보고서 시나리오 구분"
NOT_SELECTED = "선정 안 함"
PSM_WORST, PSM_ALTERNATIVE, PSM_UNUSED = "최악", "대안", "사용 안 함"
FILE_NAME = "회사 작성용 엑셀의 ‘사고시나리오 검토’ 시트"   # 자료 접수는 회사 작성용 엑셀 한 파일
REPORT_NAME = "영향범위_분석_근거서.docx"
NOTE = ew.LINK_NOTE + ": 사고시나리오 결과(회사 파일·규정수량 판정으로 프로그램이 계산한 초안)"
INPUT_COLUMNS = ("경계까지 거리(m)", "액위(m)", "누출지점 배관길이(m)", "비열비", "연소열", "비점", "액체비열", "기화열",
                 "증발잠열(kcal/kg)", "액체비열(kcal/kg·℃)", "증기밀도(kg/m3)", "사고원점 좌표")
OUTPUT_KEYS = (sc.SCENARIO_KEY, iw.IMPACT_TABLE_KEY, iw.TARGETS_KEY, iw.SUMMARY_KEY, iw.DOCUMENT_KEY,
               iw.NO_SCENARIO_KEY, f14.FREQUENCY_KEY, f19.TABLE_KEY)


@dataclass
class Problem:
    where: str          # 설비번호 또는 시나리오명
    what: str           # 무엇이 문제인지
    fix: str            # 어느 파일의 어느 항목을 고치면 되는지


@dataclass
class Plan:
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)        # 파일에서 ‘선정 안 함’으로 뺀 것
    problems: list[Problem] = field(default_factory=list)


@dataclass
class Outcome:
    plan: Plan
    impacts: list[iw.ScenarioImpact] = field(default_factory=list)
    psm: list[f19.Result] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def _clean(value: object) -> str:
    return "" if value is None else str(value).strip()


def _rows(project: Stage2Project, key: str) -> dict[str, dict[str, Any]]:
    record = project.get_field(key)
    if record is None or not isinstance(record.value, list):
        return {}
    return {_clean(r.get("설비번호")): dict(r) for r in record.value if isinstance(r, Mapping) and _clean(r.get("설비번호"))}


def file_inputs(project: Stage2Project) -> dict[str, dict[str, Any]]:
    """설비번호 → 사고시나리오 검토자료에서 읽은 값."""
    return _rows(project, INPUT_KEY)


def frequency_inputs(project: Stage2Project) -> dict[str, dict[str, Any]]:
    return _rows(project, FREQUENCY_INPUT_KEY)


def parse_kinds(text: str) -> list[str] | None:
    """‘독성 누출, 화재·폭발’ → 두 사고유형. ‘선정 안 함’ → None. 알아볼 수 없으면 빈 목록."""
    value = _clean(text)
    if re.sub(r"\s", "", value) in ("선정안함", "선정하지않음", "제외", "해당없음"):
        return None
    kinds = []
    if "독성" in value or "누출" in value and "화재" not in value:
        kinds.append(sc.TOXIC)
    if "화재" in value or "폭발" in value:
        kinds.append(sc.FIRE)
    return kinds


def _kind_reason(kind: str, chosen_by_file: bool) -> str:
    if chosen_by_file:
        return f"사고유형({kind})은 회사 검토자료에서 정했습니다."
    if kind == sc.TOXIC:
        return "별지 제6호 물성에 급성독성 구분이 있어 독성 누출 시나리오를 봅니다."
    if kind == sc.FIRE:
        return "별지 제6호 물성에 폭발한계가 있어 화재·폭발 시나리오를 봅니다."
    return ""


def rule_reason(target: sc.Target | None, kind: str, chosen_by_file: bool) -> str:
    """규정수량 판정과 사고유형 근거를 잇는 선정 근거 문장(숫자는 판정 결과의 것만)."""
    if target is None:
        return f"회사 검토자료에서 선정한 시나리오입니다. {_kind_reason(kind, chosen_by_file)}".strip()
    label = f"{target.tag}({target.name})" if target.name else target.tag
    if target.verdict == sc.TARGET and target.holding_kg is not None and target.threshold_kg is not None:
        head = (f"{label}: {target.material} 취급량 {target.holding_kg:g} kg이 규정수량 {target.threshold_kg:g} kg 이상이라 "
                "예비시나리오 대상 설비입니다(규정 제23조, 별표 2).")
    else:
        head = f"{label}: 회사 검토자료에서 선정했습니다(규정수량 판정 ‘{target.verdict}’ — {target.reason})."
    return f"{head} {_kind_reason(kind, chosen_by_file)}".strip()


def _reason_drafts(project: Stage2Project) -> dict[str, dict[str, str]]:
    record = project.get_field(REASON_DRAFT_KEY)
    return dict(record.value) if record is not None and isinstance(record.value, Mapping) else {}


def plan(project: Stage2Project) -> Plan:
    """확정할 시나리오 목록. 프로그램 제안(규정수량 대상) + 파일의 ‘선정할 사고유형’으로 고친 결과."""
    out = Plan()
    proposed: dict[str, list[dict[str, Any]]] = {}
    for row in sc.proposed_scenarios(project):
        proposed.setdefault(_clean(row.get("대상 설비번호")), []).append(row)
    targets = {t.tag: t for t in sc.evaluate(project)}
    facilities = {_clean(r.get("설비번호")): r for r in sc._facility_rows(project)}
    inputs = file_inputs(project)
    drafts = _reason_drafts(project)
    tags = list(proposed) + [t for t in inputs if t not in proposed and _clean(inputs[t].get(KIND_COLUMN))]
    for tag in tags:
        row = inputs.get(tag, {})
        choice = _clean(row.get(KIND_COLUMN))
        kinds = parse_kinds(choice) if choice else [_clean(p.get("사고유형")) for p in proposed.get(tag, [])]
        if kinds is None:
            out.skipped.append(f"{tag}: 회사 검토자료에서 ‘{NOT_SELECTED}’")
            continue
        if not kinds:
            out.problems.append(Problem(tag, f"‘{KIND_COLUMN}’ 값 ‘{choice}’을 알아보지 못했습니다.",
                                        f"{FILE_NAME}의 ‘{KIND_COLUMN}’에 ‘독성 누출’, ‘화재·폭발’ 또는 ‘{NOT_SELECTED}’을 적어 주세요."))
            continue
        if tag not in facilities:
            out.problems.append(Problem(tag, "설비 목록에 없는 설비번호입니다.",
                                        f"{FILE_NAME}의 설비번호를 설비대장과 같게 고쳐 주세요."))
            continue
        target = targets.get(tag)
        material = target.material if target else _clean(facilities[tag].get("취급물질"))
        for kind in kinds:
            base = next((p for p in proposed.get(tag, []) if p.get("사고유형") == kind), None)
            if base is None:
                unit = _clean(facilities[tag].get("단위공장·공정") or facilities[tag].get("단위공장")) or project.company_name
                base = {"단위공장": unit, "사고시나리오명": f"{tag} {material} {kind}".strip(), "대상 설비번호": tag,
                        "유해화학물질명": material, "사고유형": kind,
                        "취급량(kg)": f"{target.holding_kg:g}" if target and target.holding_kg is not None else ""}
            scenario = {k: v for k, v in base.items() if k != "선정 근거"}
            for column in INPUT_COLUMNS:
                if _clean(row.get(column)):
                    scenario[column] = _clean(row.get(column))
            rule = rule_reason(target, kind, bool(choice))
            company = _clean(row.get(REASON_COLUMN))
            draft = drafts.get(scenario["사고시나리오명"], {})
            if company:
                scenario["선정 근거"], scenario["선정 근거 출처"] = company, "회사 검토자료"
            elif draft.get("rule") == rule and draft.get("text"):
                scenario["선정 근거"], scenario["선정 근거 출처"] = draft["text"], f"AI 문장 다듬기({draft.get('model', '')})"
            else:
                scenario["선정 근거"], scenario["선정 근거 출처"] = rule, "규정수량 판정(프로그램)"
            scenario["공정안전보고서 구분"] = _clean(row.get(PSM_COLUMN))
            out.scenarios.append(scenario)
            if not _clean(row.get("경계까지 거리(m)")):
                out.problems.append(Problem(scenario["사고시나리오명"], "설비에서 사업장 경계까지 거리가 없어 장외거리를 구할 수 없습니다.",
                                            f"{FILE_NAME}에 설비번호 {tag}의 ‘경계까지 거리(m)’를 적어 주세요."))
    return out


def _saved(project: Stage2Project, key: str) -> Any:
    record = project.get_field(key)
    return None if record is None else record.value


def needs_refresh(project: Stage2Project) -> bool:
    """파일을 새로 올렸거나(결과가 보류로 바뀜) 계산 입력이 바뀌어 다시 계산해야 하는지."""
    planned = plan(project).scenarios
    if not planned and not sc.saved_scenarios(project):
        return False
    if planned != sc.saved_scenarios(project):
        return True
    for key in (sc.SCENARIO_KEY, iw.IMPACT_TABLE_KEY):
        record = project.get_field(key)
        if record is None or record.status not in CONFIRMED_STATUSES:
            return True
    return False


def _link(project: Stage2Project, key: str) -> None:
    """계산 결과도 회사 파일에서 이어진 초안으로 표시합니다(파일을 다시 올리면 보류로 바뀌어 다시 계산)."""
    record = project.get_field(key)
    if record is not None:
        project.set_field(key, record.label, record.value, record.status, evidence=list(record.evidence), note=NOTE)


def _frequency_rows(project: Stage2Project, scenarios: list[dict[str, Any]], off_site: set[str]) -> list[dict[str, Any]]:
    counts = frequency_inputs(project)
    rows = []
    for scenario in scenarios:
        name = scenario["사고시나리오명"]
        if name not in off_site:
            continue
        source = counts.get(_clean(scenario.get("대상 설비번호")), {})
        row: dict[str, Any] = {"사고시나리오명": name}
        for event in f14.EVENT_NAMES:
            row[event] = _clean(source.get(event))
        for column in ("개수 산정근거", "수동적 완화장치", "능동적 완화장치", "안전성확보설비 증빙"):
            row[column] = _clean(source.get(column))
        rows.append(row)
    return rows


def weather_inputs(project: Stage2Project) -> tuple[dict[str, str], str]:
    """별지 제19호의2 대기온도·습도와 출처. 회사 파일 값이 먼저, 없으면 기상청 관측 자료."""
    from . import psm_weather

    values, source = {}, ""
    record = project.get_field(WEATHER_INPUT_KEY)
    if record is not None and isinstance(record.value, Mapping):
        values = {k: _clean(v) for k, v in record.value.items() if _clean(v)}
        source = "회사 파일"
    basis = psm_weather.saved(project)
    filled = []
    if "대기온도(℃)" not in values and basis.get("최고기온(℃)") is not None:
        values["대기온도(℃)"] = f"{basis['최고기온(℃)']:g}"
        filled.append("대기온도")
    if "습도(%)" not in values and basis.get("평균 상대습도(%)") is not None:
        values["습도(%)"] = f"{basis['평균 상대습도(%)']:g}"
        filled.append("습도")
    if filled:
        station = f"기상청 {basis.get('관측소', '')} {basis.get('기간', '')}".strip()
        source = (source + " / " if source else "") + f"{'·'.join(filled)}: {station}"
    return values, source


def psm_designations(project: Stage2Project, scenarios: list[dict[str, Any]],
                     impacts: list[iw.ScenarioImpact]) -> dict[str, str]:
    """공정안전보고서 최악·대안 지정. 파일의 ‘공정안전보고서 시나리오 구분’이 먼저이고, 비어 있으면
    단위공장·사고유형마다 피해반경이 가장 큰 시나리오를 최악으로 씁니다."""
    radius = {i.name: i.radius_m or 0.0 for i in impacts}
    chosen: dict[str, str] = {}
    best: dict[tuple[str, str], tuple[float, str]] = {}
    for scenario in scenarios:
        name, mark = scenario["사고시나리오명"], _clean(scenario.get("공정안전보고서 구분"))
        if mark.startswith(PSM_WORST):
            chosen[name] = f19.WORST
        elif mark.startswith(PSM_ALTERNATIVE):
            chosen[name] = f19.ALTERNATIVE
        elif mark:
            continue                            # 사용 안 함
        else:
            key = (_clean(scenario.get("단위공장")), _clean(scenario.get("사고유형")))
            if key not in best or radius.get(name, 0.0) > best[key][0]:
                best[key] = (radius.get(name, 0.0), name)
    worst_kinds = {(_clean(s.get("단위공장")), _clean(s.get("사고유형"))) for s in scenarios
                   if chosen.get(s["사고시나리오명"]) == f19.WORST}
    for key, (_, name) in best.items():
        if key not in worst_kinds:
            chosen[name] = f19.WORST
    return chosen


def _problems(project: Stage2Project, outcome: Outcome) -> None:
    """계산 엔진이 남긴 문제를 ‘어느 파일의 어느 항목’으로 바꿔 모읍니다."""
    for impact in outcome.impacts:
        for problem in impact.problems:
            outcome.problems.append(Problem(impact.name, problem, _where_to_fix(problem, impact.tag)))
    counts = frequency_inputs(project)
    for impact in outcome.impacts:
        if impact.is_off_site and not any(_clean(counts.get(impact.tag, {}).get(e)) for e in f14.EVENT_NAMES):
            outcome.problems.append(Problem(impact.name, "장외로 영향이 나가는데 개시사건 개수가 없습니다(별지 제14호 시설빈도).",
                                            f"{FILE_NAME}에 설비번호 {impact.tag}의 개시사건 개수와 ‘개수 산정근거’를 적어 주세요."))
    for result in outcome.psm:
        for problem in result.problems:
            fix = ("‘사고시나리오 결과’ 화면에서 기상청 자료로 대기온도·습도를 채우거나, 회사 자료에 ‘대기온도(℃)’·‘습도(%)’를 적어 주세요."
                   if "대기온도" in problem or "습도" in problem else _where_to_fix(problem, result.row.get("대상 설비번호", "")))
            outcome.problems.append(Problem(result.row.get("시나리오명", ""), problem, fix))


def current(project: Stage2Project) -> Outcome:
    """저장된 결과를 다시 쓰지 않고 지금 상태를 계산해 보여 줄 때(화면). 오래된 결과면 먼저 refresh를 부르세요."""
    outcome = Outcome(plan(project))
    outcome.problems = list(outcome.plan.problems)
    if sc.saved_scenarios(project):
        outcome.impacts = iw.evaluate(project)
    record = project.get_field(f19.TABLE_KEY)
    if project.psm_in_scope and outcome.impacts:
        designations = psm_designations(project, sc.saved_scenarios(project), outcome.impacts)
        outcome.psm = f19.build(project, designations, weather_inputs(project)[0])
    elif record is not None and isinstance(record.value, list):
        outcome.psm = [f19.Result(dict(r)) for r in record.value if isinstance(r, Mapping)]
    _problems(project, outcome)
    return outcome


def refresh(project: Stage2Project) -> Outcome:
    """회사 파일과 별지 제8호 목록으로 시나리오 결과를 다시 계산해 작성자료(초안)에 반영합니다."""
    current_plan = plan(project)
    outcome = Outcome(current_plan, problems=list(current_plan.problems))
    project.set_field(sc.SCENARIO_KEY, "사고시나리오 목록(회사 파일·규정수량 판정)", current_plan.scenarios, ew.FILE_STATUS, note=NOTE)
    if not current_plan.scenarios:
        return outcome
    impacts = iw.evaluate(project)
    outcome.impacts = impacts
    report = iw.report_docx(project, impacts)
    ref = EvidenceRef(source_type="PROGRAM_OUTPUT", source_name=REPORT_NAME, sha256=sha256(report).hexdigest(),
                      location="사고시나리오 결과 화면에서 내려받기")
    iw.apply_to_forms(project, impacts, evidence_refs=[ref])
    off_site = {i.name for i in impacts if i.is_off_site}
    if off_site:
        project.set_field(iw.NO_SCENARIO_KEY, "장외 사고시나리오 없음", "아니오", "CALCULATED", note=NOTE)
    project.set_field(f14.FREQUENCY_KEY, "사고시나리오별 개시사건 개수(회사 파일)",
                      _frequency_rows(project, current_plan.scenarios, off_site), ew.FILE_STATUS, note=NOTE)
    if project.psm_in_scope:
        designations = psm_designations(project, current_plan.scenarios, impacts)
        outcome.psm = f19.build(project, designations, weather_inputs(project)[0])
        f19.save(project, outcome.psm)
    _problems(project, outcome)
    for key in OUTPUT_KEYS:
        if key != sc.SCENARIO_KEY:
            _link(project, key)
    return outcome


def _where_to_fix(problem: str, tag: str) -> str:
    """계산 엔진의 문제 문장 → 어느 파일의 어느 항목을 고칠지."""
    rules = (
        (("경계까지 거리", "사업장 경계까지"), f"{FILE_NAME}에 설비번호 {tag}의 ‘경계까지 거리(m)’를 적어 주세요."),
        (("액위",), f"{FILE_NAME}에 설비번호 {tag}의 ‘액위(m)’를 적어 주세요."),
        (("연소열",), f"{FILE_NAME}에 설비번호 {tag}의 ‘연소열(kJ/kg)’을 적어 주세요."),
        (("비점", "기화열", "액체비열"), f"{FILE_NAME}에 설비번호 {tag}의 ‘비점(℃)’·‘액체비열(kJ/kg·K)’·‘기화열(kJ/kg)’을 적어 주세요."),
        (("연결구",), "회사 작성용 엑셀의 ‘설비’ 시트에 이 설비의 ‘최대 연결구 크기(mm)’를 적어 주세요."),
        (("운전온도", "운전압력"), "회사 작성용 엑셀의 ‘설비’ 시트에 이 설비의 운전압력·운전온도를 적어 주세요."),
        (("비중",), "회사 작성용 엑셀의 ‘설비’ 또는 ‘물질’ 시트에 비중을 적어 주세요."),
        (("분자량", "증기압"), "회사 작성용 엑셀의 ‘물질’ 시트에 이 물질의 분자량·증기압을 적어 주세요."),
        (("최대보유량",), "회사 작성용 엑셀의 ‘설비’ 시트에서 용량·최대보유량을 확인해 주세요."),
        (("끝점", "ERPG", "AEGL", "독성"), "물질의 CAS 번호와 독성 끝점 자료를 확인해 주세요(SDS 물성표)."),
    )
    for words, fix in rules:
        if any(word in problem for word in words):
            return fix
    return "영향범위 분석 근거서의 가정과 회사 작성용 엑셀의 입력값을 확인해 주세요."


def report_docx(project: Stage2Project) -> bytes:
    return iw.report_docx(project, iw.evaluate(project))


# ---------------------------------------------------------------- AI 문장 다듬기(선정 근거)

_REASON_INSTRUCTIONS = (
    "너는 화학사고예방관리계획서의 사고시나리오 선정 근거 문장을 다듬는 도우미다. 입력의 rule_text가 사실의 전부다. "
    "rule_text에 없는 숫자·설비번호·물질명·법령 조항을 새로 쓰지 않는다. 뜻을 바꾸지 말고 한두 문장의 공문서 문체로 다듬는다. "
    "응답은 {\"text\": \"...\"} 형식의 JSON 객체 하나다."
)


def polish_reasons(project: Stage2Project, client) -> list[dict[str, Any]]:
    """프로그램이 쓴 선정 근거(회사 문장이 없는 것)를 AI로 다듬어 보관합니다. 근거 없는 숫자는 [확인 필요]로 바꿉니다."""
    from . import cap_fact_drafting as fd

    drafts = _reason_drafts(project)
    results = []
    for scenario in plan(project).scenarios:
        if scenario.get("선정 근거 출처") == "회사 검토자료":
            continue
        target = next((t for t in sc.evaluate(project) if t.tag == scenario["대상 설비번호"]), None)
        rule = rule_reason(target, scenario["사고유형"], bool(_clean(file_inputs(project).get(
            scenario["대상 설비번호"], {}).get(KIND_COLUMN))))
        item = fd.Item(system="CAP", key=scenario["사고시나리오명"], label="시나리오 선정 근거", section="사고시나리오",
                       field_key=sc.SCENARIO_KEY, request="선정 근거 문장",
                       basis=[fd.Basis("선정 근거", rule, "규정수량 판정", "rule")])
        try:
            answer = client.generate_json(instructions=_REASON_INSTRUCTIONS,
                                          prompt=json.dumps({"rule_text": rule}, ensure_ascii=False))
            text = _clean((answer or {}).get("text"))
            if not text:
                raise ValueError("빈 응답")
            text, replaced = fd.sanitize(text, item)
        except Exception as exc:          # AI가 안 되면 규칙 문장을 그대로 둡니다
            results.append({"시나리오": scenario["사고시나리오명"], "결과": f"규칙 문장 유지({type(exc).__name__})"})
            continue
        drafts[scenario["사고시나리오명"]] = {"rule": rule, "text": text, "model": getattr(client, "model", "로컬 AI"),
                                          "date": date.today().isoformat()}
        results.append({"시나리오": scenario["사고시나리오명"], "결과": "다듬음",
                        "바꾼 값": ", ".join(replaced)})
    project.set_field(REASON_DRAFT_KEY, "사고시나리오 선정 근거 AI 문장", drafts, "AI_DRAFT",
                      note="규칙 문장을 AI로 다듬은 것. 규칙 문장이 바뀌면 쓰지 않음")
    return results
