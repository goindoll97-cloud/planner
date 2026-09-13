from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Mapping
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .project import EvidenceRef, Stage2Project
from .requirements import cap_field_labels, psm_field_labels
from .intake import field_label, selected_requirement_specs


SCHEMA_VERSION = "stage2-integrated-authoring-v1"
META_SHEET = "_시스템정보"
MODE_INPUT = "INPUT"
MODE_EXAMPLE = "EXAMPLE"

PSM_FULL = "공정안전보고서"
CAP_FULL = "화학사고예방관리계획서"

HEADER_FILL = "1F4E78"
SUBHEADER_FILL = "D9EAF7"
INPUT_FILL = "FFF2CC"
EXAMPLE_FILL = "E2F0D9"
NOTE_FILL = "F2F2F2"

PROTECTED_STAGE1_FIELDS = {
    "business.company_name",
    "business.address",
    "inventory.chemicals",
    "inventory.facilities",
}

TABLE_SPECS: tuple[dict[str, Any], ...] = (
    {
        "sheet": "02_화학물질정보",
        "scope": "COMMON",
        "title": "화학물질 정보",
        "targets": ("cap.chemical.details",),
        "headers": (
            "물질명", "CAS 번호", "함량(%)", "물리적 상태", "최대보유량", "단위",
            "사용·저장 공정", "주요 용도", "비고",
        ),
        "example": (
            ("톨루엔", "108-88-3", 99.5, "액체", 15000, "kg", "원료 저장·혼합", "원료", "예시값"),
        ),
    },
    {
        "sheet": "03_설비정보",
        "scope": "COMMON",
        "title": "장치·설비 통합정보",
        "targets": ("psm.psi.equipment_specs", "cap.facility.equipment_specs"),
        "headers": (
            "설비번호", "설비명", "설비종류", "단위공장·공정", "취급물질", "용량", "용량단위",
            "설계압력", "설계온도", "운전압력", "운전온도", "재질", "최대보유량(kg)", "P&ID 번호", "비고",
        ),
        "example": (
            ("TK-101", "톨루엔 저장탱크", "저장탱크", "원료저장", "톨루엔", 20, "m3", "0.49 MPa", "80 ℃", "0.15 MPa", "30 ℃", "SUS304", 15000, "PID-101", "예시값"),
        ),
    },
    {
        "sheet": "04_안전밸브_파열판",
        "scope": "COMMON",
        "title": "안전밸브 및 파열판 통합정보",
        "targets": ("psm.psi.relief_device_specs", "cap.safety.relief_device_specs"),
        "headers": (
            "안전밸브·파열판 번호", "보호대상 설비번호", "형식", "설정압력", "배출용량", "배출물질",
            "배출상태", "최종 배출·처리 지점", "관련 P&ID 번호", "비고",
        ),
        "example": (
            ("PSV-101", "TK-101", "안전밸브", "0.45 MPa", "1200 kg/h", "톨루엔 증기", "기체", "스크러버", "PID-101", "예시값"),
        ),
    },
    {
        "sheet": "05_가스누출감지_경보장치",
        "scope": "COMMON",
        "title": "가스누출감지 및 경보장치 통합정보",
        "targets": ("psm.psi.gas_detection", "cap.safety.gas_detection"),
        "headers": (
            "감지기 번호", "설치위치", "검출대상 물질", "감지방식", "경보 설정값", "경보 위치",
            "비상전원 여부", "관련 도면번호", "비고",
        ),
        "example": (
            ("GD-101", "TK-101 방유제 내", "톨루엔", "고정식", "10% LEL", "중앙제어실", "예", "GA-101", "예시값"),
        ),
    },
    {
        "sheet": "10_동력기계",
        "scope": "PSM",
        "title": "동력기계 목록",
        "targets": ("psm.psi.machinery_list",),
        "headers": (
            "기계번호", "기계명", "형식", "용량", "동력", "재질", "취급물질", "설치공정", "관련 P&ID 번호", "비고",
        ),
        "example": (
            ("P-101", "원료 이송펌프", "원심펌프", "20 m3/h", "7.5 kW", "SUS304", "톨루엔", "원료저장", "PID-101", "예시값"),
        ),
    },
    {
        "sheet": "11_배관_개스킷",
        "scope": "PSM",
        "title": "배관 및 개스킷 명세",
        "targets": ("psm.psi.piping_gasket_specs",),
        "headers": (
            "배관번호·Class", "유체명", "배관재질", "호칭경", "설계압력", "설계온도", "개스킷 재질", "관련 P&ID 번호", "비고",
        ),
        "example": (
            ("PCL-150", "톨루엔", "SUS304", "50A", "0.49 MPa", "80 ℃", "PTFE", "PID-101", "예시값"),
        ),
    },
    {
        "sheet": "20_배출물질_처리시설",
        "scope": "CAP",
        "title": "배출물질 처리시설 현황",
        "targets": ("cap.safety.waste_treatment",),
        "headers": (
            "시설번호", "시설명", "처리대상 물질", "처리방식", "처리용량", "연결 설비·배관", "최종 배출지점", "비고",
        ),
        "example": (
            ("SC-101", "유기용제 스크러버", "톨루엔 증기", "흡수", "1500 m3/h", "PSV-101", "대기배출구", "예시값"),
        ),
    },
)

