"""읽힌 회사 문서의 명시적 항목을 CAP 법정서식의 필드로 연결한다.

두 칸짜리 항목/값 표만 연결한다. 제목이나 파일 이름만 보고 값을 추측하지 않는다.
프로그램 안에 승인 단계는 두지 않는다: 읽은 값은 바로 초안(FILE_READ)에 넣고, 파일끼리 값이 다르면 보류(HOLD)해
어느 파일을 고칠지 알린다. 사람이 다른 곳에서 확정한 값(USER_CONFIRMED)은 바꾸지 않는다.
"""
from __future__ import annotations

from collections import defaultdict
import re

from .cap_form3_workspace import fields as form3_fields
from .cap_form16_workspace import items as form16_items
from .cap_form4_workspace import LOADING_KEY, OVERVIEW_KEY, PROCESS_KEY
from .cap_form5_workspace import OVERVIEW_KEY as UNIT_OVERVIEW_KEY
from .cap_form2_workspace import SUBMISSION_TYPE_KEY, SUBMISSION_REASON_KEY, UNIT_PLANT_KEY, SUBMISSION_TYPES, SUBMISSION_REASONS
from .project import EvidenceRef

NOTE = "업로드 문서의 항목·값 자동 연결"
DIRECT = {item["label"]: (item["key"], item["label"], item["kind"] != "choice")
          for item in form3_fields()}
DIRECT.update({
    "단위공장명": (UNIT_PLANT_KEY, "단위공장명", True),
    "제출구분": (SUBMISSION_TYPE_KEY, "제출구분", False),
    "제출 사유": (SUBMISSION_REASON_KEY, "제출 사유", False),
    "총괄 취급시설 단위공장 구성": (OVERVIEW_KEY, "총괄 취급시설 단위공장 구성", True),
    "공정개요": (PROCESS_KEY, "공정개요", True),
    "단위공장 취급시설 개요": (UNIT_OVERVIEW_KEY, "단위공장 취급시설 개요", True),
})
DIRECT.update({item["label"]: (item["key"], item["label"], False) for item in form16_items()})
CHOICES = {item["key"]: set(item.get("options") or ()) for item in form3_fields() if item["kind"] == "choice"}
CHOICES[SUBMISSION_TYPE_KEY] = set(SUBMISSION_TYPES)
CHOICES[SUBMISSION_REASON_KEY] = set(SUBMISSION_REASONS)
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
        status = "HOLD" if len(distinct) > 1 else "FILE_READ"
        project.set_field(key, first["label"], first["value"] if len(distinct) == 1 else "", status,
                          evidence=evidence, note=NOTE)
    return grouped


def linked(record) -> bool:
    """근거자료의 항목·값 표에서 연결한 값인지(사람이 다른 곳에서 적은 값과 구분)."""
    return record is not None and str(record.note).startswith(NOTE)


def forget(project, documents, removed):
    """파일을 빼면 그 파일에서만 연결한 칸을 지우고 남은 파일로 다시 맞춥니다."""
    keys = {c["key"] for doc in removed for c in doc.get("links", [])}
    for key in keys:
        if linked(project.get_field(key)):
            project.fields.pop(key, None)
    return synchronize(project, documents)
