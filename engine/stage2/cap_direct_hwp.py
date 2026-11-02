"""HWP draft written directly into the supplied HWPX form.

DOCX 초안이 이미 규정서식 값과 서술형을 검증해 작성하므로, 여기서는 사실을 다시
연결하지 않고 완성된 DOCX의 내용을 같은 구조의 HWPX 원본서식으로 옮긴다.
"""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.oxml.ns import qn
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph
from hwpx import HwpxDocument

from .cap_baseline_docx import _is_label_cell, load_cap_baseline_bytes
from .hwp5_binary import from_hwpx

SOURCE = Path(__file__).resolve().parents[2] / 'data/templates/cap/cap_direct_source.hwpx'
SOURCE_SHA256 = '28391863c280d5154bb0d40631505f2ec10bf50a0516d0205a67264e2c039d49'

NARRATIVE_START = '법정서식 기반 검토용 작성본'
# 물질·시나리오마다 표가 늘어나는 서식의 baseline DOCX 표 번호(별지 제7호, 제14호)
REPEATED_FORMS = (16, 26)
# baseline DOCX의 표 하나가 HWPX에서는 표 둘로 나뉜 서식(별지 제14호 3. 보호대상 명세)
SPLIT_FORM = 28
SPLIT_FORM_ROW = 2
BLACK = '#000000'
HP = '{http://www.hancom.co.kr/hwpml/2011/paragraph}'
HH = '{http://www.hancom.co.kr/hwpml/2011/head}'
HC = '{http://www.hancom.co.kr/hwpml/2011/core}'
# 서술형 제목은 원본서식의 별지 소제목 문단·글자 모양을 쓴다(자동 번호가 붙는 개요 스타일 제외).
HEADING_FORMATS = {'Heading 1': ('86', '64'), 'Heading 2': ('86', '94')}


def _norm(text: str) -> str:
    return re.sub(r'\s+', '', text or '')


def _docx_rows(table) -> list[list]:
    """표의 행별 실제 칸. 세로 병합의 이어지는 칸은 HWPX에 없으므로 뺀다."""
    return [[_Cell(tc, table) for tc in tr.tc_lst if tc.vMerge != 'continue'] for tr in table._tbl.tr_lst]


def _signature(row: list) -> tuple:
    return tuple(cell.text.strip() if _is_label_cell(cell) else None for cell in row)


def _row_texts(rows: list[list]) -> list[list[str]]:
    return [[_norm(cell.text) for cell in row] for row in rows]


def _hwp_text(cell) -> str:
    return ''.join(cell.element.itertext())


def _clone_form(doc, table) -> None:
    """별지 표제부터 표까지 복제해 바로 뒤 새 쪽에 둔다(DOCX의 표 복제와 같은 배치)."""
    anchor = table.paragraph.element
    blocks = [anchor]
    sibling = anchor.getprevious()
    while sibling is not None:
        blocks.insert(0, sibling)
        text = ''.join(sibling.itertext())
        if '■' in text and '별지' in text:
            break
        sibling = sibling.getprevious()
    else:
        raise ValueError('HWP 서식의 별지 표제를 찾을 수 없습니다.')
    for index, block in enumerate(blocks):
        clone = deepcopy(block)
        for run in clone.findall(HP + 'run'):
            for control in run.findall(HP + 'secPr') + run.findall(HP + 'ctrl'):
                run.remove(control)
        if index == 0:
            clone.set('pageBreak', '1')
        for offset, tbl in enumerate(clone.iter(HP + 'tbl')):
            tbl.set('id', str(int(tbl.get('id')) + 100000 * (offset + 1) + 7919 * (index + 1)))
        anchor.addnext(clone)
        anchor = clone
    table.paragraph.section.mark_dirty()


def _char_colors(doc) -> dict:
    return {el.get('id'): el.get('textColor') for el in doc.parts.headers[0].element.iter(HH + 'charPr')}


def _shaded_fills(doc) -> set:
    shaded = set()
    for fill in doc.parts.headers[0].element.iter(HH + 'borderFill'):
        for brush in fill.iter(HC + 'winBrush'):
            if brush.get('faceColor') not in (None, 'none', '#FFFFFF'):
                shaded.add(fill.get('id'))
    return shaded