ATTACHMENT_KINDS = {
    "DOCUMENT_SET", "DRAWING", "DRAWING_SET", "DRAWING_AND_DATA", "DRAWING_AND_TABLE",
    "ANALYSIS_DOCUMENT", "CALCULATION_AND_DRAWING", "CALCULATION_AND_MODEL",
}

EXAMPLE_VALUES: dict[str, Any] = {
    "cap.business.representative": "홍길동",
    "cap.business.registration_no": "123-45-67890",
    "cap.business.contact": "053-000-0000",
    "cap.business.submission_type": "신규",
    "cap.business.writer_info": "환경안전팀 김담당 / 053-000-0001",
    "psm.business.overview": "본 사업장은 원료 저장, 혼합 및 제품 출하 공정으로 구성되며 주요 공정설비는 저장탱크, 혼합기 및 이송펌프이다.",
    "process.description": "원료는 저장탱크에서 이송펌프로 혼합공정에 공급되고, 정해진 운전조건에서 혼합 후 제품저장설비로 이송된다.",
    "psm.risk.purpose": "공정 내 잠재 유해·위험요인을 체계적으로 확인하고 필요한 개선대책을 도출하기 위함.",
    "psm.risk.characteristics": "인화성 액체 취급과 이송배관 누출에 따른 화재·폭발 위험이 주요 위험특성이다.",
    "psm.risk.mitigation": "누출감지, 긴급차단, 방유제 및 비상대응절차를 운영한다.",
    "psm.operation.sop": "정상운전, 운전개시, 운전정지 및 비상정지 절차를 사내 안전운전지침서에 따라 수행한다.",
    "psm.operation.maintenance": "설비별 점검주기와 정비기준을 정하고 점검·보수 이력을 관리한다.",
    "psm.operation.work_permit": "화기작업, 밀폐공간작업 등 위험작업은 안전작업허가 절차에 따라 승인 후 수행한다.",
    "psm.operation.contractor": "도급작업 전 작업위험과 안전수칙을 공유하고 작업 중 이행상태를 확인한다.",
    "psm.operation.training": "신규·정기·작업변경 시 필요한 안전보건교육을 실시하고 기록을 보관한다.",
    "psm.operation.prestartup": "신설·변경 설비의 가동 전 설계·시공·안전장치·절차 준비상태를 확인한다.",
    "psm.operation.moc": "설비, 원료, 운전조건 및 절차 변경 시 변경요소 관리절차에 따라 사전 검토한다.",
    "psm.operation.audit": "정기적으로 공정안전관리 이행상태를 자체 점검하고 개선조치를 관리한다.",
    "psm.operation.incident_investigation": "공정사고 발생 시 원인조사 후 재발방지대책을 수립하고 이행상태를 확인한다.",
    "psm.emergency.contacts": "비상상황 발생 시 중앙제어실을 통해 비상연락망으로 상황을 전파한다.",
    "psm.emergency.roles_procedures": "비상대응조직별 지휘, 신고, 초기대응, 대피 및 복구 임무를 정하여 운영한다.",
    "psm.emergency.training": "정기 비상조치 교육과 훈련을 실시하고 결과를 기록한다.",
    "cap.prevention.safety_policy": "화학사고 예방과 인명·환경피해 최소화를 안전관리의 기본방침으로 한다.",
    "cap.prevention.training_plan": "취급작업자와 비상대응조직을 대상으로 정기 교육·훈련을 실시한다.",
    "cap.prevention.change_management_plan": "유해화학물질, 취급시설, 운전조건 또는 절차 변경 시 사전 검토 후 변경사항을 관리한다.",
    "cap.internal.shutdown_authority": "공정반장 또는 중앙제어실 책임자",
    "cap.internal.shutdown_procedure": "이상상황 확인 후 원료공급 차단, 관련 설비 정지, 상황전파 순으로 조치한다.",
    "cap.internal.communication_system": "비상방송, 유선전화 및 비상연락망을 이용하여 내부에 상황을 전달한다.",
    "cap.external.communication_plan": "주변 지역사회와 관계기관에 사고위험정보와 비상시 행동요령을 정기적으로 안내한다.",
}


