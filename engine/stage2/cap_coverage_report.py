"""화학사고예방관리계획서 항목별 자료 현황.

두 가지를 사람 말로 알려 줍니다.
1. 올린 파일마다 프로그램이 어디까지 읽었는지(읽지 못한 부분 포함).
2. 서식 항목(별지)마다 회사 파일에서 채웠는지, 자료에 없는지, 프로그램이 계산·조회하는지.

‘자료에 없음’과 ‘읽지 못했을 수 있음’은 구분합니다. 읽지 못한 파일이 하나라도 있으면 빈 항목은 그 파일에 있을 수 있다고 알립니다.
"""
from __future__ import annotations

from . import cap_form_coverage as cov
from . import evidence_workspace as ew
from .project import Stage2Project

FILLED = "채워짐"
MISSING = "자료에 없음"
POSSIBLY_UNREAD = "읽지 못했을 수 있음"
CONDITIONAL = "해당 시 필요"
COMPUTED = "프로그램이 계산·조회"

READ_OK = "읽음"
READ_PARTIAL = "일부만 읽음"
READ_NOT_LINKED = "읽었지만 서식에 연결된 값 없음"
READ_FAILED = "읽지 못함"

_COMPUTED_STATES = {cov.LEGAL_ENGINE, cov.CALCULATION, cov.EXTERNAL_ANALYSIS, cov.RENDERER_GAP}


def file_results(project: Stage2Project) -> list[dict]:
    """올린 파일별 읽기 결과. 읽지 못한 이유와 고칠 방법을 함께 돌려줍니다."""
    rows = []
    for doc in ew.documents(project):
        facts = int(doc.get("fact_count") or 0)
        skipped = int(doc.get("rows_without_id") or 0)
        unmapped = list(doc.get("unmapped_columns") or [])
        tables = len(doc.get("tables", []))
        if doc.get("needs_ocr"):
            status, why, fix = READ_FAILED, "글자가 없는 스캔본이라 내용을 읽을 수 없어요.", "글자가 있는 PDF나 엑셀·한글 파일로 다시 올려 주세요."
        elif doc.get("needs_reading") and facts == 0:
            status = READ_NOT_LINKED
            why = doc.get("problem") or "문서는 읽었지만 서식 칸에 연결할 값을 찾지 못했어요."
            fix = ("표 머리글에 설비번호·제품코드·용량 같은 항목 이름을 넣어 다시 올려 주세요."
                   if tables else "문장으로만 적힌 내용은 표(항목·값 2열)로 정리해 다시 올려 주세요.")
        elif skipped or unmapped:
            status = READ_PARTIAL
            parts = []
            if unmapped:
                parts.append("프로그램이 모르는 열: " + ", ".join(unmapped[:6]) + (" 외" if len(unmapped) > 6 else ""))
            if skipped:
                parts.append(f"번호·이름이 없거나 합계 줄이라 건너뛴 행 {skipped}개")
            why, fix = " / ".join(parts), "열 이름과 단위를 확인하고 설비번호·제품코드를 채워 다시 올려 주세요."
        else:
            status, why, fix = READ_OK, "", ""
        rows.append({"파일": doc["name"], "읽은 결과": status, "읽어서 채운 값": facts,
                     "읽지 못한 이유": why, "고치는 방법": fix, "_ok": status == READ_OK})
    return rows


def item_status(project: Stage2Project) -> list[dict]:
    """화사계 서식 항목별 현황(별지 번호순)."""
    unread = [r["파일"] for r in file_results(project) if not r["_ok"]]
    rows = []
    for item in cov.audit_cap_form_coverage(project):
        files = []
        for key in item.field_keys:
            record = project.get_field(key)
            if record is not None:
                files.extend(ref.source_name for ref in record.evidence if ref.source_name)
        files = list(dict.fromkeys(files))
        if item.state == cov.READY:
            status, note = FILLED, ""
        elif item.state in _COMPUTED_STATES:
            status, note = COMPUTED, "회사 자료가 갖춰지면 프로그램이 채워요."
        elif item.state in {cov.CONDITIONAL, cov.NOT_APPLICABLE}:
            status, note = CONDITIONAL, item.note or "해당하는 경우에만 필요해요."
        elif unread:
            status = POSSIBLY_UNREAD
            note = "읽지 못한 파일이 있어요: " + ", ".join(unread[:3]) + (" 외" if len(unread) > 3 else "")
        else:
            status, note = MISSING, "올린 파일에서 찾지 못했어요."
        rows.append({"별지": f"제{item.form_no}호", "서식": item.form_name, "항목": item.item, "현황": status,
                     "채운 파일": ", ".join(files), "필요한 자료": item.required_input, "비고": note,
                     "_form": item.form_no})
    rows.sort(key=lambda r: r["_form"])
    return rows


def summary(project: Stage2Project) -> dict:
    items = item_status(project)
    counts: dict[str, int] = {}
    for row in items:
        counts[row["현황"]] = counts.get(row["현황"], 0) + 1
    return {"total": len(items), "counts": counts, "files": file_results(project), "items": items}
