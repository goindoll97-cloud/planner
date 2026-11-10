"""One-off 260409 CAP template conversion; preserve only the statutory 별지 pages."""
from __future__ import annotations

import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data" / "templates" / "cap"
OLD_META = FOLDER / "cap_statutory_forms_baseline.json"
NEW_META = FOLDER / "cap_statutory_forms_260409.json"
NEW_DOCX = FOLDER / "cap_statutory_forms_260409.docx"
parts = sorted(FOLDER.glob("cap_statutory_forms_baseline.docx.b64.*"))
if not parts or not OLD_META.exists():
    raise RuntimeError("260409 기존 보관본이 없어 안전하게 변환할 수 없습니다.")
old_meta = json.loads(OLD_META.read_text(encoding="utf-8"))
legacy = b"".join(base64.b64decode("".join(p.read_text(encoding="ascii").split()), validate=True) for p in parts)
if sha256(legacy).hexdigest() != old_meta["sha256"]:
    raise ValueError("이전 서식 데이터의 SHA-256이 기존 등록값과 다릅니다.")
doc = Document(BytesIO(legacy))
if len(doc.tables) != 44:
    raise ValueError("이전 별표+별지 문서 표 수가 예상과 다릅니다.")
body = doc.element.body

def item_text(element):
    return "".join(element.xpath(".//w:t/text()"))

first = next((i for i, e in enumerate(body) if e.tag == qn("w:p") and item_text(e).strip() == "[별표 1]"), None)
annex = next((i for i, e in enumerate(body) if e.tag == qn("w:p") and
              "■" in item_text(e) and "별지 제1호서식" in item_text(e)), None)
if first is None or annex is None or annex <= first:
    raise ValueError("별표 및 제1호서식 본문 경계 확인 실패")
previous_reference = list(body)[first:annex]
if sum(x.tag == qn("w:tbl") for x in previous_reference) != 6:
    raise ValueError("삭제할 이전 별표 표 6개를 특정하지 못했습니다.")
for element in previous_reference:
    body.remove(element)
if len(doc.tables) != 38:
    raise ValueError("260409 별지 전용 구조(38개 표)가 생성되지 않았습니다.")
paragraphs = "\n".join(p.text for p in doc.paragraphs)
missing = [value for value in old_meta["required_markers"] if value not in paragraphs]
if missing:
    raise ValueError("필수 규정서식 명칭 누락: " + ", ".join(missing))
buf = BytesIO()
doc.save(buf)
content = buf.getvalue()
if len(Document(BytesIO(content)).tables) != 38:
    raise ValueError("260409 DOCX 재검증 실패")
NEW_DOCX.write_bytes(content)
meta = dict(old_meta)
meta.update(
    schema_version="cap-statutory-form-layout-baseline-v2",
    template_file=NEW_DOCX.name,
    encoding="binary",
    sha256=sha256(content).hexdigest(),
    required_table_count=38,
    source_description=(
        "260409 법정 별지 전용 작성서식. 260409로 등록된 이전 원본에서 "
        "별표 1~4 본문만 제외하여 별지 본문 표·셀 서식을 유지함. "
        "사용자가 제공한 별지 전용 DOCX와 바이트가 동일한 것은 아님."
    ),
    source_document_name="「화학사고예방관리계획서 작성 등에 관한 규정」 일부 개정_별표, 별지 서식만_260409.docx",
    source_document_sha256="6491a1648b37f96b482f4a529ee8dd0b7be93951324556fcdbce9e58d5c42aa8",
)
NEW_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
for part in parts:
    part.unlink()
OLD_META.unlink()
print(f"260409 별지 38표 생성 {len(content)} bytes sha256={meta['sha256']}; 이전 기준서식 삭제")