@dataclass(frozen=True)
class IntegratedImportResult:
    updated_fields: int
    table_fields: int
    attachment_declarations: int
    warnings: tuple[str, ...]


def _scope_matches(project: Stage2Project, scope: str) -> bool:
    if scope == "COMMON":
        return project.psm_in_scope or project.cap_in_scope
    if scope == "PSM":
        return project.psm_in_scope
    if scope == "CAP":
        return project.cap_in_scope
    return False


def _safe_sheet_name(name: str) -> str:
    text = re.sub(r"[\\/*?:\[\]]", "_", str(name))
    return text[:31]


def _style_title(ws, title: str, note: str = "") -> None:
    ws["A1"] = title
    ws["A1"].font = Font(size=14, bold=True, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=HEADER_FILL)
    ws["A1"].alignment = Alignment(vertical="center")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=6)
    if note:
        ws["A2"] = note
        ws["A2"].fill = PatternFill("solid", fgColor=NOTE_FILL)
        ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=6)


def _style_header(row) -> None:
    for cell in row:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=HEADER_FILL)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _autosize(ws, max_width: int = 34) -> None:
    for column_cells in ws.columns:
        letter = get_column_letter(column_cells[0].column)
        width = 10
        for cell in column_cells:
            value = "" if cell.value is None else str(cell.value)
            width = max(width, min(len(value) + 2, max_width))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        ws.column_dimensions[letter].width = width


def _normalized_mapping(row: Mapping[str, Any]) -> dict[str, Any]:
    def key(value: object) -> str:
        return re.sub(r"[^0-9a-z가-힣]", "", str(value or "").lower())
    return {key(k): v for k, v in row.items()}


def _pick(row: Mapping[str, Any], *aliases: str) -> Any:
    normalized = _normalized_mapping(row)
    for alias in aliases:
        token = re.sub(r"[^0-9a-z가-힣]", "", alias.lower())
        if token in normalized and normalized[token] not in (None, ""):
            return normalized[token]
    return ""


def _prefill_chemicals(project: Stage2Project) -> list[list[Any]]:
    record = project.get_field("inventory.chemicals")
    rows = record.value if record and isinstance(record.value, list) else []
    out: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        out.append([
            _pick(row, "물질명", "화학물질명", "제품명", "substance", "name"),
            _pick(row, "CAS 번호", "CAS", "CAS No", "CAS번호"),
            _pick(row, "함량(%)", "함량", "농도", "content", "purity"),
            _pick(row, "물리적 상태", "상태", "state", "phase"),
            _pick(row, "최대보유량", "최대저장량", "보유량", "quantity", "holding"),
            _pick(row, "단위", "unit"),
            _pick(row, "공정", "사용공정", "저장공정", "process"),
            _pick(row, "용도", "usage"),
            _pick(row, "비고", "note"),
        ])
    return out


