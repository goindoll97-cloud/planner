"""회사에 요청할 자료 목록. 작성요건 registry와 동일한 항목을 사용한다."""
from __future__ import annotations

from collections import defaultdict
from io import BytesIO
import os
from pathlib import Path
import re

from .requirements import COMMON_REQUIREMENTS, cap_requirement_specs


START_FORMS = (
    {"key": "cap.intake.form1", "section": "별지 제1호", "label": "작성수준·대상시설 산정 근거",
     "details": "물질별 CAS·함량, 설비별 용량·최대보유량·일일 취급량, 시설구분과 판정 근거",
     "evidence": ["물질목록·제품 SDS", "설비대장·보관계획", "최대보유량·취급량 산정자료"],
     "levels": ["1군", "2군"], "basis": "작성수준 판정과 별지 제1호 입력자료", "pages": (), "required": True},
    {"key": "cap.intake.form2", "section": "별지 제2호", "label": "제출구분·변경사항 근거",
     "details": "신규·변경 제출구분, 사유, 단위공장, 변경 전후 자료(해당 시)",
     "evidence": ["사업장 기본현황", "기존 제출본·변경내역(해당 시)"],
     "levels": ["1군", "2군"], "basis": "제출·변경 정보 입력자료", "pages": (), "required": True},
)


def form_zone(row: dict) -> str:
    """근거에 적힌 별지 번호만 표기한다. 별지 없는 항목에 번호를 추정하지 않는다."""
    if row["key"].startswith("cap.intake.form"):
        return row["section"]
    numbers = sorted({int(n) for n in re.findall(r"별지\s*제\s*(\d+)호", row["basis"])})
    if numbers:
        return "별지 " + "·".join(f"제{n}호" for n in numbers)
    if row["key"].startswith("common."):
        return "공통자료"
    return "별지 번호 없는 작성자료 · " + re.sub(r"^3\.\d+\s*", "", row["section"])


