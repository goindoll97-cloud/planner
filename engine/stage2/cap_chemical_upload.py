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
# 신규 기본 물질목록은 제품 단위로 한 줄씩만 받는다.
# 혼합제품의 구성성분 CAS·함량은 별도 '혼합물 구성성분' 파일에서 받는다.
OUT_COLUMNS = ("제품명", "혼합물 여부", "CAS No.", "최대 제조·사용량", "최대 저장량", "단위")
# 과거 회사 파일의 세부 열은 계속 읽어 보존한다. 새 빈 양식에는 노출하지 않는다.
EXTRA_COLUMNS = (
    "함량(%)", "성상", SDS_CLASS_COLUMN, "최대 동시보유량(ton)",
    "상온·상압 액체 여부(해당 시)", "최대보유량 법정 산정 여부",
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
    """제품 단위로 정리한다.

    신규 양식은 한 행이 한 제품이다. 혼합제품의 구성성분은 두 번째 파일에서 받는다.
    과거 한-시트 양식은 하위호환을 위해 읽되, 제품명이 빈 행은 바로 앞 행이 명시적으로
    '혼합물'인 경우에만 구성성분으로 연결한다. 단일물질 뒤의 빈 제품명 행을 혼합물로
    자동 추정하지 않는다.
    """
    products: list[dict[str, Any]] = []
    current_mixture: dict[str, Any] | None = None

    for raw in rows:
        row = dict(raw)
        name = _clean(row.get("제품명"))
        cas = _clean(row.get("CAS No."))
        pct = _clean(row.get("함량(%)"))
        if not name and not cas and not pct:
            continue

        flag = mixture_flag(row.get("혼합물 여부"))

        # 과거 양식의 후속 성분 행: 앞 제품이 명시적으로 혼합물일 때만 허용한다.
        if not name:
            if current_mixture is None:
                orphan = dict(row)
                orphan["제품명"] = cas or "(제품명 누락)"
                orphan["혼합물 여부"] = ""
                orphan["_components"] = []
                orphan["_component_problems"] = [
                    "제품명이 비어 있습니다. 새 기본 물질목록에서는 모든 제품을 한 줄씩 적어 주세요. "
                    "혼합물 성분은 별도 '혼합물 구성성분' 파일에 적습니다."
                ]
                products.append(orphan)
                continue
            current_mixture.setdefault("_legacy_component_rows", []).append(row)
            continue

        product = dict(row)
        product["제품명"] = name
        product["_components"] = []
        product["_component_problems"] = []
        current_mixture = product if flag == "Y" else None
        products.append(product)

    # 구형 한-시트 혼합물 양식의 성분 행도 안전하게 보존한다.
    for product in products:
        product_flag = mixture_flag(product.get("혼합물 여부"))
        if product_flag != "Y":
            # 새 양식에서 명시적으로 단일물질이라고 한 경우만 100%로 처리한다.
            # 구형 파일처럼 구분이 비어 있으면 추정하지 않고 판정 단계에서 확인한다.
            if product_flag == "N" and not _clean(product.get("함량(%)")):
                product["함량(%)"] = "100"
            continue

        legacy = list(product.pop("_legacy_component_rows", []) or [])
        # 구형 양식은 혼합물 첫 행 자체에 첫 성분 CAS/함량을 넣을 수 있었다.
        if _clean(product.get("CAS No.")) or _clean(product.get("함량(%)")):
            legacy.insert(0, dict(product))

        components: list[dict[str, str]] = []
        problems: list[str] = list(product.get("_component_problems") or [])
        total = 0.0
        for part in legacy:
            part_cas = _clean(part.get("CAS No."))
            part_pct = _clean(part.get("함량(%)"))
            if not part_cas and not part_pct:
                continue
            if not cas_valid(part_cas):
                problems.append(f"성분 CAS {part_cas or '(빈칸)'}의 형식 또는 검산 숫자가 맞지 않습니다")
            if not re.fullmatch(r"\d+(?:\.\d+)?", part_pct):
                problems.append(f"성분 {part_cas or '(CAS 미입력)'}의 함량(%)은 숫자로 적어야 합니다")
            else:
                total += float(part_pct)
            components.append({"CAS No.": part_cas, "함량(%)": part_pct})

        if total > 100.5:
            problems.append(f"성분 함량의 합이 {total:g}%로 100%를 넘습니다")
        elif components and total < 99.5:
            notes = [n for n in _clean(product.get("메모")).split(" / ") if n]
            notes.append(
                f"적은 성분의 함량 합이 {total:g}%입니다. 나머지 {100 - total:g}%에 규제 대상 물질이 없는지 제품 SDS 제3항으로 확인하세요"
            )
            product["메모"] = " / ".join(notes)

        product["CAS No."] = ""
        product["함량(%)"] = ""
        product["_components"] = components
        product["_component_problems"] = problems

    return products


# 자동으로 처리한 내용을 알려 주는 메모. 확인할 문제가 아니므로 ⚠️로 세지 않는다.
_INFO_NOTE = re.compile(r"를 톤으로 바꿈|^혼합물\(성분 \d+개\)|상한값을 사용|비율로 보고 %로 바꿈|혼합물로 처리했습니다|^비고:")


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
        flag = mixture_flag(row.get("혼합물 여부"))
        is_mixture = flag == "Y"
        if not flag:
            warnings += 1
            notes.append("단일물질/혼합물 구분이 없습니다. 구형 파일로 보고 추가하며, 판정 전에 다시 확인합니다.")
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
            errors += 1
            notes.append("단일물질은 CAS No.가 반드시 필요합니다. 물질명으로 추정하지 않습니다.")
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
            if not extra:
                continue
            notes.append(extra)
            if not _INFO_NOTE.search(extra):
                warnings += 1  # 단위 환산 같은 단순 안내가 아니라 사용자가 확인해야 하는 메모
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
            "확인": ("❌ " if errors else "⚠️ " if warnings else "✅ ") + ("; ".join(dict.fromkeys(notes)) or "이상 없음"),
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
            # 아래 세 열은 rows.append에서 정규화된 값을 직접 넣으므로 여기서 덮어쓰지 않는다.
            if column in {"함량(%)", "성상", SDS_CLASS_COLUMN}:
                continue
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
    """신입사원용 기본 물질목록. 한 행이 한 제품이며 혼합물 성분은 두 번째 파일에서 받는다."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "물질 목록"
    headers = ["제품명", "단일물질/혼합물", "CAS No.", "최대 제조·사용량", "최대 저장량", "단위"]
    sheet.append(headers)
    for column, width in zip("ABCDEF", (28, 18, 18, 22, 18, 10)):
        sheet.column_dimensions[column].width = width
    for cell in sheet[1]:
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.font = Font(color="FFFFFF", bold=True)

    def dropdown(values: str, cells: str, title: str, prompt: str) -> None:
        validation = DataValidation(
            type="list", formula1=f'"{values}"', allow_blank=False, showErrorMessage=True,
            errorTitle=f"{title}을 선택하세요", error=f"{values} 중에서 고르세요.",
            showInputMessage=True, promptTitle=title, prompt=prompt,
        )
        sheet.add_data_validation(validation)
        validation.add(cells)

    dropdown(
        "단일물질,혼합물", "B2:B1000", "단일물질/혼합물",
        "제품 SDS 제3항을 확인하세요. 구성성분이 하나인 물질은 단일물질, 여러 성분으로 된 제품은 혼합물입니다.",
    )
    dropdown("kg,ton", "F2:F1000", "수량 단위", "제조·사용량과 저장량에 공통으로 적용할 단위입니다.")

    guide = workbook.create_sheet("작성 안내")
    lines = (
        ["처음에는 이 파일 하나만 작성합니다. 한 줄에 제품 하나씩 적으세요."],
        ["필수: 제품명, 단일물질/혼합물, 최대 제조·사용량 또는 최대 저장량, 단위"],
        ["단일물질: CAS No.를 반드시 적습니다. 함량은 프로그램이 100%로 처리합니다."],
        ["혼합물: 제품 자체 CAS No.는 비워 둡니다. 혼합물이 확인되면 프로그램이 두 번째 '혼합물 구성성분' 파일을 제공합니다."],
        ["두 번째 파일에는 제품 SDS 제3항을 보고 구성성분별 CAS No.와 함량(%)만 적습니다."],
        ["최대 제조·사용량: 하루에 가장 많이 제조하거나 사용하는 양입니다. 하지 않으면 0, 모르면 비워 둡니다."],
        ["최대 저장량: 한 시점에 가장 많이 저장하는 양입니다. 저장하지 않으면 0, 모르면 비워 둡니다."],
        ["성상, SDS 제2항 분류, 법정 면제·제외 조건 등 어려운 값은 처음부터 요구하지 않습니다. 실제 판정에 필요할 때 화면 질문으로만 묻습니다."],
        ["(예시) 톨루엔 / 단일물질 / 108-88-3 / 3000 / 5000 / kg"],
        ["(예시) 반응기 세정제 A / 혼합물 / (CAS 비움) / 2 / 4 / ton"],
    )
    for line in lines:
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
