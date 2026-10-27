"""읽힌 회사 문서의 명시적 항목을 CAP 법정서식의 필드로 연결한다.

두 칸짜리 항목/값 표만 연결한다. 제목이나 파일 이름만 보고 값을 추측하지 않는다.
판정·대응계획은 원문과 대조하기 전에는 서식의 확정값으로 취급하지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
import re

from .cap_form3_workspace import fields as form3_fields
from .cap_form16_workspace import items as form16_items
from .cap_form4_workspace import LOADING_KEY, OVERVIEW_KEY, PROCESS_KEY
from .cap_form5_workspace import OVERVIEW_KEY as UNIT_OVERVIEW_KEY
from .project import EvidenceRef

NOTE = "업로드 문서의 항목·값 자동 연결"
DIRECT = {item["label"]: (item["key"], item["label"], item["kind"] != "choice")
          for item in form3_fields()}
DIRECT.update({
    "총괄 취급시설 단위공장 구성": (OVERVIEW_KEY, "총괄 취급시설 단위공장 구성", True),
    "공정개요": (PROCESS_KEY, "공정개요", True),
    "단위공장 취급시설 개요": (UNIT_OVERVIEW_KEY, "단위공장 취급시설 개요", True),
})
DIRECT.update({item["label"]: (item["key"], item["label"], False) for item in form16_items()})
CHOICES = {item["key"]: set(item.get("options") or ()) for item in form3_fields() if item["kind"] == "choice"}
LOADING_LABEL = "입·출하 시설 수(기)"


def _candidate(label, value, source, digest, location):
    label, value = str(label).strip(), str(value).strip()
    if not value or value in {"-", "해당 없음(미확인)"}:
        return None
    if label == LOADING_LABEL:
        if not re.fullmatch(r"\d{1,5}", value):
            return None
        key, title, auto = LOADING_KEY, "입·출하 및 운반시설", True
        value = f"입·출하 시설 {int(value)}기"
    elif label in DIRECT:
        key, title, auto = DIRECT[label]
        if key in CHOICES and value not in CHOICES[key]:
            return None
    else:
        return None
    return {"key": key, "label": title, "value": value, "auto": auto,
            "document": source, "sha256": digest, "location": location}


def extract(tables, source, digest):
    """서식에 해당하는 정확한 2열 표만 사용하고 각 셀의 원본 위치를 기록한다."""
    found = []
    for table in tables:
        for number, row in enumerate(table.rows, 1):
            if len(row) != 2:
                continue
            candidate = _candidate(row[0], row[1], source, digest, f"{table.location} {number}행 2열")
            if candidate:
                found.append(candidate)
    return found


def synchronize(project, documents):
    """다른 파일의 상충값을 합쳐 보류한다. 사용자가 확정한 필드는 변경하지 않는다."""
    grouped = defaultdict(list)
    for doc in documents:
        for candidate in doc.get("links", []):
            grouped[candidate["key"]].append(candidate)
    for key, candidates in grouped.items():
        existing = project.get_field(key)
        if existing and existing.status == "USER_CONFIRMED":
            continue
        if existing and existing.note != NOTE:
            continue
        distinct = {str(candidate["value"]) for candidate in candidates}
        evidence = [EvidenceRef("upload", candidate["document"], sha256=candidate["sha256"],
                                location=candidate["location"]) for candidate in candidates]
        first = candidates[0]
        status = "HOLD" if len(distinct) > 1 else "VERIFIED" if all(c["auto"] for c in candidates) else "AI_DRAFT"
        project.set_field(key, first["label"], first["value"] if len(distinct) == 1 else "", status,
                          evidence=evidence, note=NOTE)
    return grouped


def confirm(project, key):
    """원본과 대조한 초안만 확정할 수 있다. 충돌값은 문서를 고쳐야 한다."""
    record = project.get_field(key)
    if not record or record.note != NOTE or record.status != "AI_DRAFT":
        return False
    project.set_field(key, record.label, record.value, "USER_CONFIRMED", evidence=record.evidence,
                      note=f"{NOTE}; 담당자가 원본 확인")
    return True