def grouped_checklist() -> list[tuple[str, list[dict]]]:
    """표시 순서: 두 군 공통, 1군 전용, 2군 전용(있을 때만)."""
    rows = list(START_FORMS) + checklist()
    grouped = []
    for label, levels in (("1군·2군 공통", ["1군", "2군"]), ("1군만", ["1군"]), ("2군만", ["2군"])):
        selected = [r for r in rows if r["levels"] == levels]
        if not selected:
            continue
        selected.sort(key=lambda r: (int(re.search(r"제(\d+)호", form_zone(r)).group(1))
                                     if re.search(r"제(\d+)호", form_zone(r)) else 999,
                                     form_zone(r), rows.index(r)))
        grouped.append((label, selected))
    return grouped


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
        from .cap_fact_drafting import input_facts
        facts = input_facts(spec)
        evidence = (["항목·값 표: " + " / ".join(f.template_header for f in facts),
                     "기존 회사자료·연락망 (완성된 계획서가 있으면 선택 제출)"]
                    if facts else list(dict.fromkeys(spec.suggested_evidence)))
        details = ("회사에서 확인할 정보: " + ", ".join(f.template_header for f in facts)
                   + ". 이 정보로 프로그램이 서술형 초안을 작성하고, 로컬 AI로 문장을 다듬습니다. 완성된 계획서는 필수가 아닙니다."
                   if facts else spec.description)
        rows.append({"key": spec.key, "section": spec.section, "label": spec.label + (" 작성용 정보" if facts else ""),
                     "details": details, "evidence": evidence,
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
    for label, rows in grouped_checklist():
        lines.extend([f"[{label}]", ""])
        for row in rows:
            if not drawings and ("도면" in row["section"] or row["key"].startswith("common.pf") or row["key"] == "common.site_plan"):
                continue
            qualifier = " (적용 여부 확인)" if not row["required"] else ""
            lines.append(f"• [{form_zone(row)}] {row['label']}{qualifier}")
            lines.append(f"  필요한 내용: {row['details']}")
            lines.append("  요청할 자료: " + (" / ".join(row["evidence"]) if row["evidence"] else "해당 항목의 회사 보유자료·계산근거·확인기록"))
            if row["basis"]:
                lines.append(f"  작성 참고: {row['basis']}")
            lines.append("")
    lines.extend(["조건이 달라지면 추가 확인", "• 물질·농도·성상·최대보유량·일일 취급량이 바뀌면 작성수준과 대상시설을 다시 판정하세요.",
                  "• 1군은 소통 대상·방법·주기, 협력 기관·내용, 경보 방법·대피 경로·장소를 알려 주세요. 계획서 문장은 프로그램이 작성합니다.",
                  "• 공동비상대응, 타 제도 심사결과 활용, 변경제출 여부는 각 증빙이 있을 때 해당 자료를 추가하세요.",
                  "• 누락 자료는 파일·항목별 보완 요청으로 돌려보내고, 규정 기준표가 없으면 판정 보류로 표시합니다."])
    return "\n".join(lines) + "\n"


def conditional_notice(group: str) -> str:
    """승인된 작성수준에서 달라지는 자료를 구체적으로 안내한다."""
    if group == "1군":
        extra = [row["label"] for row in checklist() if row["levels"] == ["1군"]]
        return ("이 사업장은 1군으로 설정되어 있습니다. 완성된 계획서 대신 서술형 작성에 필요한 단답형 정보를 추가하세요: "
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


def guidance_pdf() -> bytes:
    """한국어 글꼴이 확인된 환경에서만 회사 전달용 PDF를 만든다."""
    from html import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether

    candidates = [os.environ.get("CAP_PDF_FONT_PATH", ""),
                  r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\NanumGothic.ttf",
                  "/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc"]
    font_path = next((Path(p) for p in candidates if p and Path(p).is_file()), None)
    if font_path is None:
        raise RuntimeError("PDF용 한글 글꼴이 없습니다. CAP_PDF_FONT_PATH에 한글 TTF 파일 경로를 설정하세요.")
    pdfmetrics.registerFont(TTFont("CapKorean", str(font_path)))
    style = ParagraphStyle("body-ko", fontName="CapKorean", fontSize=9, leading=12.5, textColor=colors.HexColor("#243142"), wordWrap="CJK")
    title = ParagraphStyle("title-ko", parent=style, fontSize=16, leading=23, spaceAfter=12)
    sub = ParagraphStyle("sub-ko", parent=style, fontSize=12, leading=18, textColor=colors.HexColor("#174d7a"), spaceBefore=14, spaceAfter=5)
    small = ParagraphStyle("small-ko", parent=style, fontSize=8, leading=10.8)
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=48, leftMargin=48, topMargin=45, bottomMargin=45)
    story = [Paragraph("화학사고예방관리계획서 회사자료 준비 목록", title),
             Paragraph("작성수준 판정 전에는 1군·2군 공통자료와 1군 추가자료를 함께 확인하세요. 자료 접수만으로 법정 서식이 완성되지는 않습니다.", style)]
    for label, rows in grouped_checklist():
        story.append(Paragraph(escape(label), sub))
        for row in rows:
            detail = escape(row["details"])
            evidence = escape(" / ".join(row["evidence"]) or "회사 보유자료·계산근거·확인기록")
            story.append(KeepTogether([
                Paragraph(escape(f"[{form_zone(row)}] {row['label']}"), style),
                Paragraph(f"필요한 내용: {detail}", small),
                Paragraph(f"요청할 자료: {evidence}", small), Spacer(1, 5)]))
    story.extend([Paragraph("판정과 추가 확인", sub), Paragraph(
        "물질·농도·성상·최대보유량·일일 취급량이 달라지면 승인된 최신 규정 DB로 작성수준과 대상시설을 다시 판정하세요. "
        "실제 주소의 주민·보호대상·논·하천 등 주변 현황은 지도와 현장을 대조해 확인하세요.", style)])
    doc.build(story)
    return out.getvalue()
