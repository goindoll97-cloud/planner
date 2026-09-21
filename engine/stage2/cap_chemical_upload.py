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

SDS_CLASS_COLUMN = "SDS 제2항 유해성·위험성 분류(선택 입력)"
# 양식의 열. 법정 대상 판정에 필요한 값만 받는다(한 줄 = 한 CAS, 혼합물은 성분마다 한 줄).
OUT_COLUMNS = ("제품명", "혼합물 여부", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위", "성상", SDS_CLASS_COLUMN)
# 과거 회사 파일에 있던 값은 계속 읽어 보존한다.
EXTRA_COLUMNS = (
    "최대 동시보유량(ton)", "상온·상압 액체 여부(해당 시)", "최대보유량 법정 산정 여부",
)
ALL_COLUMNS = OUT_COLUMNS + EXTRA_COLUMNS
TON_EXTRAS = ("최대 제조·사용량", "최대 저장량")
STATE_COLUMN = "성상(상온·상압)"
STATE_OPTIONS = ("기체", "액체", "고체")
LIQUID_COLUMN = "상온·상압 액체 여부(해당 시)"
YES_NO_OPTIONS = ("Y", "N")
_STATE_WORDS = {"액체": "Y", "liquid": "Y", "기체": "N", "gas": "N", "고체": "N", "solid": "N"}
FIELD_ALIASES = {
    "제품명": ("제품명", "물질명", "화학물질명", "유해화학물질명", "품명", "제품", "화학명", "물질", "productname", "name"),
    "CAS No.": ("casno", "cas번호", "cas", "화학물질식별번호", "casnumber", "cas no."),
    "함량(%)": ("함량", "농도", "순도", "성분함량", "함유량", "content", "함량%"),
    "혼합물 여부": ("단일물질혼합물", "단일혼합", "혼합물여부", "혼합여부", "mixture", "mixtureyn"),
    "최대 동시보유량(ton)": ("최대동시보유량", "최대보유량", "보유량", "재고량"),
    "성상": ("성상", "상온상압성상", "물질상태", "상태"),
    "상온·상압 액체 여부(해당 시)": ("상온상압액체여부", "액체여부", "상온상압액체"),
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


def mixture_flag(text: object) -> str:
    """'단일물질'/'혼합물'(또는 Y/N)을 Y/N으로 바꾼다. 읽지 못하면 빈 값."""
    word = re.sub(r"\s", "", _clean(text)).lower()
    if word in {"혼합물", "혼합", "y", "yes", "예", "mixture"}:
        return "Y"
    if word in {"단일물질", "단일", "n", "no", "아니오", "single"}:
        return "N"
    return ""


def group_products(rows: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """한 줄이 한 CAS인 표를 제품 단위로 묶는다.

    제품명이 비어 있거나 바로 위 줄과 같으면 위 제품의 다음 성분이다. 혼합물은 제품 줄의 CAS·함량을 비우고 성분 목록을
    `_components`에 담는다. 수량·단위·성상·SDS 분류는 제품의 첫 줄(또는 처음 값이 있는 줄)에서 가져온다.
    """
    groups: list[list[Mapping[str, Any]]] = []
    last_name = ""
    for row in rows:
        name, cas = _clean(row.get("제품명")), _clean(row.get("CAS No."))
        if not name and not cas and not _clean(row.get("함량(%)")):
            continue
        if groups and (not name or _norm(name) == _norm(last_name)):
            groups[-1].append(row)
        else:
            groups.append([row])
            last_name = name
    products: list[dict[str, Any]] = []
    for group in groups:
        first = dict(group[0])
        name = _clean(first.get("제품명")) or _clean(first.get("CAS No."))
        flags = {mixture_flag(r.get("혼합물 여부")) for r in group} - {""}
        many = len([r for r in group if _clean(r.get("CAS No."))]) > 1
        notes = [n for n in _clean(first.get("메모")).split(" / ") if n]
        if many and "Y" not in flags:
            notes.append("CAS가 여러 개라 혼합물로 처리했습니다")
        is_mixture = "Y" in flags or many
        for column in ("최대 제조·사용량", "최대 저장량", "단위", "성상", SDS_CLASS_COLUMN, "상온·상압 액체 여부(해당 시)",
                       "최대 동시보유량(ton)", "최대보유량 법정 산정 여부"):
            if not _clean(first.get(column)):
                first[column] = next((_clean(r.get(column)) for r in group if _clean(r.get(column))), "")
        if not is_mixture:
            first.update({"제품명": name, "혼합물 여부": "N", "_components": []})
            if not _clean(first.get("함량(%)")):
                first["함량(%)"] = "100"
            first["메모"] = " / ".join(notes)
            products.append(first)
            continue
        components, problems, total = [], [], 0.0
        for row in group:
            cas = _clean(row.get("CAS No."))
            if not cas:
                continue
            content = _clean(row.get("함량(%)"))
            found = CAS_RE.findall(cas)
            if len(found) != 1 or not cas_valid("-".join(found[0])):
                problems.append(f"성분 CAS {cas}의 형식 또는 검산 숫자가 맞지 않습니다")
            if not content:
                problems.append(f"성분 {cas}의 함량(%)이 비어 있습니다")
            elif not re.fullmatch(r"\d+(?:\.\d+)?", content):
                problems.append(f"성분 {cas}의 함량(%)은 숫자만 적어야 합니다")
            else:
                total += float(content)
            components.append({"CAS No.": "-".join(found[0]) if len(found) == 1 else cas, "함량(%)": content})
        if not components:
            problems.append("혼합물의 성분 CAS를 한 줄에 하나씩 적어 주세요")
        if total > 100.5:
            problems.append(f"성분 함량의 합이 {total:g}%로 100%를 넘습니다")
        first.update({"제품명": name, "혼합물 여부": "Y", "CAS No.": "", "함량(%)": "", "_components": components,
                      "_component_problems": problems})
        first["메모"] = " / ".join([*notes, f"혼합물(성분 {len(components)}개)"])
        products.append(first)
    return products


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
        is_mixture = mixture_flag(row.get("혼합물 여부")) == "Y" and bool(row.get("_components") or row.get("_component_problems"))
        for problem in row.get("_component_problems") or []:
            errors += 1
            notes.append(problem)
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
        if not cas and not is_mixture:
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
        for column in (("최대 동시보유량(ton)", *TON_EXTRAS) if is_mixture else ("함량(%)", "최대 동시보유량(ton)", *TON_EXTRAS)):
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
            "제품명": name or cas, "혼합물 여부": mixture_flag(row.get("혼합물 여부")), "CAS No.": cas,
            "함량(%)": _clean(row.get("함량(%)")), "성상": _clean(row.get("성상")), SDS_CLASS_COLUMN: _clean(row.get(SDS_CLASS_COLUMN)),
            "_components": list(row.get("_components") or []), "_component_problems": list(row.get("_component_problems") or []),
            "최대 제조·사용량": _clean(row.get("최대 제조·사용량")),
            "최대 저장량": _clean(row.get("최대 저장량")),
            "단위": _clean(row.get("단위")) or "ton",
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
        quantities: dict[str, str] = {}
        for column in TON_EXTRAS:
            value, note = _to_ton(cell(column), cell("단위"), mapping.get(column, ""))
            quantities[column] = value
            if note:
                notes.append(f"{column}: {note}")

        extras: dict[str, str] = {}
        flag_text = cell("혼합물 여부")
        state_note = ""
        if cell("성상") and not cell(LIQUID_COLUMN):
            liquid = _STATE_WORDS.get(re.sub(r"[\s()]", "", cell("성상")).lower(), "")
            if not liquid:
                state_note = f"성상 '{cell('성상')}'을 기체·액체·고체 중에서 읽지 못했습니다"
        else:
            liquid = ""
        for column in EXTRA_COLUMNS:
            if column == "최대 동시보유량(ton)":
                extras[column] = amount
            elif column == LIQUID_COLUMN and liquid:
                extras[column] = liquid  # 성상 선택에서 액체 여부를 프로그램이 정한다(액체 Y, 기체·고체 N)
            else:
                extras[column] = cell(column)
        if state_note:
            notes.append(state_note)
        # 업로드 단계에서 kg/ton을 ton으로 환산했으므로 이후 엔진에는 ton이라고 명시한다.
        normalized_unit = "ton" if any(quantities.values()) or amount else (cell("단위") or "")
        if flag_text and not mixture_flag(flag_text):
            notes.append(f"단일물질/혼합물 '{flag_text}'을 읽지 못했습니다(단일물질·혼합물 중에서 고르세요)")
        rows.append({"제품명": cell("제품명"), "혼합물 여부": mixture_flag(flag_text), "CAS No.": cell("CAS No."),
                     "함량(%)": content,
                     "최대 제조·사용량": quantities.get("최대 제조·사용량", ""),
                     "최대 저장량": quantities.get("최대 저장량", ""),
                     "단위": normalized_unit, "성상": cell("성상"), SDS_CLASS_COLUMN: cell(SDS_CLASS_COLUMN),
                     **extras,
                     "메모": " / ".join(notes)})
    return rows


def blank_template() -> bytes:
    """법정 대상 판정에 필요한 값만 받는 양식. 한 줄이 한 CAS이고, 혼합물은 성분마다 한 줄씩 적는다."""
    from openpyxl import Workbook
    from openpyxl.worksheet.datavalidation import DataValidation

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "물질 목록"
    headers = ["제품명", "단일물질/혼합물", "CAS No.", "함량(%)", "최대 제조·사용량", "최대 저장량", "단위", "성상(상온·상압)",
               "SDS 제2항 분류(선택)"]
    sheet.append(headers)
    for column, width in zip("ABCDEFGHI", (26, 16, 16, 12, 20, 16, 10, 16, 30)):
        sheet.column_dimensions[column].width = width

    def dropdown(values: str, cells: str, title: str, prompt: str) -> None:
        validation = DataValidation(type="list", formula1=f'"{values}"', allow_blank=True, showErrorMessage=True,
                                    errorTitle=f"{title}을 선택하세요", error=f"{values} 중에서 고르세요.",
                                    showInputMessage=True, promptTitle=title, prompt=prompt)
        sheet.add_data_validation(validation)
        validation.add(cells)

    dropdown("단일물질,혼합물", "B2:B1000", "단일물질/혼합물", "혼합제품이면 '혼합물'을 고르고 성분마다 한 줄씩 적으세요.")
    dropdown("kg,ton", "G2:G1000", "수량 단위", "최대 제조·사용량과 최대 저장량에 공통으로 적용할 단위입니다.")
    dropdown("기체,액체,고체", "H2:H1000", "성상", "상온·상압(20℃, 1기압)에서의 상태입니다.")

    guide = workbook.create_sheet("작성 안내")
    for line in (
        ["법정 대상 판정에 필요한 값만 적는 양식입니다. 한 줄이 한 CAS 번호입니다."],
        ["■ 단일물질: 한 줄에 적습니다. 단일물질/혼합물에 '단일물질', CAS No., 수량을 적습니다(함량은 비워 두면 100%)."],
        ["■ 혼합물: 성분마다 한 줄씩 적습니다. 첫 줄에 제품명, '혼합물', 수량, 첫 성분의 CAS No.와 함량(%)을 적고, "
         "다음 줄부터는 제품명을 비우고 성분의 CAS No.와 함량(%)만 적습니다. 성분은 제품 SDS 제3항에서 옮깁니다."],
        ["제품명: 사내에서 쓰는 이름입니다(표시용). 법적 판정은 CAS No.로 합니다."],
        ["CAS No.: 단일물질이면 그 물질, 혼합물이면 각 성분의 CAS 번호입니다. 혼합제품 자체의 CAS는 적지 않습니다."],
        ["함량(%): 혼합물 성분의 함량입니다. 범위는 상한값으로 적고 성분 함량의 합은 100%를 넘지 않게 합니다."],
        ["최대 제조·사용량 / 최대 저장량: 제품 단위로 첫 줄에만 적습니다. 모르면 비우고, 하지 않으면 0을 적습니다(빈 칸은 '아직 모름')."],
        ["단위: kg 또는 ton(두 수량에 공통). 프로그램이 ton으로 바꿔 저장합니다."],
        ["성상: 상온·상압에서 기체·액체·고체 중 하나입니다. 제품 첫 줄에 적으면 됩니다."],
        ["SDS 제2항 분류(선택): 비워도 됩니다. 비우면 판정 화면에서 KOSHA 후보를 불러올 수 있습니다."],
        ["(예시) 단일물질 — 톨루엔 / 단일물질 / 108-88-3 / (함량 비움) / 3000 / 12500 / kg / 액체"],
        ["(예시) 혼합물 — 첫 줄: 세척제A / 혼합물 / 67-64-1 / 60 / 500 / 2000 / kg / 액체  →  다음 줄: (제품명 비움) / (구분 비움) / 108-88-3 / 30"],
        ["판정 질문(개별 주요취급시설·예외 해당 여부 등 사업장 전체에 대한 것)은 화면에서 몇 가지만 묻습니다."],
    ):
        guide.append(line)
    guide.column_dimensions["A"].width = 130
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


def _save_components(project: Stage2Project, products: list[Mapping[str, Any]], first_position: int, file_name: str) -> None:
    """혼합물 성분을 프로젝트에 저장한다. 제품목록행번호는 화학물질 목록에서의 위치(1부터)다."""
    from .cap_judgement import MIXTURE_COMPONENTS_KEY, mixture_components

    added = []
    for offset, product in enumerate(products):
        for component in product.get("_components") or []:
            added.append({
                "적용여부": "Y", "제품목록행번호": first_position + offset, "제품명(확인용)": _clean(product.get("제품명")),
                "구성성분명": "", "CAS No.": _clean(component.get("CAS No.")), "함량(%)": _clean(component.get("함량(%)")),
                "SDS 제3항 근거": f"회사 입력 파일({file_name}) — 제품 SDS 제3항과 대조 확인",
            })
    if added:
        project.set_field(MIXTURE_COMPONENTS_KEY, "혼합물 구성성분", [*mixture_components(project), *added], "USER_CONFIRMED")


def add_to_project(project: Stage2Project, rows: list[Mapping[str, Any]], *, file_name: str, sha256: str,
                   evidence: EvidenceRef | None = None, sds_confirmed: bool = False) -> tuple[int, int]:
    """검사를 통과한 행만 화학물질 목록에 추가한다. (추가한 수, 건너뛴 수)

    혼합물의 성분은 함께 저장한다. 성분의 CAS·함량을 제품 SDS 제3항과 대조했다는 확인(sds_confirmed)이 없으면 혼합물은 추가하지 않는다.
    """
    from . import cap_chemical_workspace as chem

    cas_have, names_have = _existing(project)
    checked = check_rows(rows, cas_have, names_have)
    good = [r for r in checked.rows if r["_ok"]]
    if not sds_confirmed and any(r.get("_components") for r in good):
        raise ValueError("혼합물의 성분 CAS·함량을 제품 SDS 제3항과 대조해 확인한 뒤에 추가할 수 있습니다.")
    skipped = len(checked.rows) - len(good)
    if not good:
        return 0, skipped
    new_rows = to_inventory_rows(good)
    first_position = len(chem._rows(project)[1]) + 1
    _save_components(project, good, first_position, file_name)
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
