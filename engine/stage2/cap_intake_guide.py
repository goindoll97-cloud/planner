"""회사에 요청할 자료 목록. 작성요건 registry와 동일한 항목을 사용한다."""
from __future__ import annotations

from collections import defaultdict
from io import BytesIO

from .requirements import COMMON_REQUIREMENTS, cap_requirement_specs


def checklist(group: str = "") -> list[dict]:
    """작성수준 미확정이면 1·2군 합집합을 보여 주고 조건부임을 표시한다."""
    selected = group if group in {"1군", "2군"} else ""
    source = cap_requirement_specs(selected) if selected else cap_requirement_specs("1군") + cap_requirement_specs("2군")
    seen: dict[str, set[str]] = defaultdict(set)
    for level in ("1군", "2군"):
        for spec in cap_requirement_specs(level):
            seen[spec.key].add(level)
    rows = []
    for spec in (*COMMON_REQUIREMENTS, *source):
        if any(row["key"] == spec.key for row in rows):
            continue
        evidence = list(dict.fromkeys(spec.suggested_evidence))
        rows.append({"key": spec.key, "section": spec.section, "label": spec.label,
                     "details": spec.description, "evidence": evidence,
                     "levels": sorted(seen.get(spec.key, {"1군", "2군"})),
                     "basis": spec.legal_basis, "pages": spec.manual_pages,
                     "required": spec.required})
    return rows


def guidance_text(group: str = "", *, drawings: bool = True) -> str:
    level = group if group in {"1군", "2군"} else "작성수준 미확정 (1·2군 전체 후보)"
    lines = ["화학사고예방관리계획서 회사자료 요청 목록", f"적용 범위: {level}",
             "한 번에 여러 파일을 올리세요. 아래 항목은 자료를 모을 때의 목록이며, 업로드만으로 법정 서식이 자동 완성되지는 않습니다.",
             "파일에는 설비번호·제품코드·적용 공장, 단위, 작성·개정일, 출처를 적어 주세요. 실제 최대보유량·취급량은 별도 확인이 필요합니다.",
             "허용 형식: CSV/XLSX, 텍스트 PDF, DOCX, HWP 5.0, HWPX, TXT. 암호화·구형 HWP 또는 스캔본은 한글에서 HWPX로 저장하거나 OCR 후 원본과 대조하세요.",
             "작성수준과 물질별 취급량·보유량 판정은 승인된 최신 규정 DB의 계산 결과로 확인합니다. 미확정이면 1·2군 자료를 함께 준비하세요.",
             "사고시나리오 대상, 영향범위, 주민·보호대상 및 지도는 물질·시설·주소를 확인한 뒤 추가 자료를 요청합니다. 지도 후보는 현장과 대조하세요.", ""]
    current = None
    for row in checklist(group):
        if not drawings and ("도면" in row["section"] or row["key"].startswith("common.pf") or row["key"] == "common.site_plan"):
            continue
        if row["section"] != current:
            current = row["section"]
            lines.extend([f"[{current}]", ""])
        levels = row["levels"]
        qualifier = " (1군 판정 시 추가)" if levels == ["1군"] and group != "1군" else ""
        qualifier += " (적용 여부 확인)" if not row["required"] else ""
        lines.append(f"• {row['label']}{qualifier}")
        lines.append(f"  필요한 내용: {row['details']}")
        lines.append("  요청할 자료: " + (" / ".join(row["evidence"]) if row["evidence"] else "해당 항목의 회사 보유자료·계산근거·확인기록"))
        if row["basis"]:
            lines.append(f"  작성 참고: {row['basis']}")
        lines.append("")
    lines.extend(["조건이 달라지면 추가 확인", "• 물질·농도·성상·최대보유량·일일 취급량이 바뀌면 작성수준과 대상시설을 다시 판정하세요.",
                  "• 1군으로 확인되면 외부 비상대응·지역사회 소통 관련 자료도 제출하세요.",
                  "• 공동비상대응, 타 제도 심사결과 활용, 변경제출 여부는 각 증빙이 있을 때 해당 자료를 추가하세요.",
                  "• 누락 자료는 파일·항목별 보완 요청으로 돌려보내고, 규정 기준표가 없으면 판정 보류로 표시합니다."])
    return "\n".join(lines) + "\n"


def conditional_notice(group: str) -> str:
    """승인된 작성수준에서 달라지는 자료를 구체적으로 안내한다."""
    if group == "1군":
        extra = [row["label"] for row in checklist() if row["levels"] == ["1군"]]
        return ("이 사업장은 1군으로 설정되어 있습니다. 외부 비상대응·지역사회 소통 자료를 추가 제출하세요: "
                + ", ".join(extra) + ". 물질·함량·최대보유량·일일 취급량과 승인 규정 DB를 대조해 작성수준을 확정하세요.")
    if group == "2군":
        return ("이 사업장은 2군으로 설정되어 있습니다. 물질·함량·최대보유량·일일 취급량이 바뀌면 "
                "승인 규정 DB로 작성수준을 다시 판정하고 1군으로 바뀔 경우 외부 비상대응 자료를 추가하세요.")
    return ("이 사업장은 작성수준이 확인되지 않았습니다. 물질별 함량·최대보유량·일일 취급량을 원본에 기재하고 "
            "승인 규정 DB로 1군·2군을 판정하세요. 판정 전에는 두 군의 자료를 함께 준비하세요.")


def guidance_hwpx(group: str = "") -> bytes:
    """일반 한글 프로그램에서 열 수 있는 HWPX 요청서를 생성한다."""
    from hwpx import HwpxDocument
    doc = HwpxDocument.new()
    for line in guidance_text(group).splitlines():
        doc.add_paragraph(line or " ")
    return doc.to_bytes()


def guidance_hwp(group: str = "") -> bytes:
    """실제 HWP 5.0 바이너리 요청서."""
    from .hwp5_binary import from_hwpx
    return from_hwpx(guidance_hwpx(group))