def _write_cell(cell, text: str, row_cells: list, colors: dict, shaded: set) -> None:
    if _norm(_hwp_text(cell)) == _norm(text):
        return
    if cell.element.get('borderFillIDRef') in shaded:
        raise ValueError('규정서식의 색 있는 명칭 칸에 값을 쓰려고 했습니다: ' + _hwp_text(cell)[:60])
    # 원본의 빈칸 일부는 빨강·파랑 글자로 지정되어 있어 회사 값은 같은 행의 검정 글자 모양을 쓴다.
    black = next((run.get('charPrIDRef') for other in row_cells for run in other.element.iter(HP + 'run')
                  if colors.get(run.get('charPrIDRef')) == BLACK), None)
    for run in cell.element.iter(HP + 'run'):
        if black and colors.get(run.get('charPrIDRef')) != BLACK:
            run.set('charPrIDRef', black)
    cell.set_text(text.strip(), preserve_format=True, split_paragraphs='\n' in text.strip())


def _fill_table(table, filled_rows: list[list], blank_rows: list[list], colors: dict, shaded: set) -> None:
    position = 0
    for target, row in enumerate(filled_rows):
        if len(filled_rows) > len(blank_rows) and (
                position >= len(blank_rows) or _signature(row) != _signature(blank_rows[position])):
            # 행을 늘린 표: 바로 위 행의 형식으로 빈 행을 더한다(위쪽 삽입이어야 세로 병합이 함께 늘어난다).
            if not position or _signature(row) != _signature(blank_rows[position - 1]):
                raise ValueError('HWP 서식과 DOCX 초안의 표 구조가 다릅니다.')
            table.insert_rows(target - 1, 1, side='above', blank=True)
        else:
            position += 1
    for target, row in enumerate(filled_rows):
        cells = list(table.rows[target].cells)
        if len(cells) != len(row):
            raise ValueError('HWP 서식과 DOCX 초안의 칸 구성이 다릅니다.')
        for hwp_cell, docx_cell in zip(cells, row):
            _write_cell(hwp_cell, docx_cell.text, cells, colors, shaded)


def _allow_page_split(table) -> None:
    """값으로 길어진 표가 통째로 다음 쪽으로 밀려 제목만 남지 않게 쪽 나눔을 허용한다."""
    if sum(1 for _ in table.paragraph.element.iter(HP + 'tbl')) != 1:
        return
    position = table.element.find(HP + 'pos')
    position.set('treatAsChar', '0')
    position.set('vertRelTo', 'PARA')
    position.set('horzRelTo', 'COLUMN')
    position.set('horzAlign', 'CENTER')
    position.set('vertOffset', '0')
    position.set('horzOffset', '0')
    table.element.set('pageBreak', 'CELL')
    table.paragraph.section.mark_dirty()


def _fix_form_pagination(doc) -> None:
    """원본은 빈 서식 높이로 쪽을 맞췄으므로, 값으로 표가 길어져도 별지가 새 쪽에서 시작하고 소제목이 표와 함께 가게 한다."""
    keep_with_next = set()
    for section in doc.sections:
        previous = None
        for element in list(section.element.findall(HP + 'p')):
            text = ''.join(element.itertext()).strip()
            has_table = element.find('.//' + HP + 'tbl') is not None
            if has_table and previous is not None and re.match(r'\d', ''.join(previous.itertext()).strip()):
                keep_with_next.add(previous.get('paraPrIDRef'))
            if text.startswith('■') and '별지' in text and element.getprevious() is not None:
                element.set('pageBreak', '1')
                sibling = element.getprevious()
                while sibling is not None and not ''.join(sibling.itertext()).strip() and sibling.find('.//' + HP + 'tbl') is None:
                    filler, sibling = sibling, sibling.getprevious()
                    section.element.remove(filler)
            previous = element
        section.mark_dirty()
    header = doc.parts.headers[0]
    for para_pr in header.element.iter(HH + 'paraPr'):
        if para_pr.get('id') in keep_with_next:
            for setting in para_pr.iter(HH + 'breakSetting'):
                setting.set('keepWithNext', '1')
    header.mark_dirty()


