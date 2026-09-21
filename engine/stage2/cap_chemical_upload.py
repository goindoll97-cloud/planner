from __future__ import annotations

"""회사가 이미 가지고 있는 물질 목록(엑셀·CSV)을 읽어 화학물질 목록으로 옮긴다.

- 열 이름이 달라도(제품명/물질명/품명, CAS No./CAS번호 …) 알아서 맞추고, 사용자가 바로잡을 수 있다.
- CAS 번호는 형식과 검산 숫자를 검사한다. 함량 범위("95~99")는 상한값을 쓰고 표시한다. 보유량은 톤으로 바꾼다(L는 비중이 필요해 바꾸지 못함).
- 이미 있는 물질은 덮어쓰지 않고 건너뛴다. 올린 파일은 SHA-256과 함께 기록한다.
"""

from dataclasses import dataclass, field
from io import BytesIO
import hashlib
import re
from typing import Any, Mapping

import pandas as pd

from .project import EvidenceRef, Stage2Project

OUT_COLUMNS = ("제품명", "CAS No.", "함량(%)", "최대 동시보유량(ton)")
# 판정 엔진이 물질마다 필요로 하는 선택 입력 열. 양식에 함께 적으면 판정 때 다시 묻지 않는다.
EXTRA_COLUMNS = (
    "상온·상압 액체 여부(해당 시)", "최대 제조·사용량", "최대 저장량", "최대보유량 법정 산정 여부",
    "SDS 제2항 유해성·위험성 분류(선택 입력)",
)
ALL_COLUMNS = OUT_COLUMNS + EXTRA_COLUMNS
TON_EXTRAS = ("최대 제조·사용량", "최대 저장량")
FIELD_ALIASES = {
    "제품명": ("제품명", "물질명", "화학물질명", "유해화학물질명", "품명", "제품", "화학명", "물질", "productname", "name"),
    "CAS No.": ("casno", "cas번호", "cas", "화학물질식별번호", "casnumber", "cas no."),
    "함량(%)": ("함량", "농도", "순도", "성분함량", "함유량", "content", "함량%"),
    "최대 동시보유량(ton)": ("최대동시보유량", "최대보유량", "최대저장량", "보유량", "저장량", "취급량", "최대취급량", "재고량"),
    "상온·상압 액체 여부(해당 시)": ("상온상압액체여부", "액체여부", "상온상압액체", "성상"),
    "최대 제조·사용량": ("최대제조사용량", "제조사용량", "최대제조량", "최대사용량", "하루최대제조사용량"),
    "최대 저장량": ("최대저장량", "저장최대량"),
    "최대보유량 법정 산정 여부": ("최대보유량법정산정여부", "법정산정여부", "법정산정"),
    "SDS 제2항 유해성·위험성 분류(선택 입력)": ("sds제2항유해성위험성분류", "sds제2항분류", "sds분류", "유해성위험성분류", "ghs분류"),
    "단위": ("단위", "수량단위", "unit"),
    "비고": ("비고", "메모", "remark", "note"),
}
TON_FACTORS = {"ton": 1.0, "t": 1.0, "톤": 1.0, "kg": 0.001, "㎏": 0.001, "g": 1e-6, "그램": 1e-6}
CAS_RE = re.compile(r"\b(\d{2,7})-(\d{2})-(\d)\b")


@dataclass(frozen=True)
class Parsed:
    frame: pd.DataFrame
    sha256: str
    file_name: str
    header_row: int
    mapping: dict[str, str]  # 내 열 -> 파일의 열 이름


@dataclass
class Checked:
    rows: list[dict[str, Any]] = field(default_factory=list)  # 정리된 행(입력 표 열 + '확인')
    errors: int = 0
    warnings: int = 0


def _norm(value: object) -> str:
    text = re.sub(r"\([^)]*\)|（[^）]*）", "", str(value or ""))
    return re.sub(r"[\s_./·\-]", "", text).lower()


def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def cas_valid(cas: str) -> bool:
    """형식(2~7자리-2자리-1자리)과 검산 숫자를 검사한다."""
    found = CAS_RE.fullmatch(cas.strip())
    if not found:
        return False
    digits = (found.group(1) + found.group(2))[::-1]
    return sum(int(d) * (i + 1) for i, d in enumerate(digits)) % 10 == int(found.group(3))


