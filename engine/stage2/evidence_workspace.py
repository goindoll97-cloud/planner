"""회사 자료를 사업장 공통 사실로 바꾸고, 사람이 볼 예외만 남깁니다.

흐름: 자료 읽기 → 사실 후보(출처 포함) → 규칙으로 자동 기입 → 예외(충돌·오류·낮은 신뢰)만 사람에게.

자동 기입 경계는 두 가지로 정합니다.
1. 값이 유효하고 모호하지 않은가 (충돌·단위·범위·CAS 검산·추출 경로).
2. 값이 결과에 미치는 영향이 큰가. 법적 판단에 쓰이는 항목이나 예비 순위를 바꾸는 핵심값은
   더 높은 출처 신뢰도를 요구하고, 자동 기입했더라도 먼저 확인할 목록에 올립니다.
"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO, StringIO
import csv
import json
import math
import re
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile
from xml.etree import ElementTree

from .project import Stage2Project

KEY = "workspace.evidence_graph"
LABELS = {"name": "명칭", "product": "취급제품", "cas": "CAS 번호", "capacity": "용량(m³)",
          "pressure": "운전압력(MPa)", "design_pressure": "설계압력(MPa)", "temperature": "운전온도(°C)",
          "inventory": "최대보유량(kg)", "concentration": "함량(%)",
          "facility_type": "시설유형", "substance_state": "물질성상",
          "density": "비중(kg/L)", "process_type": "공정유형"}
# 별지 제1호 계산이 받는 값과 같아야 합니다(tests/test_evidence_workspace.py가 cap_workspace와 일치를 검사).
CHOICES = {"facility_type": ("저장탱크", "제조·사용시설", "보관시설", "기타", "탱크로리·운송차량", "사외배관", "취급중단 신고시설"),
           "substance_state": ("액체", "고체", "기체·고압가스", "복수성상"),
           "process_type": ("변화없음", "단순혼합", "반응")}
CHOICE_SYNONYMS = {"기체": "기체·고압가스", "고압가스": "기체·고압가스", "기체/고압가스": "기체·고압가스", "기체고압가스": "기체·고압가스",
                   "탱크로리": "탱크로리·운송차량", "운송차량": "탱크로리·운송차량", "제조사용시설": "제조·사용시설",
                   "제조시설": "제조·사용시설", "사용시설": "제조·사용시설"}
ALIASES = {"명칭": "name", "물질명": "name", "제품명": "name", "설비명": "name", "시설명": "name",
           "화학물질명": "name", "물질명칭": "name", "설비명칭": "name", "품명": "name",
           "취급제품": "product", "취급물질": "product", "취급제품명": "product",
           "cas": "cas", "casno": "cas", "cas번호": "cas",
           "용량": "capacity", "용량m3": "capacity", "용량l": "capacity", "용량m³": "capacity", "용량㎥": "capacity",
           "운전압력mpa": "pressure", "운전압력kpa": "pressure", "운전압력": "pressure",
           "설계압력mpa": "design_pressure", "설계압력kpa": "design_pressure",
           "운전온도": "temperature", "운전온도c": "temperature", "운전온도°c": "temperature", "운전온도℃": "temperature",
           "최대보유량kg": "inventory", "최대보유량ton": "inventory", "최대보유량": "inventory",
           "함량": "concentration", "함량%": "concentration",
           "시설유형": "facility_type", "설비유형": "facility_type", "시설구분": "facility_type",
           "물질성상": "substance_state", "물질상태": "substance_state", "성상": "substance_state",
           "비중": "density", "밀도": "density", "비중kg/l": "density", "밀도kg/l": "density", "밀도g/cm3": "density",
           "밀도ton/m3": "density", "비중또는밀도": "density", "비중또는밀도kg/l=ton/m3": "density",
           "공정유형": "process_type", "공정구분": "process_type"}
ID_HEADERS = {"설비번호", "시설번호", "설비id", "제품코드", "물질코드", "설비코드", "장치번호", "tagno", "tag번호"}

NUMERIC_FIELDS = {"capacity", "pressure", "design_pressure", "temperature", "inventory", "concentration", "density"}
BOUNDS = {"capacity": (0, 1e6), "pressure": (0, 100), "design_pressure": (0, 100),
          "temperature": (-273.15, 2000), "inventory": (0, 1e9), "concentration": (0, 100), "density": (0, 30)}
UNIT_SUFFIXES = {"capacity": ("m3", "m³", "㎥", "l"), "pressure": ("mpa", "kpa"), "design_pressure": ("mpa", "kpa"),
                 "inventory": ("kg", "ton"), "temperature": ("c", "°c", "℃"), "concentration": ("%",)}
# 법적 판정(규정수량·방류벽 용량 등)에 직접 쓰이는 항목은 순위와 관계없이 엄격하게 봅니다.
LEGAL_FIELDS = {"inventory", "concentration", "cas", "capacity", "facility_type", "substance_state", "density", "process_type"}
STRICT_CONFIDENCE = 0.98
RELAXED_CONFIDENCE = 0.90
HEADER_SCAN_ROWS = 20
MAX_ROWS = 10001
MAX_COLUMNS = 200
MAX_UNZIPPED = 80 * 1024 * 1024
DECISION_LABEL = {"AUTO": "자동 기입", "PERSON": "확인 완료", "BULK": "확인 완료"}


def norm(value):
    return re.sub(r"[\s().·_-]", "", str(value)).lower()


# ---------------------------------------------------------------- 저장소

def _read(project):
    """읽기 전용 조회(복사하지 않음). 수정하려면 graph()를 쓰세요."""
    record = project.get_field(KEY)
    return record.value if record else {"documents": [], "facts": [], "decisions": {}}


def graph(project):
    return deepcopy(_read(project))


def _store(project, data):
    project.set_field(KEY, "사업장 공통정보와 출처", data, "HOLD", note="추출 후보와 담당자 결정을 분리해 보존")


def _invalidate(project):
    for record in project.fields.values():
        if record.note.startswith("공통정보 연결") or record.status == "AI_DRAFT":
            record.status = "HOLD"


# ---------------------------------------------------------------- 값 검증

def has_unit(field, header):
    h = norm(header)
    return any(h.endswith(suffix) for suffix in UNIT_SUFFIXES.get(field, ()))


def cas_valid(text):
    text = str(text)
    if not re.fullmatch(r"\d{2,7}-\d{2}-\d", text):
        return False
    digits = re.sub(r"\D", "", text)
    return sum(int(n) * (i + 1) for i, n in enumerate(digits[-2::-1])) % 10 == int(digits[-1])


def normalize_value(field, raw, header):
    text = str(raw).strip()
    if field in CHOICES:
        squeezed = re.sub(r"\s+", "", text)
        for option in CHOICES[field]:
            if squeezed == re.sub(r"\s+", "", option):
                return option
        return CHOICE_SYNONYMS.get(squeezed, text)
    if field in {"name", "product", "cas"}:
        return text
    # 범위나 단위가 불명확한 값을 임의로 숫자로 확정하지 않습니다.
    if not re.fullmatch(r"[+-]?\d+(?:,\d{3})*(?:\.\d+)?", text):
        return text
    number = float(text.replace(",", ""))
    if not math.isfinite(number):
        return text
    h = norm(header)
    if field in {"capacity", "pressure", "design_pressure", "inventory"} and h in {"용량", "운전압력", "설계압력", "최대보유량"}:
        return text
    if field == "capacity" and h.endswith("l"):
        number /= 1000
    if field in {"pressure", "design_pressure"} and h.endswith("kpa"):
        number /= 1000
    if field == "inventory" and h.endswith("ton"):
        number *= 1000
    return number


def value_problem(field, value):
    """승인할 수 없는 값이면 이유를, 괜찮으면 None을 돌려줍니다."""
    if field in {"name", "product"}:
        return None if str(value).strip() else "빈 값"
    if field in CHOICES:
        return None if value in CHOICES[field] else "허용 값: " + ", ".join(CHOICES[field])
    if field == "cas":
        return None if cas_valid(value) else "CAS 형식 또는 검산값이 맞지 않음"
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "범위·단위·수식을 확인해야 하는 값"
    low, high = BOUNDS[field]
    if value < low or value > high:
        return f"허용 범위({low:g}~{high:g}) 밖의 값 — 단위를 확인하세요"
    return None


# ---------------------------------------------------------------- 문서 읽기

class Table:
    """문서에서 읽은 표. flags는 (행, 열) → 'merged'|'formula'|'formula_uncached' (0부터)."""

    def __init__(self, location, rows, flags=None):
        self.location = location
        self.rows = rows
        self.flags = flags or {}


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        text = repr(value)
        return f"{value:f}".rstrip("0").rstrip(".") if "e" in text.lower() else text
    return str(value)


def _read_csv(content):
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp949")
    rows = list(csv.reader(StringIO(text)))
    return [Table("CSV", rows)] if rows else []


def _read_xlsx(content):
    from openpyxl import load_workbook
    try:
        values = load_workbook(BytesIO(content), data_only=True)
        formulas = load_workbook(BytesIO(content), data_only=False)
    except (BadZipFile, KeyError, ValueError) as exc:
        raise ValueError("엑셀 파일을 열 수 없습니다.") from exc
    tables = []
    try:
        for sheet in values.worksheets:
            if (sheet.max_row or 0) > MAX_ROWS:
                raise ValueError("한 시트에 10,000행 이하로 나눠 주세요.")
            fsheet = formulas[sheet.title]
            max_row, max_col = sheet.max_row or 0, min(sheet.max_column or 0, MAX_COLUMNS)
            if not max_row or not max_col:
                continue
            grid = [[_cell_text(v) for v in row] for row in
                    sheet.iter_rows(min_row=1, max_row=max_row, max_col=max_col, values_only=True)]
            flags = {}
            for r, row in enumerate(fsheet.iter_rows(min_row=1, max_row=max_row, max_col=max_col, values_only=True)):
                for c, raw in enumerate(row):
                    if isinstance(raw, str) and raw.startswith("="):
                        if grid[r][c] == "":
                            grid[r][c] = raw
                            flags[(r, c)] = "formula_uncached"
                        else:
                            flags[(r, c)] = "formula"
            for span in sheet.merged_cells.ranges:
                if (span.max_row - span.min_row + 1) * (span.max_col - span.min_col + 1) > 10000:
                    continue
                top = grid[span.min_row - 1][span.min_col - 1] if span.min_row <= max_row and span.min_col <= max_col else ""
                for r in range(span.min_row - 1, min(span.max_row, max_row)):
                    for c in range(span.min_col - 1, min(span.max_col, max_col)):
                        if (r, c) != (span.min_row - 1, span.min_col - 1):
                            grid[r][c] = top
                            flags[(r, c)] = "merged"
            while grid and not any(grid[-1]):
                grid.pop()
            label = sheet.title + ("" if sheet.sheet_state == "visible" else " (숨김 시트)")
            if grid:
                tables.append(Table(label, grid, flags))
    finally:
        values.close()
        formulas.close()
    return tables


def _read_docx(content):
    from docx import Document
    doc = Document(BytesIO(content))
    passages = [{"location": f"문단 {i}", "text": p.text} for i, p in enumerate(doc.paragraphs, 1) if p.text.strip()]
    tables = []
    for i, table in enumerate(doc.tables, 1):
        try:
            tables.append(Table(f"표 {i}", [[c.text for c in row.cells] for row in table.rows]))
        except Exception:
            continue
    return tables, passages


def _read_pdf(content):
    import pdfplumber
    tables, passages = [], []
    with pdfplumber.open(BytesIO(content)) as pdf:
        for i, page in enumerate(pdf.pages, 1):
            passages.append({"location": f"p.{i}", "text": page.extract_text() or ""})
            try:
                found = page.extract_tables()
            except Exception:
                found = []
            for j, table in enumerate(found, 1):
                tables.append(Table(f"p.{i} 표 {j}", [[("" if c is None else str(c)) for c in row] for row in table]))
    return tables, passages


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _read_hwpx(content):
    """HWPX(zip+XML)의 문단과 표를 읽습니다. 구형 HWP(바이너리)는 지원하지 않습니다."""
    try:
        archive = ZipFile(BytesIO(content))
    except BadZipFile as exc:
        raise ValueError("HWPX 파일을 열 수 없습니다. 구형 HWP는 HWPX 또는 PDF로 저장해 올려 주세요.") from exc
    with archive:
        if sum(info.file_size for info in archive.infolist()) > MAX_UNZIPPED:
            raise ValueError("압축을 푼 크기가 너무 큽니다.")
        names = sorted(n for n in archive.namelist() if re.fullmatch(r"Contents/section\d+\.xml", n))
        if not names:
            raise ValueError("HWPX 본문을 찾지 못했습니다.")
        tables, passages = [], []

        def text_of(node):
            return "".join(t.text or "" for t in node.iter() if _local(t.tag) == "t")

        def cell_text(cell):
            # 셀 안의 문단은 공백으로 이어 붙여 단어가 붙지 않게 합니다.
            parts = [text_of(p).strip() for p in cell.iter() if _local(p.tag) == "p"]
            return " ".join(part for part in parts if part) or text_of(cell).strip()

        def walk(node, section, state):
            for child in node:
                name = _local(child.tag)
                if name == "tbl":
                    rows = []
                    for tr in (n for n in child.iter() if _local(n.tag) == "tr"):
                        rows.append([cell_text(tc) for tc in tr if _local(tc.tag) == "tc"])
                    state["tables"] += 1
                    if rows:
                        tables.append(Table(f"{section} 표 {state['tables']}", rows))
                elif name == "p":
                    inner_tables = any(_local(n.tag) == "tbl" for n in child.iter())
                    if inner_tables:
                        walk(child, section, state)
                    else:
                        state["paragraphs"] += 1
                        text = text_of(child).strip()
                        if text:
                            passages.append({"location": f"{section} 문단 {state['paragraphs']}", "text": text})
                else:
                    walk(child, section, state)

        for index, name in enumerate(names, 1):
            raw = archive.read(name)
            if b"<!DOCTYPE" in raw[:2048].upper() or b"<!ENTITY" in raw.upper():
                raise ValueError("허용하지 않는 XML 구조입니다.")
            walk(ElementTree.fromstring(raw), f"구역 {index}", {"tables": 0, "paragraphs": 0})
    return tables, passages


def read_document(name, content):
    suffix = name.rsplit(".", 1)[-1].lower()
    if len(content) > 20 * 1024 * 1024:
        raise ValueError("파일은 20MB 이하로 올려 주세요.")
    tables, passages = [], []
    if suffix == "csv":
        tables = _read_csv(content)
    elif suffix == "xlsx":
        tables = _read_xlsx(content)
    elif suffix == "docx":
        tables, passages = _read_docx(content)
    elif suffix == "pdf":
        tables, passages = _read_pdf(content)
    elif suffix == "hwpx":
        tables, passages = _read_hwpx(content)
    elif suffix == "txt":
        text = content.decode("utf-8-sig", errors="replace")
        passages = [{"location": f"줄 {i}", "text": line} for i, line in enumerate(text.splitlines(), 1)]
    else:
        raise ValueError("CSV·XLSX·DOCX·HWPX·텍스트 PDF·TXT를 지원합니다. 다른 형식은 변환 후 가져오세요.")
    return tables, passages


def _is_known_header(cell):
    key = norm(cell or "")
    return key in ALIASES or key in ID_HEADERS


def find_header_row(rows):
    """제목·안내 문구가 위에 있어도 항목명이 가장 많이 모인 줄을 머리글로 고릅니다."""
    best, best_score = None, 0
    for index, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        score = sum(1 for cell in row if _is_known_header(cell))
        if score > best_score:
            best, best_score = index, score
    return best


# ---------------------------------------------------------------- 접수

def ingest(project, name, content, kind="facility", entity_hint=""):
    if kind not in {"facility", "material"}:
        raise ValueError("자료 종류를 확인하세요.")
    data = graph(project)
    digest = sha256(content).hexdigest()
    if any(d["sha256"] == digest and d["kind"] == kind and d.get("hint", "") == entity_hint for d in data["documents"]):
        return 0
    tables, passages = read_document(name, content)
    added, unmapped, table_info, skipped_rows = [], [], [], 0

    def add(entity, field, raw, location, header, *, method="table", confidence=0.78, flags=()):
        if "merged" in flags or "formula" in flags:
            confidence = min(confidence, RELAXED_CONFIDENCE)
        identifier = sha256(json.dumps([digest, kind, entity, field, location, str(raw)], ensure_ascii=False).encode()).hexdigest()[:24]
        added.append({"id": identifier, "entity": kind + ":" + str(entity).strip(), "kind": kind, "field": field,
                      "value": normalize_value(field, raw, header), "raw": str(raw), "header": str(header),
                      "document": name, "sha256": digest, "location": location, "method": method,
                      "confidence": confidence, "flags": list(flags)})

    for table in tables:
        rows = table.rows
        if not rows:
            continue
        if len(rows) > MAX_ROWS:
            raise ValueError("한 표에 10,000행 이하로 나눠 주세요.")
        header_at = find_header_row(rows)
        if header_at is None:
            unmapped.extend(str(h).strip() for h in rows[0] if str(h or "").strip())
            table_info.append({"location": table.location, "header_row": None, "rows": len(rows)})
            continue
        headers = [str(h or "").strip() for h in rows[header_at]]
        fields = [ALIASES.get(norm(h)) for h in headers]
        id_col = next((i for i, h in enumerate(headers) if norm(h) in ID_HEADERS), None)
        table_info.append({"location": table.location, "header_row": header_at + 1, "rows": len(rows) - header_at - 1})
        for r in range(header_at + 1, len(rows)):
            row = rows[r]
            id_value = str(row[id_col] or "").strip() if id_col is not None and id_col < len(row) else ""
            entity = id_value or entity_hint.strip()
            if not entity:
                entity = next((str(row[i]).strip() for i, f in enumerate(fields) if f == "name" and i < len(row) and row[i]), "")
            if not entity:
                if any(str(c or "").strip() for c in row):
                    skipped_rows += 1
                continue
            base = STRICT_CONFIDENCE if id_value else 0.78
            id_flags = ("merged",) if id_value and table.flags.get((r, id_col)) == "merged" else ()
            for i, field in enumerate(fields):
                if i >= len(row) or row[i] is None or not str(row[i]).strip():
                    continue
                if field:
                    flag = table.flags.get((r, i))
                    cell_flags = tuple(f for f in (flag,) if f) + id_flags
                    add(entity, field, row[i], f"{table.location} 행 {r + 1} 열 {i + 1}", headers[i],
                        confidence=base, flags=cell_flags)
                elif headers[i] and i != id_col:
                    unmapped.append(headers[i])
    # 식별 대상을 지정한 명확한 '항목: 값' 문장만 후보로 추출합니다.
    for passage in passages:
        if not entity_hint.strip():
            continue
        for line in passage["text"].splitlines():
            parts = re.split(r"[:：]", line, maxsplit=1)
            if len(parts) == 2 and ALIASES.get(norm(parts[0])):
                add(entity_hint, ALIASES[norm(parts[0])], parts[1].strip(), passage["location"], parts[0],
                    method="literal", confidence=0.88)
    data["documents"].append({"name": name, "sha256": digest, "kind": kind, "hint": entity_hint, "passages": passages,
                              "fact_count": len(added), "unmapped_columns": sorted(set(unmapped)),
                              "tables": table_info, "rows_without_id": skipped_rows,
                              "needs_reading": not added,
                              "needs_ocr": bool(passages) and not any(p["text"].strip() for p in passages)})
    data["facts"].extend(added)
    _store(project, data)
    _invalidate(project)
    auto_approve_safe(project)
    return len(added)


# ---------------------------------------------------------------- 사실 묶음(slot)과 규칙

def _slots(data):
    groups = {}
    for fact in data["facts"]:
        groups.setdefault(fact["entity"] + "|" + fact["field"], []).append(fact)
    result = []
    for key, facts in groups.items():
        values = {json.dumps(f["value"], ensure_ascii=False, sort_keys=True) for f in facts}
        decision = data["decisions"].get(key) or {}
        signature = sha256(json.dumps(sorted(f["id"] for f in facts)).encode()).hexdigest()
        ids = {f["id"] for f in facts}
        confirmed = bool(decision and decision.get("signature") == signature and decision.get("fact_id") in ids)
        chosen = next((f for f in facts if confirmed and f["id"] == decision["fact_id"]), None)
        status = DECISION_LABEL.get(decision.get("method"), "확인 완료") if confirmed else ("값 충돌" if len(values) > 1 else "담당자 확인")
        result.append({"key": key, "entity": facts[0]["entity"], "field": facts[0]["field"], "facts": facts,
                       "signature": signature, "status": status, "chosen": chosen,
                       "method": decision.get("method") if confirmed else None})
    return result


def slots(project):
    return _slots(_read(project))


def graph_facts(project):
    """읽기 전용 사실 목록(복사하지 않음)."""
    return _read(project)["facts"]


def critical_slot_keys(project):
    """결과 순위를 바꿀 수 있는 값의 slot 키. 순위 계산이 불가능하면 빈 집합."""
    try:
        from .scenario_triage import critical_slot_keys as compute
        return compute(project)
    except Exception:
        return frozenset()


def review_gate(slot, critical=frozenset()):
    """자동 기입을 막는 이유 목록. 빈 목록이면 자동 기입해도 됩니다.

    모델 신뢰도 자체는 승인 근거가 아니며, 아래 규칙을 모두 통과해야 합니다.
    """
    facts = slot["facts"]
    field = slot["field"]
    if len({json.dumps(f["value"], ensure_ascii=False, sort_keys=True) for f in facts}) > 1:
        return ["자료 간 값 충돌"]
    for fact in facts:
        problem = value_problem(field, fact["value"])
        if problem:
            return [problem]
    if any(f.get("method") != "table" for f in facts):
        return ["문장 또는 AI 추출값"]
    if field in UNIT_SUFFIXES and any(not has_unit(field, f.get("header", "")) for f in facts):
        return ["항목명에 단위가 없음"]
    strict = field in LEGAL_FIELDS or slot["key"] in critical
    needed = STRICT_CONFIDENCE if strict else RELAXED_CONFIDENCE
    low = [f for f in facts if f.get("confidence", 0) < needed]
    if low:
        causes = []
        for f in low:
            if f.get("confidence", 0) < RELAXED_CONFIDENCE:
                causes.append("설비번호·제품코드 없이 이름으로 연결")
            elif "formula" in f.get("flags", []):
                causes.append("수식 계산 결과")
            else:
                causes.append("병합 셀에서 가져옴")
        why = "법적 판단에 쓰이는 항목" if field in LEGAL_FIELDS else "예비 순위를 바꿀 수 있는 핵심값"
        prefix = f"{why}이라 엄격 적용: " if strict else ""
        return [prefix + "출처 신뢰도 부족(" + ", ".join(dict.fromkeys(causes)) + ")"]
    return []


def auto_approve_safe(project):
    data = graph(project)
    critical = critical_slot_keys(project)
    count = 0
    for slot in _slots(data):
        if slot["chosen"] or review_gate(slot, critical):
            continue
        data["decisions"][slot["key"]] = {"fact_id": slot["facts"][0]["id"], "signature": slot["signature"], "method": "AUTO"}
        count += 1
    if count:
        _store(project, data)
    return count


def approve(project, key, fact_id):
    slot = next(s for s in slots(project) if s["key"] == key)
    fact = next(f for f in slot["facts"] if f["id"] == fact_id)
    problem = value_problem(slot["field"], fact["value"])
    if problem:
        raise ValueError(problem)
    data = graph(project)
    data["decisions"][key] = {"fact_id": fact_id, "signature": slot["signature"], "method": "PERSON"}
    _invalidate(project)
    _store(project, data)


def approve_bulk(project, keys=None):
    """표에서 읽은, 충돌 없고 유효한 값을 한꺼번에 확인합니다. AI·문장 추출값은 제외합니다."""
    data = graph(project)
    wanted = set(keys) if keys is not None else None
    approved, skipped = 0, []
    for slot in _slots(data):
        if slot["chosen"] or (wanted is not None and slot["key"] not in wanted):
            continue
        facts = slot["facts"]
        values = {json.dumps(f["value"], ensure_ascii=False, sort_keys=True) for f in facts}
        reason = None
        if len(values) > 1:
            reason = "값 충돌"
        elif any(f.get("method") != "table" for f in facts):
            reason = "문장 또는 AI 추출값"
        else:
            reason = next((value_problem(slot["field"], f["value"]) for f in facts if value_problem(slot["field"], f["value"])), None)
        if reason:
            skipped.append((slot["key"], reason))
            continue
        data["decisions"][slot["key"]] = {"fact_id": facts[0]["id"], "signature": slot["signature"], "method": "BULK"}
        approved += 1
    if approved:
        _invalidate(project)
        _store(project, data)
    return {"approved": approved, "skipped": skipped}


def confirm_auto(project, keys):
    """자동 기입한 값을 사람이 확인한 것으로 바꿉니다(핵심값 확인용)."""
    data = graph(project)
    changed = 0
    for key in keys:
        decision = data["decisions"].get(key)
        if decision and decision.get("method") == "AUTO":
            decision["method"] = "PERSON"
            changed += 1
    if changed:
        _store(project, data)
    return changed


def add_manual(project, entity, field, value, reason, confirm=False):
    if not entity.startswith(("facility:", "material:")) or field not in LABELS or not reason.strip():
        raise ValueError("대상 식별번호·항목·확인 근거를 입력하세요.")
    header = LABELS[field]
    normalized = normalize_value(field, value, header)
    if confirm:
        problem = value_problem(field, normalized)
        if problem:
            raise ValueError(problem)
    data = graph(project)
    fact = {"entity": entity, "kind": entity.split(":", 1)[0], "field": field, "value": normalized,
            "raw": str(value), "header": header, "document": "담당자 입력", "sha256": sha256(reason.encode()).hexdigest(),
            "location": reason.strip(), "method": "manual", "confidence": 0.9, "flags": []}
    fact["id"] = sha256(json.dumps(fact, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
    if fact["id"] not in {f["id"] for f in data["facts"]}:
        data["facts"].append(fact)
    _invalidate(project)
    _store(project, data)
    if confirm:
        slot = next(s for s in slots(project) if s["entity"] == entity and s["field"] == field)
        approve(project, slot["key"], fact["id"])


def confirmed_entities(project):
    entities = {}
    for slot in slots(project):
        if slot["chosen"]:
            entities.setdefault(slot["entity"], {})[slot["field"]] = slot["chosen"]["value"]
    return entities


# ---------------------------------------------------------------- 사람이 볼 목록

def review_queue(project):
    """사람이 처리할 예외 목록: 충돌 → 값 오류 → 확인 필요, 핵심값 먼저."""
    critical = critical_slot_keys(project)
    order = {"충돌": 0, "값 오류": 1, "확인 필요": 2}
    items = []
    for slot in slots(project):
        if slot["chosen"]:
            continue
        reasons = review_gate(slot, critical)
        if slot["status"] == "값 충돌":
            kind = "충돌"
        elif any(value_problem(slot["field"], f["value"]) for f in slot["facts"]):
            kind = "값 오류"
        else:
            kind = "확인 필요"
        items.append({"key": slot["key"], "entity": slot["entity"], "field": slot["field"], "kind": kind,
                      "reasons": reasons, "slot": slot, "critical": slot["key"] in critical})
    items.sort(key=lambda i: (order[i["kind"]], not i["critical"], i["entity"], i["field"]))
    return items


def critical_auto(project):
    """자동 기입했지만 결과를 바꿀 수 있어 먼저 확인할 값."""
    critical = critical_slot_keys(project)
    return [s for s in slots(project) if s["method"] == "AUTO" and s["key"] in critical]


def summary(project):
    all_slots = slots(project)
    queue = review_queue(project)
    return {"documents": len(_read(project)["documents"]), "slots": len(all_slots),
            "auto": sum(s["method"] == "AUTO" for s in all_slots),
            "person": sum(s["method"] in {"PERSON", "BULK"} for s in all_slots),
            "conflicts": sum(i["kind"] == "충돌" for i in queue),
            "errors": sum(i["kind"] == "값 오류" for i in queue),
            "pending": len(queue), "critical_auto": len(critical_auto(project))}


def tasks(project):
    data = _read(project)
    all_slots = _slots(data)
    result = [{"entity": s["entity"], "task": s["status"] + ": " + LABELS[s["field"]], "key": s["key"]}
              for s in all_slots if not s["chosen"]]
    for doc in data["documents"]:
        if doc["needs_reading"]:
            result.append({"entity": doc["name"],
                           "task": "OCR 또는 문서 구조 확인 필요" if doc["needs_ocr"] else
                           "문서를 읽었지만 사실을 연결하지 못했습니다. 표·항목 또는 식별 대상을 확인하세요.", "key": ""})
        elif doc.get("rows_without_id"):
            result.append({"entity": doc["name"],
                           "task": f"설비번호·제품코드·명칭이 없어 건너뛴 행 {doc['rows_without_id']}개", "key": ""})
    by_entity, confirmed = {}, {}
    for s in all_slots:
        by_entity.setdefault(s["entity"], set()).add(s["field"])
        if s["chosen"]:
            confirmed.setdefault(s["entity"], {})[s["field"]] = s["chosen"]["value"]
    for identifier in sorted(e for e in by_entity if e.startswith("facility:")):
        present = by_entity[identifier]
        for field in ("product", "inventory", "pressure", "temperature", "facility_type", "substance_state"):
            if field not in present:
                result.append({"entity": identifier, "task": "기본 운전조건 미확인: " + LABELS[field], "key": ""})
        product = confirmed.get(identifier, {}).get("product")
        if product:
            matches = [k for k, v in confirmed.items() if k.startswith("material:") and (v.get("name") == product or k.split(":", 1)[1] == product)]
            if len(matches) != 1:
                result.append({"entity": identifier, "task": "취급제품과 물질자료를 하나로 연결할 수 없습니다. 제품코드·이름을 확인하세요.", "key": ""})
    result.extend({"entity": "별지 제1호", "task": need, "key": ""} for need in form1_needs(project))
    return result


def form1_needs(project):
    """연결한 설비 자료로 별지 제1호 최대보유량을 계산할 때 아직 부족한 값(계산 엔진이 알려 줌)."""
    record = project.get_field("inventory.facilities")
    if record is None or record.status not in {"USER_CONFIRMED", "VERIFIED"}:
        return ()
    try:
        from . import cap_workspace
        return tuple(cap_workspace.resolve_form1(project).needs)
    except Exception:
        return ()


# ---------------------------------------------------------------- 연결·보고서

def publishing_plan(project):
    mapping = {"name": "물질명", "cas": "CAS 번호", "concentration": "함량(%)"}
    facilities = {"name": "설비명", "product": "취급물질", "capacity": "용량", "pressure": "운전압력(MPa)",
                  "design_pressure": "설계압력(MPa)", "temperature": "운전온도(℃)", "inventory": "최대보유량(kg)",
                  "facility_type": "시설유형", "substance_state": "물질성상", "density": "비중", "process_type": "공정유형"}
    entities = confirmed_entities(project)
    plans = {}
    for kind, target, columns in [("material", "inventory.chemicals", mapping), ("facility", "inventory.facilities", facilities)]:
        rows = []
        for identifier, values in entities.items():
            if not identifier.startswith(kind + ":"):
                continue
            row = {columns[k]: v for k, v in values.items() if k in columns}
            row["물질코드" if kind == "material" else "시설번호"] = identifier.split(":", 1)[1]
            if kind == "facility":
                row["설비번호"] = identifier.split(":", 1)[1]
                if "capacity" in values:
                    row["용량단위"] = "m3"
                if "name" in values:
                    row["시설명"] = values["name"]
                matches = [v for k, v in entities.items() if k.startswith("material:") and (v.get("name") == values.get("product") or k.split(":", 1)[1] == values.get("product"))]
                if len(matches) == 1:
                    row["취급물질"] = matches[0].get("name", values.get("product", ""))
                    row["제품명"] = row["취급물질"]
                    if "cas" in matches[0]:
                        row["CAS 번호"] = matches[0]["cas"]
            rows.append(row)
        if rows:
            plans[target] = rows
    return plans


def publish(project, *, replace_existing=False):
    plans = publishing_plan(project)
    if not plans:
        raise ValueError("연결할 확인 완료 사실이 없습니다.")
    for key, rows in plans.items():
        existing = project.get_field(key)
        if existing and existing.value != rows and not replace_existing:
            raise ValueError("기존 작성자료와 다릅니다. 비교 후 교체 항목을 확인하세요.")
    for key, rows in plans.items():
        project.set_field(key, "공통정보에서 연결한 " + key, rows, "USER_CONFIRMED",
                          note="공통정보 연결: 출처와 필드별 결정은 workspace.evidence_graph에 보존")
    return list(plans)


def report(project):
    from .scenario_triage import evaluate
    lines = ["# 사업장 공통정보 검토", "", project.company_name, "", "## 확인한 사실"]
    for slot in slots(project):
        if slot["chosen"]:
            f = slot["chosen"]
            how = DECISION_LABEL.get(slot["method"], "확인 완료")
            lines.append(f"- {slot['entity']} / {LABELS[slot['field']]}: {f['value']} [{how}] "
                         f"({f['document']} · {f['location']} · SHA256 {f['sha256']})")
    info = summary(project)
    lines += ["", "## 자동 기입 현황", "",
              f"- 자동 기입 {info['auto']}개, 사람이 확인 {info['person']}개, 남은 확인 {info['pending']}개",
              f"- 자동 기입 중 사람이 아직 보지 않은 핵심값 {info['critical_auto']}개"]
    lines += ["", "## 남은 확인 과제"] + [f"- {t['entity']}: {t['task']}" for t in tasks(project)]
    triage = evaluate(project)
    lines += ["", "## 물질×설비 예비 검토 순서", "", triage["method"]]
    for row in triage["rows"]:
        lines.append(f"- {row['facility']} × {row['material']}: 순위 {row['rank'] if row['rank'] is not None else '취급 관계 미확인'}, "
                     f"지표 {row['score']:g}, 상태 {row['state']}, 가정 {', '.join(row['assumptions']) or '없음'}, "
                     f"핵심값 {', '.join(row['rank_critical']) or '없음'}, 보류 {', '.join(row['blockers']) or '없음'}")
    lines += ["", "## 순위를 바꾸는 결측 질문"] + [f"- {q['facility']} × {q['material']}: {q['question']}" for q in triage["questions"]]
    lines += ["", "이 문서는 자료 검토용입니다. 기본 운전조건 외의 시나리오 선정조건·안전설비·누출조건·물성·계산모델은 기존 계산 화면에서 별도로 검토합니다."]
    return "\n".join(lines)


def scenario_packets(project):
    packets = []
    all_slots = slots(project)
    task_list = tasks(project)
    for entity, values in confirmed_entities(project).items():
        if not entity.startswith("facility:"):
            continue
        packets.append({"설비": entity, "확인한 기본조건": values,
                        "연결된 출처": [{"항목": LABELS[s["field"]], "문서": s["chosen"]["document"], "위치": s["chosen"]["location"]}
                                    for s in all_slots if s["entity"] == entity and s["chosen"]],
                        "자료 확인 과제": [t["task"] for t in task_list if t["entity"] == entity],
                        "별도 시나리오 검토": ["설비·배관 연결관계와 누출 위치", "물성·상태와 적용 모델", "누출 크기·지속시간", "안전설비·차단 조건", "사고유형과 선정 근거"],
                        "상태": "입력 검토용 — 시나리오 선정·계산 미수행"})
    return packets


def demo_zip():
    """가상 회사 시험자료. 모든 값은 허구이며 실제 운전·평가에 쓸 수 없습니다."""
    from openpyxl import Workbook
    files = {"01_materials.csv": "제품코드,제품명,CAS 번호,함량(%)\nP-01,가상 에탄올 제품,64-17-5,99\nP-02,가상 메탄올 제품,67-56-1,100\n",
             "02_equipment.csv": "설비번호,설비명,취급제품,용량(L),최대보유량(kg),운전압력(kPa),운전온도(C)\n"
                                 "TK-01,가상 저장탱크,가상 에탄올 제품,10000,7000,100,25\n"
                                 "TK-02,가상 보조탱크,가상 메탄올 제품,5000,3500,100,25\n",
             "03_old_equipment.csv": "설비번호,용량(m3)\nTK-01,12\n"}
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "설비대장"
    sheet.append(["가상공장 설비대장 (작성 기준일 2026-03)", "", "", "", ""])
    sheet.append(["", "", "", "", ""])
    sheet.append(["설비번호", "설비명", "취급제품", "최대보유량(kg)", "운전압력(MPa)"])
    sheet.append(["RX-01", "가상 반응기", "가상 에탄올 제품", "=1500+500", 0.3])
    sheet.append(["RX-02", "가상 예비 반응기", "가상 에탄올 제품", None, 0.3])
    buffer = BytesIO()
    workbook.save(buffer)
    out = BytesIO()
    with ZipFile(out, "w", ZIP_DEFLATED) as z:
        for name, text in files.items():
            z.writestr(name, text.encode("utf-8-sig"))
        z.writestr("04_ledger_with_title.xlsx", buffer.getvalue())
        z.writestr("README.txt", "모든 회사·설비·운전값은 가상 시험자료입니다. 물질 파일(01)은 제품·물질 자료로, 나머지는 설비 자료로 올리세요. "
                                 "02와 03의 TK-01 용량 10m3/12m3는 의도적인 충돌입니다. 04는 제목 줄과 빈 줄 아래에 머리글이 있고 "
                                 "수식 셀과 빈 칸이 있어, 실제 대장처럼 읽히는지 확인하는 용도입니다.")
    return out.getvalue()