def _table_pairs(filled, blank, hwp_tables) -> list[tuple]:
    """(DOCX 작성 행, DOCX 빈 행, HWPX 표) 대응. 서식 복제 수는 DOCX 초안을 따른다."""
    pairs = []
    position = 0
    hwp_index = 0
    for blank_index, blank_table in enumerate(blank.tables):
        repeats = 1 + _repeat_count(filled, blank, blank_index)
        for _ in range(repeats):
            filled_rows = _docx_rows(filled.tables[position])
            blank_rows = _docx_rows(blank_table)
            if blank_index == SPLIT_FORM:
                pairs.append((filled_rows[:SPLIT_FORM_ROW], blank_rows[:SPLIT_FORM_ROW], hwp_tables[hwp_index]))
                pairs.append((filled_rows[SPLIT_FORM_ROW:], blank_rows[SPLIT_FORM_ROW:], hwp_tables[hwp_index + 1]))
                hwp_index += 2
            else:
                pairs.append((filled_rows, blank_rows, hwp_tables[hwp_index]))
                hwp_index += 1
            position += 1
    return pairs


def _repeat_count(filled, blank, blank_index: int) -> int:
    if blank_index not in REPEATED_FORMS:
        return 0
    extra = len(filled.tables) - len(blank.tables)
    if blank_index == REPEATED_FORMS[0]:
        return sum('취급물질의 일반정보' in table.cell(0, 0).text for table in filled.tables) - 1
    return extra - _repeat_count(filled, blank, REPEATED_FORMS[0])


def _body_blocks(document):
    for element in document.element.body.iterchildren():
        if element.tag == qn('w:p'):
            yield Paragraph(element, document)
        elif element.tag == qn('w:tbl'):
            yield Table(element, document)


def _insert_paragraph_after(doc, table, text: str) -> None:
    paragraph = doc.add_paragraph(text, section=table.paragraph.section, style='바탕글')
    table.paragraph.element.addnext(paragraph.element)
    table.paragraph.section.mark_dirty()


def _copy_paragraphs(doc, filled, blank, table_of) -> None:
    """규정서식에 없던 DOCX 문단: 표 뒤 산출 근거와 끝에 붙는 서술형을 옮긴다."""
    known = {paragraph.text.strip() for paragraph in blank.paragraphs}
    table_index = -1
    narrative = False
    page_break = False
    for block in _body_blocks(filled):
        if isinstance(block, Table):
            table_index += 1
            continue
        text = block.text.strip()
        if narrative or text.startswith(NARRATIVE_START):
            narrative = True
            if block._p.xpath('.//w:br[@w:type="page"]'):
                page_break = True
            if not text:
                continue
            options = {'pageBreak': '1'} if page_break or text.startswith(NARRATIVE_START) else {}
            para_pr, char_pr = HEADING_FORMATS.get(block.style.name, (None, None))
            doc.add_paragraph(text, section_index=-1, style='바탕글', para_pr_id_ref=para_pr,
                              char_pr_id_ref=char_pr, **options)
            page_break = False
        elif text and text not in known:
            _insert_paragraph_after(doc, table_of[table_index], text)


def build_hwp_draft(docx: bytes) -> bytes:
    """완성된 DOCX 초안의 규정서식 값과 서술형을 HWP 원본서식에 작성한다."""
    source = SOURCE.read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('HWPX 원본서식이 변경되었습니다.')
    doc = HwpxDocument.open(source)
    filled = Document(BytesIO(docx))
    blank = Document(BytesIO(load_cap_baseline_bytes()))
    colors = _char_colors(doc)
    shaded = _shaded_fills(doc)

    # 뒤 서식부터 복제해야 앞 서식의 표 번호가 밀리지 않는다.
    for blank_index in reversed(REPEATED_FORMS):
        for _ in range(_repeat_count(filled, blank, blank_index)):
            _clone_form(doc, doc.tables[blank_index])
    pairs = _table_pairs(filled, blank, list(doc.tables))

    for filled_rows, blank_rows, table in pairs:
        _fill_table(table, filled_rows, blank_rows, colors, shaded)
        if _row_texts(filled_rows) != _row_texts(blank_rows):
            _allow_page_split(table)

    table_of = _tables_by_filled_position(pairs, blank, filled)
    _copy_paragraphs(doc, filled, blank, table_of)
    _fix_form_pagination(doc)
    return from_hwpx(doc.to_bytes())


def _tables_by_filled_position(pairs, blank, filled) -> list:
    """DOCX 표 순번 → 그 표 뒤 문단을 붙일 HWPX 표."""
    tables = []
    index = 0
    for blank_index in range(len(blank.tables)):
        for _ in range(1 + _repeat_count(filled, blank, blank_index)):
            if blank_index == SPLIT_FORM:
                index += 1  # 뒤쪽 표가 문단에 가깝다.
            tables.append(pairs[index][2])
            index += 1
    return tables