def _read(data: bytes, file_name: str) -> pd.DataFrame:
    if file_name.lower().endswith((".xlsx", ".xlsm")):
        return pd.read_excel(BytesIO(data), header=None, dtype=object, engine="openpyxl")
    if file_name.lower().endswith(".xls"):
        raise ValueError(".xls(구형 엑셀)는 읽지 못합니다. 엑셀에서 .xlsx 또는 CSV로 저장해 올려 주세요.")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(BytesIO(data), header=None, dtype=object, encoding=encoding, sep=None, engine="python")
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise ValueError("파일을 읽지 못했습니다. 엑셀(.xlsx) 또는 CSV(UTF-8·CP949) 파일인지 확인해 주세요.")


def _find_header(frame: pd.DataFrame) -> int:
    known = {_norm(a) for aliases in FIELD_ALIASES.values() for a in aliases}
    for index in range(min(len(frame), 15)):
        hits = sum(1 for cell in frame.iloc[index] if _norm(cell) in known)
        if hits >= 2:
            return index
    return 0


def guess_mapping(columns: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used: set[str] = set()
    for target, aliases in FIELD_ALIASES.items():
        wanted = [_norm(a) for a in aliases]
        # 표준 열 이름과 똑같은 열이 있으면 순서와 상관없이 그 열을 먼저 쓴다(예: 최대 저장량 열이 앞에 있어도 최대 동시보유량은 제자리를 찾는다).
        exact = next((c for c in columns if c not in used and _norm(c) == wanted[0]), None)
        if exact is not None:
            mapping[target] = exact
            used.add(exact)
            continue
        for column in columns:
            if column in used:
                continue
            name = _norm(column)
            if target == "최대 동시보유량(ton)" and "연간" in str(column):
                continue  # 연간 사용량은 최대 동시보유량이 아니다
            if name in wanted or any(name.startswith(w) and len(w) >= 3 for w in wanted):
                mapping[target] = column
                used.add(column)
                break
    return mapping


def parse(data: bytes, file_name: str) -> Parsed:
    if not data:
        raise ValueError("빈 파일입니다.")
    raw = _read(data, file_name)
    raw = raw.dropna(how="all").reset_index(drop=True)
    if raw.empty:
        raise ValueError("읽을 내용이 없습니다.")
    header = _find_header(raw)
    columns = [_clean(c) or f"열{i + 1}" for i, c in enumerate(raw.iloc[header])]
    body = raw.iloc[header + 1:].reset_index(drop=True)
    body.columns = columns
    body = body.dropna(how="all")
    return Parsed(body.reset_index(drop=True), hashlib.sha256(data).hexdigest(), file_name, header, guess_mapping(columns))


def _to_ton(text: str, unit: str, header: str) -> tuple[str, str]:
    """(톤 값, 메모). 톤으로 바꾸지 못하면 빈 값과 이유."""
    if not text:
        return "", ""
    number = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    if not number:
        return "", "보유량에서 숫자를 읽지 못했습니다"
    value = float(number)
    label = _norm(unit) or (re.search(r"\(([^)]*)\)", header) or [None, ""])[1].strip().lower()
    label = re.sub(r"[\s.]", "", label).lower()
    if not label:
        return "", "보유량 단위(ton·kg)를 알 수 없어 비워 두었습니다"
    if label in ("l", "리터", "ℓ", "m3", "㎥"):
        return "", f"{label} 단위는 비중이 있어야 톤으로 바꿀 수 있습니다(별지 제1호에서 계산)"
    factor = TON_FACTORS.get(label)
    if factor is None:
        return "", f"'{label}' 단위를 알 수 없어 비워 두었습니다"
    return f"{value * factor:g}", "" if factor == 1.0 else f"{label}를 톤으로 바꿈"


def _content(text: str) -> tuple[str, str]:
    """(퍼센트 숫자 문자열, 메모). 범위는 상한값을 쓴다."""
    if not text:
        return "", "함량이 비어 있습니다(100%로 가정하지 않음)"
    numbers = re.findall(r"\d+(?:\.\d+)?", text.replace(",", ""))
    if not numbers:
        return "", "함량에서 숫자를 읽지 못했습니다"
    values = [float(n) for n in numbers]
    if len(values) >= 2 and re.search(r"[~\-–]", text):
        return f"{max(values):g}", f"범위({text.strip()})의 상한값을 사용"
    value = values[0]
    if value <= 1.0 and "%" not in text and "." in text:
        return f"{value * 100:g}", "0~1 비율로 보고 %로 바꿈"
    return f"{value:g}", ""


def check_rows(rows: list[Mapping[str, Any]], existing_cas: set[str] | None = None,
               existing_names: set[str] | None = None) -> Checked:
    """입력 표의 행을 검사한다. 오류가 있는 행은 추가되지 않고, 경고는 표시만 한다."""
    existing_cas = existing_cas or set()
    existing_names = existing_names or set()
    checked = Checked()
    seen: set[str] = set()
    for row in rows:
        name, cas = _clean(row.get("제품명")), _clean(row.get("CAS No."))
        if not name and not cas:
            continue
        notes: list[str] = []
        errors = warnings = 0
        cas_list = CAS_RE.findall(cas)
        if cas and not cas_list:
            errors += 1
            notes.append("CAS 번호 형식이 아닙니다")
        elif len(cas_list) > 1:
            warnings += 1
            notes.append("CAS가 여러 개(혼합물)입니다. 성분별 확인이 필요합니다")
        for part in cas_list:
            joined = "-".join(part)
            if not cas_valid(joined):
                errors += 1
                notes.append(f"CAS {joined}의 검산 숫자가 맞지 않습니다(오타 확인)")
        if not name:
            warnings += 1
            notes.append("이름이 없어 CAS로 대신 표시합니다")
        if not cas:
            warnings += 1
            notes.append("CAS 번호가 없습니다(물질 식별이 어렵습니다)")
        key = cas or _norm(name)
        if key in seen:
            errors += 1
            notes.append("파일 안에서 같은 물질이 중복되었습니다")
        elif any("-".join(p) in existing_cas for p in cas_list) or (not cas and _norm(name) in existing_names):
            errors += 1
            notes.append("이미 목록에 있는 물질입니다(건너뜀)")
        seen.add(key)
        for column in ("함량(%)", "최대 동시보유량(ton)", *TON_EXTRAS):
            text = _clean(row.get(column))
            if text and not re.fullmatch(r"\d+(?:\.\d+)?", text):
                errors += 1
                notes.append(f"{column}은 숫자만 적어야 합니다")
        for extra in _clean(row.get("메모")).split(" / "):
            if extra:
                notes.append(extra)
        checked.errors += 1 if errors else 0
        checked.warnings += 1 if warnings and not errors else 0
        checked.rows.append({
            "제품명": name or cas, "CAS No.": cas, "함량(%)": _clean(row.get("함량(%)")),
            "최대 동시보유량(ton)": _clean(row.get("최대 동시보유량(ton)")),
            **{column: _clean(row.get(column)) for column in EXTRA_COLUMNS},
            "확인": ("❌ " if errors else "⚠️ " if warnings or notes else "✅ ") + ("; ".join(dict.fromkeys(notes)) or "이상 없음"),
            "_ok": not errors,
        })
    return checked


def normalize(parsed: Parsed, mapping: Mapping[str, str]) -> list[dict[str, str]]:
    """파일의 열을 입력 표의 열로 옮긴다(단위 변환·함량 정리 포함). 검사는 check_rows가 한다."""
    frame = parsed.frame
    rows = []
    for _, record in frame.iterrows():
        def cell(target: str) -> str:
            column = mapping.get(target)
            return _clean(record.get(column)) if column else ""

        content, content_note = _content(cell("함량(%)")) if mapping.get("함량(%)") else ("", "")
        amount_header = mapping.get("최대 동시보유량(ton)", "")
        amount, amount_note = _to_ton(cell("최대 동시보유량(ton)"), cell("단위"), amount_header)
        notes = [n for n in (content_note if mapping.get("함량(%)") else "", amount_note) if n]
        if cell("비고"):
            notes.append(f"비고: {cell('비고')}")
        extras: dict[str, str] = {}
        for column in EXTRA_COLUMNS:
            if column in TON_EXTRAS:
                value, note = _to_ton(cell(column), "", mapping.get(column, ""))
                extras[column] = value
                if note:
                    notes.append(f"{column}: {note}")
            else:
                extras[column] = cell(column)
        rows.append({"제품명": cell("제품명"), "CAS No.": cell("CAS No."), "함량(%)": content,
                     "최대 동시보유량(ton)": amount, **extras, "메모": " / ".join(notes)})
    return rows


def blank_template() -> bytes:
    """빈 양식(엑셀). 예시는 안내 시트에만 '(예시)'로 적는다."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "물질 목록"
    sheet.append(["제품명", "CAS No.", "함량(%)", "최대 동시보유량(ton)", "상온·상압 액체 여부(해당 시)",
                  "최대 제조·사용량(ton)", "최대 저장량(ton)", "최대보유량 법정 산정 여부",
                  "SDS 제2항 유해성·위험성 분류(선택 입력)"])
    for column, width in zip("ABCDEFGHI", (28, 16, 12, 22, 22, 20, 18, 22, 44)):
        sheet.column_dimensions[column].width = width
    guide = workbook.create_sheet("작성 안내")
    for line in (
        ["취급하는 유해화학물질을 한 줄에 하나씩 적습니다. 모르는 칸은 비워 두어도 됩니다."],
        ["제품명: 제품 또는 물질 이름 / CAS No.: 화학물질 고유 번호 / 함량(%): 제품 안 그 물질의 비율(숫자만)"],
        ["최대 동시보유량: 한꺼번에 가장 많이 보유하는 양. 열 이름에 단위를 적으세요: (ton) 또는 (kg)"],
        ["상온·상압 액체 여부: 상온·상압에서 액체이면 Y, 아니면 N (해당하는 물질만)"],
        ["최대 제조·사용량 / 최대 저장량: 하루 최대 제조·사용량과 한꺼번에 저장하는 최대량. 열 이름에 단위를 적으세요: (ton) 또는 (kg)"],
        ["최대보유량 법정 산정 여부: 위 최대 동시보유량을 법정 산정 방식으로 계산한 값이면 Y, 단순 재고량이나 추정이면 N"],
        ["SDS 제2항 분류: 제품 SDS 제2항의 유해성·위험성 분류를 그대로 적습니다. 해당 분류가 없으면 '별표1 해당없음'"],
        ["위 다섯 칸은 판정 규칙이 요구할 때만 필요합니다. 모르면 비워 두면, 판정 화면에서 필요한 물질만 다시 묻습니다."],
        ["CAS가 여러 개인 혼합물은 성분마다 한 줄씩 적는 것을 권합니다."],
        ["(예시) 제품명 톨루엔 / CAS No. 108-88-3 / 함량(%) 99.5 / 최대 동시보유량(ton) 12.5"],
    ):
        guide.append(line)
    guide.column_dimensions["A"].width = 100
    out = BytesIO()
    workbook.save(out)
    return out.getvalue()


def _existing(project: Stage2Project) -> tuple[set[str], set[str]]:
    from .cap_chemical_workspace import _rows

    _, rows = _rows(project)
    cas: set[str] = set()
    names: set[str] = set()
    for row in rows:
        cas.update("-".join(p) for p in CAS_RE.findall(_clean(row.get("CAS No.") or row.get("CAS 번호") or row.get("CAS"))))
        names.add(_norm(row.get("물질명") or row.get("제품명") or row.get("유해화학물질명")))
    return cas, names


def existing_keys(project: Stage2Project) -> tuple[set[str], set[str]]:
    return _existing(project)


def to_inventory_rows(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """시작하기와 같은 형식의 화학물질 목록 행(inventory.chemicals)으로 바꾼다."""
    from .cap_start import chemical_frame

    frame = chemical_frame(list(rows))
    records = frame.astype(object).where(frame.notna(), None).to_dict("records")
    for record in records:
        record["물질명"] = record.get("물질명(알면 입력)") or record.get("제품명")
    return records


def add_to_project(project: Stage2Project, rows: list[Mapping[str, Any]], *, file_name: str, sha256: str,
                   evidence: EvidenceRef | None = None) -> tuple[int, int]:
    """검사를 통과한 행만 화학물질 목록에 추가한다. (추가한 수, 건너뛴 수)"""
    from . import cap_chemical_workspace as chem

    cas_have, names_have = _existing(project)
    checked = check_rows(rows, cas_have, names_have)
    good = [r for r in checked.rows if r["_ok"]]
    skipped = len(checked.rows) - len(good)
    if not good:
        return 0, skipped
    new_rows = to_inventory_rows(good)
    keys = [chem.INVENTORY_KEY]
    canonical, _ = chem._rows(project)
    if canonical == chem.DETAILS_KEY:
        keys.append(chem.DETAILS_KEY)
    for key in keys:
        record = project.get_field(key)
        current = [dict(r) for r in record.value] if record is not None and isinstance(record.value, list) else []
        refs = list(record.evidence) if record is not None else []
        if evidence is not None:
            refs.append(evidence)
        label = record.label if record is not None else "화학물질 목록"
        project.set_field(key, label, [*current, *new_rows], "USER_CONFIRMED", evidence=refs,
                          note=f"엑셀·CSV 업로드로 물질 {len(new_rows)}건 추가({file_name}, SHA-256 {sha256[:12]})")
    project.notes.append(f"물질 목록 업로드: {file_name} (SHA-256 {sha256[:12]}…) {len(new_rows)}건 추가, {skipped}건 제외")
    return len(new_rows), skipped