def _prefill_facilities(project: Stage2Project) -> list[list[Any]]:
    record = project.get_field("inventory.facilities")
    rows = record.value if record and isinstance(record.value, list) else []
    out: list[list[Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        out.append([
            _pick(row, "설비번호", "시설번호", "장치번호", "tag", "equipment id"),
            _pick(row, "설비명", "시설명", "장치명", "equipment"),
            _pick(row, "설비종류", "시설종류", "type"),
            _pick(row, "단위공장", "공정", "process", "unit"),
            _pick(row, "취급물질", "물질명", "chemical"),
            _pick(row, "용량", "capacity"),
            _pick(row, "용량단위", "단위", "unit"),
            _pick(row, "설계압력", "design pressure"),
            _pick(row, "설계온도", "design temperature"),
            _pick(row, "운전압력", "operating pressure"),
            _pick(row, "운전온도", "operating temperature"),
            _pick(row, "재질", "material"),
            _pick(row, "최대보유량", "최대보유량(kg)", "holding"),
            _pick(row, "P&ID 번호", "P&ID", "PID"),
            _pick(row, "비고", "note"),
        ])
    return out


def _table_rows_for(project: Stage2Project, sheet: str, example: bool, spec: Mapping[str, Any]) -> list[list[Any]]:
    if example:
        return [list(row) for row in spec.get("example", ())]
    if sheet == "02_화학물질정보":
        return _prefill_chemicals(project)
    if sheet == "03_설비정보":
        return _prefill_facilities(project)
    return []


def _write_table_sheet(wb: Workbook, project: Stage2Project, spec: Mapping[str, Any], *, example: bool, meta_rows: list[list[Any]]) -> None:
    sheet_name = _safe_sheet_name(str(spec["sheet"]))
    ws = wb.create_sheet(sheet_name)
    _style_title(
        ws,
        str(spec["title"]),
        "노란색 영역에 사업장 정보를 입력하세요. 공정안전보고서와 화학사고예방관리계획서에 공통으로 필요한 정보는 한 번만 작성합니다."
        if not example else
        "작성예시입니다. 아래 값은 실제 사업장 정보가 아니며 입력 방법을 보여주기 위한 예시입니다.",
    )
    header_row = 4
    headers = list(spec["headers"])
    for col, value in enumerate(headers, 1):
        ws.cell(header_row, col, value)
    _style_header(ws[header_row])

    rows = _table_rows_for(project, sheet_name, example, spec)
    first_data = header_row + 1
    for r_idx, row in enumerate(rows, first_data):
        for c_idx, value in enumerate(row, 1):
            ws.cell(r_idx, c_idx, value)
            ws.cell(r_idx, c_idx).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
    reserve_to = max(first_data + 24, first_data + len(rows))
    for row in ws.iter_rows(min_row=first_data, max_row=reserve_to, min_col=1, max_col=len(headers)):
        for cell in row:
            if cell.fill.fill_type is None:
                cell.fill = PatternFill("solid", fgColor=INPUT_FILL if not example else EXAMPLE_FILL)
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    ws.freeze_panes = f"A{first_data}"
    _autosize(ws)
    targets = [key for key in spec.get("targets", ()) if _target_in_scope(project, key)]
    meta_rows.append(["TABLE", sheet_name, "|".join(targets), header_row, "", ""])


def _target_in_scope(project: Stage2Project, field_key: str) -> bool:
    if field_key.startswith("psm."):
        return project.psm_in_scope
    if field_key.startswith("cap."):
        return project.cap_in_scope
    return True


def _question_text(label: str, request_text: str) -> str:
    request = str(request_text or "").strip()
    if request and request != label:
        return request
    return f"{label}을(를) 사업장 실제 기준으로 작성해 주세요."


def _example_value(field_key: str, label: str) -> str:
    if field_key in EXAMPLE_VALUES:
        return str(EXAMPLE_VALUES[field_key])
    if "연락" in label:
        return "예: 담당부서, 담당자, 연락처와 연락 순서를 실제 기준으로 입력"
    if "계획" in label or "절차" in label or "방침" in label:
        return f"예: {label}의 실제 운영방법, 담당자, 주기 및 기록방법을 간단히 입력"
    if "현황" in label or "정보" in label:
        return f"예: {label}에 해당하는 사업장 실제 현황을 입력"
    return f"예: {label}에 해당하는 사업장 실제 내용을 입력"


def _handled_fields(project: Stage2Project) -> set[str]:
    handled = set(PROTECTED_STAGE1_FIELDS)
    for spec in TABLE_SPECS:
        if _scope_matches(project, str(spec["scope"])):
            handled.update(key for key in spec["targets"] if _target_in_scope(project, key))
    handled.update({"process.description"})
    return handled


def _build_question_groups(project: Stage2Project) -> dict[str, list[tuple[str, str, str, str]]]:
    groups: dict[str, list[tuple[str, str, str, str]]] = {}
    handled = _handled_fields(project)
    seen: set[str] = set()
    for spec in selected_requirement_specs(project):
        if spec.input_kind in ATTACHMENT_KINDS or spec.input_kind in {"DOCUMENT_SET", "DRAWING"}:
            continue
        for key in spec.field_keys:
            if key in handled or key in seen or key in PROTECTED_STAGE1_FIELDS:
                continue
            if not _target_in_scope(project, key):
                continue
            seen.add(key)
            if spec.system == "PSM":
                group = f"공정안전보고서_{spec.section}"
            elif spec.system == "CAP":
                section = re.sub(r"^3\.\d+\s*", "", spec.section).strip()
                group = f"화학사고예방관리계획서_{section or '작성정보'}"
            else:
                group = "공통_추가정보"
            label = field_label(key)
            groups.setdefault(group, []).append((key, label, _question_text(label, spec.request_text), spec.legal_basis))
    return groups


def _write_question_sheet(wb: Workbook, sheet_name: str, rows: Iterable[tuple[str, str, str, str]], *, project: Stage2Project, example: bool, meta_rows: list[list[Any]]) -> None:
    ws = wb.create_sheet(_safe_sheet_name(sheet_name))
    _style_title(
        ws,
        sheet_name.replace("_", " "),
        "질문을 읽고 회사 작성값에 실제 사업장 기준으로 입력하세요. 모르면 임의로 작성하지 말고 빈칸으로 두십시오."
        if not example else
        "작성예시입니다. 표현방식을 참고하되 실제 사업장 사실과 다른 내용을 복사하지 마십시오.",
    )
    headers = ["확인할 내용", "회사 작성값", "작성 예", "작성방법"]
    for col, value in enumerate(headers, 1):
        ws.cell(4, col, value)
    _style_header(ws[4])
    current = 5
    for field_key, label, question, basis in rows:
        record = project.get_field(field_key)
        current_value = ""
        if not example and record and record.value not in (None, "", [], {}):
            current_value = record.value if isinstance(record.value, (str, int, float, bool)) else ""
        ws.cell(current, 1, question)
        ws.cell(current, 2, _example_value(field_key, label) if example else current_value)
        ws.cell(current, 3, _example_value(field_key, label))
        ws.cell(current, 4, "확인 가능한 사내 문서나 담당자 확인을 바탕으로 작성. 모르는 내용은 빈칸 유지.")
        ws.cell(current, 2).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
        for col in range(1, 5):
            ws.cell(current, col).alignment = Alignment(vertical="top", wrap_text=True)
        meta_rows.append(["FORM", ws.title, field_key, current, 2, basis])
        current += 1
    ws.freeze_panes = "A5"
    _autosize(ws, max_width=42)
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 52
    ws.column_dimensions["C"].width = 52
    ws.column_dimensions["D"].width = 36


def _attachment_specs(project: Stage2Project) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for spec in selected_requirement_specs(project):
        if spec.input_kind not in ATTACHMENT_KINDS and spec.input_kind not in {"DOCUMENT_SET", "DRAWING"}:
            continue
        for key in spec.field_keys:
            if key in seen or key in PROTECTED_STAGE1_FIELDS:
                continue
            if not _target_in_scope(project, key):
                continue
            seen.add(key)
            rows.append((key, field_label(key), spec.request_text or spec.description))
    return rows


def _write_attachment_sheet(wb: Workbook, project: Stage2Project, *, example: bool, meta_rows: list[list[Any]]) -> None:
    ws = wb.create_sheet("07_도면_첨부자료목록")
    _style_title(
        ws,
        "도면·첨부자료 목록",
        "PFD, P&ID, 배치도, 물질안전보건자료(MSDS) 등 파일 자체는 이 Excel에 넣지 말고 파일명과 도면번호만 적은 뒤 프로그램에서 별도로 업로드하세요.",
    )
    headers = ["자료종류", "파일명", "도면·문서번호", "개정번호·일자", "비고", "확인사항"]
    for col, value in enumerate(headers, 1):
        ws.cell(4, col, value)
    _style_header(ws[4])
    current = 5
    for field_key, label, request in _attachment_specs(project):
        record = project.get_field(field_key)
        declared = ""
        if not example and record and isinstance(record.value, str):
            declared = record.value
        ws.cell(current, 1, label)
        ws.cell(current, 2, f"{re.sub(r'[^0-9A-Za-z가-힣]+', '_', label)}.pdf" if example else declared)
        ws.cell(current, 3, "PID-101" if example and "P&ID" in label else "")
        ws.cell(current, 4, "Rev.3 / 2026-08-01" if example else "")
        ws.cell(current, 5, "최신본" if example else "")
        ws.cell(current, 6, request)
        for col in (2, 3, 4, 5):
            ws.cell(current, col).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
        for col in range(1, 7):
            ws.cell(current, col).alignment = Alignment(vertical="top", wrap_text=True)
        meta_rows.append(["ATTACHMENT", ws.title, field_key, current, 2, ""])
        current += 1
    ws.freeze_panes = "A5"
    _autosize(ws, max_width=40)


def _write_guide(wb: Workbook, project: Stage2Project, *, example: bool) -> None:
    ws = wb.active
    ws.title = "00_작성안내"
    title = "통합 작성자료 작성예시" if example else "통합 작성자료"
    _style_title(ws, title, "공정안전보고서와 화학사고예방관리계획서의 중복정보를 한 번만 입력하도록 구성한 프로그램용 작성자료입니다.")
    scope = []
    if project.psm_in_scope:
        scope.append(PSM_FULL)
    if project.cap_in_scope:
        scope.append(CAP_FULL)
    guide_rows = [
        ("작성범위", ", ".join(scope)),
        ("문서 성격", "프로그램 통합 작성자료(법정 별지서식 자체가 아님)"),
        ("작성 원칙", "노란색 칸에 실제 사업장 사실만 입력하고, 모르는 내용은 추측하지 말고 빈칸으로 둡니다."),
        ("중복 입력", "공통 화학물질·설비·안전밸브·감지기 정보는 한 번만 작성하며 선택한 두 보고서에 재사용됩니다."),
        ("도면·이미지", "PFD, P&ID, 배치도, 물질안전보건자료(MSDS) 등 파일은 07_도면_첨부자료목록에 파일명만 적고 프로그램에서 별도 업로드합니다."),
        ("Stage 1 승계", "판정진단에서 확인된 회사명·주소·화학물질·시설자료는 가능한 범위에서 미리 채워집니다. 판정에 사용된 사실을 바꿔야 하면 먼저 판정진단을 다시 수행합니다."),
        ("작성예시", "작성예시 파일은 입력 방법 참고용이며 프로그램에 제출할 수 없습니다."),
        ("법적 근거", "평소 화면에서는 최소화하고, 누락·확인 필요 항목이 발생했을 때 프로그램의 ‘왜 필요한가?’에서 관련 법령·서식·매뉴얼 근거를 확인합니다."),
    ]
    ws["A4"] = "구분"
    ws["B4"] = "내용"
    _style_header(ws[4])
    for idx, (kind, text) in enumerate(guide_rows, 5):
        ws.cell(idx, 1, kind)
        ws.cell(idx, 2, text)
        ws.cell(idx, 2).alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 100


def _write_business_sheet(wb: Workbook, project: Stage2Project, *, example: bool, meta_rows: list[list[Any]]) -> None:
    ws = wb.create_sheet("01_사업장정보")
    _style_title(ws, "사업장 정보", "판정진단에서 확인된 정보는 미리 채워집니다. 내용이 달라졌다면 이 파일에서 고치기 전에 판정진단을 다시 수행하세요.")
    ws.append([])
    headers = ["확인할 내용", "회사 작성값", "작성 예", "작성방법"]
    for col, value in enumerate(headers, 1):
        ws.cell(4, col, value)
    _style_header(ws[4])
    base = [
        ("business.company_name", "회사명", "㈜가상화학", "Stage 1에서 승계된 회사명을 확인"),
        ("business.address", "사업장 소재지", "대구광역시 ○○구 ○○로 00", "Stage 1에서 승계된 사업장 소재지를 확인"),
    ]
    current = 5
    for key, label, example_value, guidance in base:
        record = project.get_field(key)
        value = example_value if example else (record.value if record else "")
        ws.cell(current, 1, label)
        ws.cell(current, 2, value)
        ws.cell(current, 3, example_value)
        ws.cell(current, 4, guidance)
        ws.cell(current, 2).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
        meta_rows.append(["PROTECTED", ws.title, key, current, 2, "Stage 1 판정자료"])
        current += 1

    # CAP의 사업장 일반정보 중 Stage 1에서 받지 않은 값은 여기에서 한 번만 입력한다.
    if project.cap_in_scope:
        labels = cap_field_labels()
        for key in (
            "cap.business.representative", "cap.business.registration_no", "cap.business.contact",
            "cap.business.submission_type", "cap.business.writing_level", "cap.business.other_system_review",
            "cap.business.writer_info",
        ):
            label = labels.get(key, field_label(key))
            record = project.get_field(key)
            value = _example_value(key, label) if example else (record.value if record and isinstance(record.value, (str, int, float)) else "")
            ws.cell(current, 1, label)
            ws.cell(current, 2, value)
            ws.cell(current, 3, _example_value(key, label))
            ws.cell(current, 4, "사업자등록증, 사내 담당자 확인 등 실제 근거를 바탕으로 입력")
            ws.cell(current, 2).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
            meta_rows.append(["FORM", ws.title, key, current, 2, ""])
            current += 1
    ws.freeze_panes = "A5"
    _autosize(ws, max_width=44)
    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 42
    ws.column_dimensions["C"].width = 42
    ws.column_dimensions["D"].width = 44


def _write_process_sheet(wb: Workbook, project: Stage2Project, *, example: bool, meta_rows: list[list[Any]]) -> None:
    ws = wb.create_sheet("06_공정정보")
    _style_title(ws, "공정 정보", "공정 흐름과 정상운전 정보를 회사 담당자가 이해하는 수준으로 적어 주세요. 프로그램이 법정 문서 문장으로 다듬을 때 이 사실정보만 사용합니다.")
    headers = ["확인할 내용", "회사 작성값", "작성 예", "작성방법"]
    for col, value in enumerate(headers, 1):
        ws.cell(4, col, value)
    _style_header(ws[4])
    key = "process.description"
    record = project.get_field(key)
    value = _example_value(key, "공정개요") if example else (record.value if record and isinstance(record.value, str) else "")
    ws.cell(5, 1, "원료 투입부터 제품·부산물 배출까지 주요 공정 흐름과 정상운전 조건을 설명해 주세요.")
    ws.cell(5, 2, value)
    ws.cell(5, 3, _example_value(key, "공정개요"))
    ws.cell(5, 4, "공정단계, 주요 설비, 취급물질, 정상 운전조건을 사실 위주로 입력")
    ws.cell(5, 2).fill = PatternFill("solid", fgColor=EXAMPLE_FILL if example else INPUT_FILL)
    meta_rows.append(["FORM", ws.title, key, 5, 2, ""])
    _autosize(ws, max_width=48)
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 60
    ws.column_dimensions["C"].width = 60
    ws.column_dimensions["D"].width = 42


def _write_meta(wb: Workbook, project: Stage2Project, *, example: bool, meta_rows: list[list[Any]]) -> None:
    ws = wb.create_sheet(META_SHEET)
    ws.append(["schema_version", SCHEMA_VERSION])
    ws.append(["workbook_mode", MODE_EXAMPLE if example else MODE_INPUT])
    ws.append(["project_id", project.project_id])
    ws.append(["psm_selected", str(project.psm_in_scope)])
    ws.append(["cap_selected", str(project.cap_in_scope)])
    ws.append([])
    ws.append(["kind", "sheet", "field_keys", "row_or_header", "value_column", "basis"])
    for row in meta_rows:
        ws.append(row)
    ws.sheet_state = "hidden"


def build_integrated_authoring_workbook(project: Stage2Project, *, example: bool = False) -> bytes:
    if not project.scope_confirmed or not (project.psm_in_scope or project.cap_in_scope):
        raise ValueError("먼저 작성범위를 선택해야 통합 작성자료를 만들 수 있습니다.")

    wb = Workbook()
    meta_rows: list[list[Any]] = []
    _write_guide(wb, project, example=example)
    _write_business_sheet(wb, project, example=example, meta_rows=meta_rows)

    for spec in TABLE_SPECS:
        if _scope_matches(project, str(spec["scope"])):
            _write_table_sheet(wb, project, spec, example=example, meta_rows=meta_rows)

    _write_process_sheet(wb, project, example=example, meta_rows=meta_rows)
    _write_attachment_sheet(wb, project, example=example, meta_rows=meta_rows)

    groups = _build_question_groups(project)
    for group_name, rows in groups.items():
        if not rows:
            continue
        # 이미 별도 공정정보 시트에서 받는 값은 제외한다.
        filtered = [row for row in rows if row[0] != "process.description"]
        if filtered:
            _write_question_sheet(wb, group_name, filtered, project=project, example=example, meta_rows=meta_rows)

    _write_meta(wb, project, example=example, meta_rows=meta_rows)
    output = BytesIO()
    wb.save(output)
    return output.getvalue()


def _meta_map(wb) -> tuple[dict[str, str], list[dict[str, Any]]]:
    if META_SHEET not in wb.sheetnames:
        raise ValueError("프로그램 통합 작성자료가 아닙니다. _시스템정보 시트를 찾을 수 없습니다.")
    ws = wb[META_SHEET]
    header: dict[str, str] = {}
    for row in range(1, 6):
        key = str(ws.cell(row, 1).value or "").strip()
        value = str(ws.cell(row, 2).value or "").strip()
        header[key] = value
    records: list[dict[str, Any]] = []
    for row in ws.iter_rows(min_row=8, values_only=True):
        if not any(value not in (None, "") for value in row):
            continue
        records.append({
            "kind": str(row[0] or ""),
            "sheet": str(row[1] or ""),
            "field_keys": str(row[2] or ""),
            "row_or_header": int(row[3]) if row[3] not in (None, "") else 0,
            "value_column": int(row[4]) if row[4] not in (None, "") else 0,
            "basis": str(row[5] or ""),
        })
    return header, records


def _clean_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def _parse_table(ws, header_row: int) -> list[dict[str, Any]]:
    headers = [str(cell.value or "").strip() for cell in ws[header_row]]
    last_col = max((idx for idx, value in enumerate(headers, 1) if value), default=0)
    if not last_col:
        return []
    headers = headers[:last_col]
    rows: list[dict[str, Any]] = []
    blank_run = 0
    for row_no in range(header_row + 1, ws.max_row + 1):
        values = [_clean_value(ws.cell(row_no, col).value) for col in range(1, last_col + 1)]
        if not any(value not in (None, "") for value in values):
            blank_run += 1
            if blank_run >= 5:
                break
            continue
        blank_run = 0
        rows.append({header: value for header, value in zip(headers, values) if header})
    return rows


def _norm_compare(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).strip().lower()


def apply_integrated_authoring_workbook(
    project: Stage2Project,
    workbook_bytes: bytes,
    *,
    workbook_evidence: EvidenceRef | None = None,
) -> IntegratedImportResult:
    wb = load_workbook(BytesIO(workbook_bytes), data_only=False)
    meta, records = _meta_map(wb)
    if meta.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("지원하지 않는 통합 작성자료 버전입니다. 프로그램에서 최신 입력파일을 다시 내려받아 작성해 주세요.")
    if meta.get("workbook_mode") != MODE_INPUT:
        raise ValueError("작성예시 파일은 제출할 수 없습니다. '통합 작성자료.xlsx'에 실제 사업장 정보를 작성해 업로드해 주세요.")
    if meta.get("project_id") != project.project_id:
        raise ValueError("다른 작성 프로젝트에서 내려받은 통합 작성자료입니다. 현재 프로젝트의 파일을 다시 내려받아 주세요.")

    warnings: list[str] = []
    updated = 0
    table_fields = 0
    attachment_count = 0
    evidence = [workbook_evidence] if workbook_evidence is not None else []

    for item in records:
        sheet_name = item["sheet"]
        if sheet_name not in wb.sheetnames:
            warnings.append(f"시트 누락: {sheet_name}")
            continue
        ws = wb[sheet_name]
        kind = item["kind"]
        field_keys = [key for key in item["field_keys"].split("|") if key]
        if not field_keys:
            continue

        if kind == "PROTECTED":
            key = field_keys[0]
            current = project.get_field(key)
            cell_value = _clean_value(ws.cell(item["row_or_header"], item["value_column"]).value)
            if current and cell_value not in (None, "") and _norm_compare(cell_value) != _norm_compare(current.value):
                warnings.append(
                    f"{field_label(key)} 값이 Stage 1 판정자료와 다릅니다. 통합 작성자료에서 덮어쓰지 않았으며, 변경이 필요하면 판정진단을 다시 수행해 주세요."
                )
            continue

        if kind == "FORM":
            key = field_keys[0]
            value = _clean_value(ws.cell(item["row_or_header"], item["value_column"]).value)
            if value in (None, ""):
                continue
            project.set_field(
                key,
                field_label(key),
                value,
                "USER_CONFIRMED",
                evidence=evidence,
                note="통합 작성자료 Excel에서 회사가 직접 입력한 내용",
            )
            updated += 1
            continue

        if kind == "TABLE":
            rows = _parse_table(ws, item["row_or_header"])
            if not rows:
                continue
            for key in field_keys:
                if key in PROTECTED_STAGE1_FIELDS:
                    continue
                project.set_field(
                    key,
                    field_label(key),
                    rows,
                    "USER_CONFIRMED",
                    evidence=evidence,
                    note="통합 작성자료 Excel의 구조화 표에서 회사가 직접 입력한 내용",
                )
                updated += 1
                table_fields += 1
            continue

        if kind == "ATTACHMENT":
            key = field_keys[0]
            row_no = item["row_or_header"]
            file_name = str(ws.cell(row_no, 2).value or "").strip()
            if not file_name:
                continue
            value = {
                "file_name": file_name,
                "reference_no": str(ws.cell(row_no, 3).value or "").strip(),
                "revision": str(ws.cell(row_no, 4).value or "").strip(),
                "note": str(ws.cell(row_no, 5).value or "").strip(),
            }
            project.set_field(
                key,
                field_label(key),
                value,
                "HOLD",
                evidence=evidence,
                note="통합 작성자료에 파일명이 기재되었으나 실제 도면·첨부파일의 별도 업로드 및 내용 확인이 필요합니다.",
            )
            attachment_count += 1

    return IntegratedImportResult(
        updated_fields=updated,
        table_fields=table_fields,
        attachment_declarations=attachment_count,
        warnings=tuple(warnings),
    )


def declared_attachment_file_name(record_value: Any) -> str:
    if isinstance(record_value, Mapping):
        return str(record_value.get("file_name") or "").strip()
    if isinstance(record_value, str):
        return record_value.strip()
    return ""


def attach_company_file(project: Stage2Project, evidence: EvidenceRef) -> tuple[str, ...]:
    """Attach a separately uploaded drawing/document to fields that declared the same file name."""
    matched: list[str] = []
    target_name = Path(evidence.source_name).name.lower()
    for key, record in list(project.fields.items()):
        declared = Path(declared_attachment_file_name(record.value)).name.lower()
        if not declared or declared != target_name:
            continue
        refs = list(record.evidence)
        if not any(ref.sha256 == evidence.sha256 for ref in refs):
            refs.append(evidence)
        project.set_field(
            key,
            record.label,
            record.value,
            "HOLD",
            evidence=refs,
            note="통합 작성자료에 기재된 파일과 실제 첨부파일이 연결되었습니다. 내용 확인 전까지 사람 확인 필요 상태로 유지합니다.",
        )
        matched.append(key)
    if not matched:
        existing = project.get_field("attachments.unclassified")
        refs = list(existing.evidence) if existing else []
        refs.append(evidence)
        names = list(existing.value) if existing and isinstance(existing.value, list) else []
        names.append(evidence.source_name)
        project.set_field(
            "attachments.unclassified",
            "미분류 첨부자료",
            names,
            "HOLD",
            evidence=refs,
            note="통합 작성자료의 파일명과 자동 연결되지 않은 첨부자료입니다. 사람이 연결대상을 확인해야 합니다.",
        )
    return tuple(matched)
