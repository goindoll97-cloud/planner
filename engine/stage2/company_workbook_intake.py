"""회사 작성용 엑셀 한 파일의 검사와 최신본 교체. 실패한 파일은 적용하지 않는다."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
from math import isfinite
from zipfile import ZipFile, BadZipFile

from openpyxl import load_workbook

from . import cap_upload_template as tpl, cap_fact_catalog as cat, evidence_workspace as ew

KEY = 'workspace.company_workbook'
HISTORY_KEY = 'workspace.company_workbook_history'


class WorkbookFormatError(ValueError):
    def __init__(self, issues):
        super().__init__('회사 작성용 엑셀 양식의 시트와 항목 이름을 확인해 주세요.')
        self.issues = issues


# ---------------------------------------------------------------------------
# 신입사원용 가상 회사 파일(2행 작성 요령·3행 예시·4행부터 입력)을 회사 양식 구조로 바꿔 읽는다.
TRAINING_MARK = '행 안내'          # 표 시트 맨 끝 열 머리글
TRAINING_FIRST_ROW = 4             # 2행 요령·3행 예시는 사실 추출·계산·초안에서 제외
TRAINING_RENAMED = {               # 회사 양식 열 이름 → 연습 파일 열 이름
    '폭발한계 하한': '폭발한계 하한(%)', '폭발한계 상한': '폭발한계 상한(%)', '증기압': '증기압(mmHg)',
    '경보 설정값': '경보 설정값 1차(H)', '설정압력': '설정압력(MPa)',
    '보호기기 운전압력': '(자동) 보호기기 운전압력(MPa)', '보호기기 설계압력': '(자동) 보호기기 설계압력(MPa)',
}
# 회사 양식의 사업장 정보 항목 중 연습 파일에서 별지 16호 표 시트로 옮긴 것: (시트, [열], 구분자)
TRAINING_MOVED = {
    '지역사회 소통 대상': ('별지16-6-2 지역사회소통', ['참석 대상'], ', '),
    '지역사회 소통 방법': ('별지16-6-2 지역사회소통', ['종류', '소통방법'], ', '),
    '지역사회 소통 주기': ('별지16-6-2 지역사회소통', ['일정'], ', '),
    '지역사회 소통 담당·장소': ('별지16-6-2 지역사회소통', ['장소'], ', '),
    '주민 경보 방법': ('별지16-7-1 대피경보', ['대상 명칭', '대피경보 방법'], ', '),
    '고지 대상': ('별지16-10 지역사회고지', ['고지 대상 목록'], ', '),
    '고지 방법': ('별지16-10 지역사회고지', ['고지 방법'], ', '),
    '고지 내용': ('별지16-10 지역사회고지', ['고지 내용'], ', '),
    '지역사회 고지 일정·담당자': ('별지16-10 지역사회고지', ['고지 예정 시기', '담당자'], ', '),
    '응급의료기관·전화·이송 방법': ('별지16-8 응급의료', ['병원명', '주소', '전화번호', '이송 방법'], ', '),
    '대피장소별 위치·수용인원·연락처': ('별지16-9 대피장소', ['대피장소(구체적 위치)', '수용 인원(명)', '사업장으로부터 거리(m)', '연락처'], ', '),
    '대피 장소': ('별지16-9 대피장소', ['대피장소(구체적 위치)'], ', '),
}
# 최소 사실 입력형 파일: 표 시트마다 1행 머리글·2행 작성 예시·3행부터 입력, 맨 끝 열은 작성 안내.
# 예시 열이 없고 2행 안내 칸이 아래 문구로 시작한다. 도면·이미지는 사람이 따로 첨부하므로
# ‘첨부 도면’ 같은 양식 밖 시트는 읽지 않는다.
MINIMAL_FIRST_ROW = 3
MINIMAL_MARK = '◀ 2행은 작성 예시'


def _layout(book):
    """(안내 열 머리글, 첫 입력 행) 또는 회사 양식 그대로면 None."""
    for ws in book.worksheets:
        if ws.title in (tpl.SITE_SHEET, tpl.HELP_SHEET) or not ws.max_column:
            continue
        last = ws.cell(1, ws.max_column).value
        if last == TRAINING_MARK:
            return TRAINING_MARK, TRAINING_FIRST_ROW
        if (last == tpl.GUIDANCE_HEADER and ws.max_column > 1
                and ws.cell(1, ws.max_column - 1).value != tpl.EXAMPLE_HEADER
                and str(ws.cell(2, ws.max_column).value or '').startswith(MINIMAL_MARK)):
            return tpl.GUIDANCE_HEADER, MINIMAL_FIRST_ROW
    return None


def is_training_layout(book):
    return _layout(book) is not None


def _training_rows(ws, with_row=False, layout=(TRAINING_MARK, TRAINING_FIRST_ROW)):
    mark, first_row = layout
    headers = {c.value: c.column for c in ws[1] if c.value}
    for row in range(first_row, ws.max_row + 1):
        values = {h: ws.cell(row, col).value for h, col in headers.items() if h != mark}
        if any(v not in (None, '') for v in values.values()):
            yield (row, headers, values) if with_row else values


def _from_training_layout(content):
    """연습 파일을 빈 회사 양식에 옮겨 담은 bytes와 위치표({(시트, 옮긴 칸): 연습 파일 칸}).

    예시 행·자동 점검 열·추가 시트는 옮기지 않는다. 오류는 위치표로 연습 파일의 실제 칸을 알린다.
    """
    from openpyxl.utils import get_column_letter as col_letter
    where = {}
    src = load_workbook(BytesIO(content), data_only=True)
    layout = _layout(src) or (TRAINING_MARK, TRAINING_FIRST_ROW)
    out = load_workbook(BytesIO(tpl.build_company()))
    site = {str(r[0].value): r[1].value for r in src[tpl.SITE_SHEET].iter_rows(min_row=2) if r[0].value}
    site_rows = {str(r[0].value): r[0].row for r in src[tpl.SITE_SHEET].iter_rows(min_row=2) if r[0].value}
    for row in range(2, out[tpl.SITE_SHEET].max_row + 1):
        label = out[tpl.SITE_SHEET].cell(row, 1).value
        src_label = '주소' if label == '우편번호/주소' and label not in site_rows else label
        if src_label in site_rows:
            where[(tpl.SITE_SHEET, f'A{row}')] = f'A{site_rows[src_label]}'
            where[(tpl.SITE_SHEET, f'B{row}')] = f'B{site_rows[src_label]}'
        if label == '우편번호/주소' and site.get(label) not in (None, ''):
            value = site[label]
        elif label == '우편번호/주소':
            zip_code = str(site.get('우편번호') or '').strip()
            value = ' '.join(x for x in (zip_code if zip_code.strip('0') else '', str(site.get('주소') or '').strip()) if x)
        elif label in TRAINING_MOVED and site.get(label) in (None, ''):
            title, cols, sep = TRAINING_MOVED[label]
            parts = [' '.join(str(r[c]) for c in cols if r.get(c) not in (None, ''))
                     for r in (_training_rows(src[title], layout=layout) if title in src.sheetnames else [])]
            value = sep.join(p for p in parts if p) or None
        else:
            value = site.get(label)
        out[tpl.SITE_SHEET].cell(row, 2, value)
    for ws in out.worksheets:
        if ws.title in (tpl.SITE_SHEET, tpl.HELP_SHEET) or ws.title not in src.sheetnames:
            continue
        headers = [c.value for c in ws[1]]
        inputs = [h for h in headers[:-2] if h]
        for row, (src_row, src_cols, values) in enumerate(_training_rows(src[ws.title], with_row=True, layout=layout), 2):
            for col, header in enumerate(inputs, 1):
                name = TRAINING_RENAMED.get(header, header)
                src_col = src_cols.get(name, src_cols.get(header, col))
                where[(ws.title, f'{col_letter(col)}{row}')] = f'{col_letter(src_col)}{src_row}'
                value = values.get(name, values.get(header))
                if value not in (None, ''):
                    ws.cell(row, col, value)
    out.properties.identifier = src.properties.identifier or ''
    out.properties.title = src.properties.title
    out.properties.description = src.properties.description
    buffer = BytesIO()
    out.save(buffer)
    return buffer.getvalue(), where


def current(project):
    record = project.get_field(KEY)
    return record.value if record else None


def project_for_upload(selected, name, content):
    """엑셀의 사업장명으로 저장 대상을 찾는다. 적용에 성공하기 전에는 저장하지 않는다."""
    sanitized, _ = inspect(content, name)
    book = load_workbook(BytesIO(sanitized))
    sheet = book[tpl.SITE_SHEET]
    values = {str(row[0].value): row[1].value for row in sheet.iter_rows(min_row=2)}
    company = str(values.get('사업장명') or '').strip()
    if not company:
        raise WorkbookFormatError([{'파일·위치': name + ' · 사업장 정보', '항목': '사업장명',
            '확인된 문제': '엑셀에 사업장명이 없습니다.', '수정 요청': '사업장명 값을 채워 다시 올려 주세요.'}])
    from .storage import list_projects, load_project
    from .direct_template import create_direct_cap_project
    if selected.company_name == company:
        target = deepcopy(selected)
    else:
        matches = [p for p in list_projects() if p['company_name'] == company]
        if len(matches) > 1:
            raise WorkbookFormatError([{'파일·위치': name, '항목': '사업장 선택',
                '확인된 문제': '같은 이름의 사업장이 여러 개 있습니다.',
                '수정 요청': '화면에서 적용할 사업장을 선택한 뒤 다시 올려 주세요.'}])
        target = load_project(matches[0]['project_id']) if matches else create_direct_cap_project(company)
    from . import demo_company_workbook as demo
    training_copy = (
        tpl.HELP_SHEET in book.sheetnames
        and book[tpl.SITE_SHEET].cell(1, 3).value == tpl.EXAMPLE_HEADER
        and book[tpl.HELP_SHEET].cell(1, 1).value == "시트"
    )
    if company == demo.COMPANY and (book.properties.identifier in (demo.IDENTIFIER, *demo.LEGACY_IDENTIFIERS) or training_copy):
        target.cap_group = '1군'
        if demo.NOTICE not in target.notes:
            target.notes.append(demo.NOTICE)
    return target


def inspect(content, name, group=''):
    """입력 오류는 위치와 함께 반환하고, 오류 셀은 자동 작성에서 제외한다."""
    issues = []
    where = {}
    def issue(sheet, cell, label, reason, fix):
        cell = where.get((sheet, cell), cell)
        issues.append({'파일·위치': f'{name} · {sheet}!{cell}', '항목': label,
                       '확인된 문제': reason, '수정 요청': fix})
    if not name.lower().endswith('.xlsx') or len(content) > 20 * 1024 * 1024:
        raise WorkbookFormatError([{'파일·위치': name, '항목': '파일 형식', '확인된 문제': '회사 작성용 .xlsx 파일(20MB 이하)이 필요합니다.', '수정 요청': '화면에서 양식을 내려받아 작성해 주세요.'}])
    try:
        with ZipFile(BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist()) > ew.MAX_UNZIPPED:
                raise ValueError('엑셀 압축 해제 크기가 너무 큽니다.')
        book = load_workbook(BytesIO(content))
        if is_training_layout(book):
            content, where = _from_training_layout(content)
            book = load_workbook(BytesIO(content))
    except (BadZipFile, ValueError, OSError, KeyError) as exc:
        raise WorkbookFormatError([{'파일·위치': name, '항목': '엑셀 읽기', '확인된 문제': '파일을 열지 못했습니다.', '수정 요청': 'Excel에서 .xlsx로 다시 저장한 뒤 올려 주세요.'}]) from exc
    expected = load_workbook(BytesIO(tpl.build_company()))
    legacy = load_workbook(BytesIO(tpl.build_company(include_scenario_sheets=True)))
    scenario_title, target_title = tpl.ENTITY_SHEETS['scenario'], tpl.ENTITY_SHEETS['target']
    # Two valid GIS-enriched layouts: the old scenario sheet with location
    # columns and the current scenario sheet plus a map-generated target sheet.
    old_scenario_headers = (
        scenario_title in book.sheetnames
        and [c.value for c in book[scenario_title][1]][:legacy[scenario_title].max_column - 2]
        == [c.value for c in legacy[scenario_title][1]][:legacy[scenario_title].max_column - 2]
    )
    if old_scenario_headers:
        expected = legacy
    elif target_title in book.sheetnames:
        expected = load_workbook(BytesIO(tpl.build_company(include_target_sheet=True)))
    optional_sheets = {scenario_title, target_title, tpl.HELP_SHEET}
    for ws in expected:
        if ws.title not in book.sheetnames:
            if ws.title in optional_sheets:
                continue
            issue(ws.title, 'A1', '시트', '필요한 시트가 없습니다.', '빈 시트도 삭제하지 말고 원래 양식에 값을 옮겨 주세요.')
            continue
        actual = book[ws.title]
        if actual.max_row > ew.MAX_ROWS or actual.max_column > ew.MAX_COLUMNS:
            issue(ws.title, 'A1', '표 크기', '읽을 수 있는 행·열 수를 초과했습니다.', '불필요한 빈 행·열을 제거해 주세요.')
            continue
        if ws.title == tpl.HELP_SHEET:
            # The last sheet is documentation. It must never affect facts.
            continue
        input_count = ws.max_column - 2
        for col in range(1, input_count + 1):
            current, expected_title = actual.cell(1, col).value, ws.cell(1, col).value
            # Accept legacy company workbooks that still say SDS.
            if current not in (expected_title, expected_title.replace("MSDS", "SDS")):
                issue(ws.title, actual.cell(1, col).coordinate, '열 이름',
                      '양식의 열 이름이나 순서가 바뀌었습니다.',
                      f'열 제목을 ‘{expected_title}’로 복원해 주세요.')
        example_col = input_count + 1
        if actual.cell(1, example_col).value not in (tpl.EXAMPLE_HEADER, '예시 (입력하지 마세요)'):
            issue(ws.title, actual.cell(1, example_col).coordinate, '예시 열',
                  '회사 입력열 뒤의 예시 열 제목이 바뀌었습니다.', '공식 작성용 엑셀의 예시 열을 유지해 주세요.')
        if actual.cell(1, example_col + 1).value not in (None, tpl.GUIDANCE_HEADER):
            issue(ws.title, actual.cell(1, example_col + 1).coordinate, '작성 안내 열',
                  '작성 안내 열의 머리글이 바뀌었습니다.', '공식 작성용 엑셀의 안내 열을 유지해 주세요.')
        if actual.max_column > input_count + 2 and any(
                actual.cell(r, c).value is not None for r in range(1, actual.max_row + 1)
                for c in range(input_count + 3, actual.max_column + 1)):
            issue(ws.title, 'A1', '추가 열', '양식에 없는 열에 내용이 있습니다.',
                  '내용을 양식의 해당 입력 칸으로 옮겨 주세요.')
    extras = set(book.sheetnames) - set(expected.sheetnames)
    for title in sorted(extras):
        issue(title, 'A1', '추가 시트', '양식에 없는 시트는 읽을 수 없습니다.', '추가 자료를 원래 양식의 해당 입력란에 옮겨 주세요.')
    site = book[tpl.SITE_SHEET] if tpl.SITE_SHEET in book.sheetnames else None
    if site:
        labels = [r[0].value for r in expected[tpl.SITE_SHEET].iter_rows(min_row=2)]
        actual = [site.cell(r, 1).value for r in range(2, max(site.max_row, len(labels) + 1) + 1)]
        if actual[:len(labels)] != labels or any(v not in (None, '') for v in actual[len(labels):]):
            issue(tpl.SITE_SHEET, 'A2', '작성 항목', '항목이 삭제·변경되거나 순서가 바뀌었습니다.', '양식을 다시 내려받아 값 열에만 내용을 옮겨 주세요.')
    if issues:
        raise WorkbookFormatError(issues)
    wanted = tpl.company_columns()

    def check(ws, row, col, item, label=None):
        cell = ws.cell(row, col)
        value = cell.value
        label = label or item.name
        if group and group not in item.groups:
            cell.value = None
            return
        missing = value is None or str(value).strip() in {'', '미확인', '확인 필요', '[확인 필요]'}
        reason = ''
        if missing:
            # Initial fact-only files deliberately omit calculated outputs and
            # the separate GIS review checklist; these are NOT company facts.
            deferred = tpl.minimal_excludes(item)
            if (item.required and not deferred) or value not in (None, '') or item.id == 'cap-components.4':
                reason = '필요한 값이 비어 있거나 아직 확인되지 않았습니다.'
        elif cell.data_type == 'f':
            reason = '수식 대신 확인한 값을 입력해 주세요.'
        elif item.format == 'choice' and str(value).strip() not in item.options:
            reason = '선택 가능한 값: ' + ' / '.join(item.options)
        elif item.evidence_field == 'company_name' and str(value).strip() == '':
            reason = '사업장명을 입력해 주세요.'
        else:
            raw = str(value).strip()
            field = item.evidence_field
            if field in ew.CORE_FIELDS:
                normalized = ew.normalize_value(field, raw, item.template_header)
                reason = ew.value_problem(field, normalized) or ''
                if isinstance(normalized, (int, float)) and not isfinite(normalized):
                    reason = '유한한 숫자를 입력해 주세요.'
            elif (item.format == 'number' or '(%)' in item.template_header) and not missing:
                try:
                    number = float(raw.replace(',', '').removesuffix('%'))
                    if not isfinite(number):
                        raise ValueError()
                    if item.id == 'site.dike_required_ratio' and number < 0:
                        reason = '필요용량 비율은 0 이상으로 입력해 주세요.'
                    elif item.id != 'site.dike_required_ratio' and (item.unit == '%' or '(%)' in item.template_header) and not 0 <= number <= 100:
                        reason = '백분율은 0~100 범위로 입력해 주세요.'
                except ValueError:
                    reason = '숫자만 입력하고 단위는 열 제목에 맞춰 주세요.'
            if 'CAS' in item.template_header and raw and not ew.cas_valid(raw):
                reason = 'CAS 번호의 형식 또는 검증 숫자가 맞지 않습니다.'
        if reason:
            issue(ws.title, cell.coordinate, label, reason, '예시·단위를 확인해 이 칸을 수정하고 엑셀 전체를 다시 올려 주세요.')
            cell.value = None
        elif missing:
            cell.value = None

    for row, item in enumerate(wanted['site'], 2):
        check(site, row, 2, item)
    table_items = {}
    for kind, title in tpl.ENTITY_SHEETS.items():
        items = wanted[kind]
        entity_kind = 'facility' if kind == 'scenario' else kind
        identity = next(i for i in cat.facts(kinds=[entity_kind]) if i.identifier)
        table_items[title] = [identity] + [i for i in items if not i.identifier]
    table_items.update({tpl.sheet_title(t): items for t, items in wanted['tables'].items()})
    for title, items in table_items.items():
        if title not in book.sheetnames:
            continue
        ws = book[title]
        by_header = {tpl.display_header(i.template_header): i for i in items}
        by_header.update({i.template_header: i for i in items})
        guide_present = ws.cell(1, ws.max_column).value == tpl.GUIDANCE_HEADER
        headers = [c.value for c in ws[1]][:-2 if guide_present else -1]
        active = []
        seen = {}
        for row in range(2, ws.max_row + 1):
            if not any(ws.cell(row, c).value not in (None, '') for c in range(1, len(headers) + 1)):
                continue
            active.append(row)
            ids = tuple(str(ws.cell(row, c).value or '').strip() for c, h in enumerate(headers, 1) if by_header[h].identifier)
            if not all(ids):
                issue(title, f'A{row}', '번호·식별정보', '대상을 구별할 번호·식별정보가 빠졌습니다.', '이 행의 번호·식별정보를 채워 주세요. 이 행은 아직 작성에 사용하지 않습니다.')
                for col in range(1, len(headers) + 1):
                    ws.cell(row, col).value = None
                continue
            if ids in seen:
                issue(title, f'A{row}', '번호·식별정보', f'{seen[ids]}행과 같은 대상이 중복되었습니다.', '한 대상은 한 행으로 정리해 주세요.')
            seen[ids] = row
            for col, header in enumerate(headers, 1):
                check(ws, row, col, by_header[header])
        if not active and title in {'설비', '물질'}:
            issue(title, 'A2', title + ' 목록', '입력된 목록이 없습니다.', '사업장의 설비·취급 제품을 한 행에 하나씩 입력해 주세요.')
    facilities = {str(book['설비'].cell(r, 1).value).strip() for r in range(2, book['설비'].max_row + 1)
                  if book['설비'].cell(r, 1).value is not None}
    for title, header in [('사고시나리오 검토', '설비번호'), ('안전밸브', '보호대상 설비번호')]:
        if title not in book.sheetnames:
            continue
        ws = book[title]
        col = next(c.column for c in ws[1] if c.value == header)
        for row in range(2, ws.max_row + 1):
            value = ws.cell(row, col).value
            if value is not None and str(value).strip() not in facilities:
                issue(title, ws.cell(row, col).coordinate, header, '설비 시트에 없는 설비번호입니다.',
                      '설비 시트의 번호와 일치시키거나 누락된 설비를 추가해 주세요.')
                for c in range(1, ws.max_column):
                    ws.cell(row, c).value = None
    products = {str(book['물질'].cell(r, 1).value).strip() for r in range(2, book['물질'].max_row + 1)
                if book['물질'].cell(r, 1).value is not None}
    components = book['혼합제품 구성성분']
    totals = {}
    for row in range(2, components.max_row + 1):
        code = components.cell(row, 1).value
        if code is None:
            continue
        code = str(code).strip()
        if code not in products:
            issue(components.title, f'A{row}', '혼합제품 코드', '물질 시트에 없는 제품코드입니다.', '물질 시트와 같은 제품코드를 사용해 주세요.')
            for col in range(1, components.max_column):
                components.cell(row, col).value = None
            continue
        value = components.cell(row, 5).value
        if value is not None:
            totals.setdefault(code, []).append((row, float(str(value).replace(',', '').removesuffix('%'))))
    for code, parts in totals.items():
        if sum(value for _, value in parts) > 100.00001:
            for row, _ in parts:
                issue(components.title, f'E{row}', '구성성분 함량(%)', f'{code}의 성분 함량 합계가 100%를 넘습니다.', '제품 SDS 제3항을 확인해 성분별 함량을 수정해 주세요.')
                components.cell(row, 5).value = None
    out = BytesIO()
    book.save(out)
    return out.getvalue(), issues


def apply(project, name, content):
    """읽기에 성공한 최신 엑셀을 원자적으로 적용. 이름이 달라도 이전본과 섞지 않는다."""
    sanitized, issues = inspect(content, name, project.cap_group)
    digest = sha256(content).hexdigest()
    previous = current(project)
    if previous and previous['sha256'] == digest:
        return False
    work = deepcopy(project)
    managed = {k for i in cat.facts(docs=['CAP']) for k in (i.field_key, *(t[0] for t in i.targets)) if k and not k.startswith('@')}
    managed.update({'business.company_name', ew.KEY})
    from . import scenario_pipeline
    managed.update(scenario_pipeline.OUTPUT_KEYS)
    from . import ai_drafting as drafting
    removed = {}
    for key, record in list(work.fields.items()):
        if ((key in managed and key != 'business.company_name')
                or record.note.startswith(ew.LINK_NOTE) or drafting.is_replaceable_draft(record)):
            removed[key] = deepcopy(record.to_dict())
            del work.fields[key]
    history = work.get_field(HISTORY_KEY)
    snapshots = deepcopy(history.value) if history else []
    if removed or previous:
        snapshots.append({'previous': previous, 'fields': removed})
    work.set_field(HISTORY_KEY, '엑셀 적용 전 자료 보존', snapshots, 'HOLD')
    work.__dict__.pop('_evidence_memo', None)
    ew.ingest(work, name, sanitized, 'mixed')
    identity = next((f for f in ew.graph_facts(work) if f['field'] == 'company_name'), None)
    if identity and str(identity['value']).strip() != project.company_name.strip():
        raise WorkbookFormatError([{'파일·위치': f"{name} · {identity['location']}", '항목': '사업장명',
            '확인된 문제': '엑셀의 사업장명과 현재 선택한 사업장이 다릅니다.',
            '수정 요청': '맞는 사업장을 선택하거나 엑셀의 사업장명을 확인한 뒤 다시 올려 주세요.'}])
    # 실제 원본의 해시로 출처를 연결한다. 원본은 저장소에 별도로 보존한다.
    data = ew.graph(work)
    data['documents'][0]['sha256'] = digest
    for fact in data['facts']:
        fact['sha256'] = digest
    ew._store(work, data)
    work.set_field(KEY, '최신 회사 작성용 엑셀', {'name': name, 'sha256': digest,
        'uploaded_at': datetime.now(timezone.utc).isoformat(), 'issues': issues}, 'FILE_READ')
    if ew.catalog_preview(work) or ew.publishing_plan(work):
        ew.publish(work, replace_existing=True)
    _keep_map_survey(work, removed)
    project.fields = work.fields
    project.__dict__.pop('_evidence_memo', None)
    return True


MAP_INPUT_COLUMNS = ('경계까지 거리(m)', '사고원점 좌표')


def _keep_map_survey(work, removed):
    """지도로 확인한 값은 회사 엑셀에 없으므로, 엑셀을 고쳐 다시 올려도 지우지 않고 되살린다."""
    from .project import FieldRecord
    for key in (ew.SURVEY_KEY, ew.SURVEY_REVIEW_KEY):
        if key in removed and work.get_field(key) is None:
            work.fields[key] = FieldRecord.from_dict(removed[key])
    old = removed.get(ew.SCENARIO_INPUT_KEY)
    if not old or not isinstance(old.get('value'), list):
        return
    kept = {str(r.get('설비번호', '')).strip(): {c: r[c] for c in MAP_INPUT_COLUMNS if r.get(c) not in (None, '')}
            for r in old['value'] if isinstance(r, dict)}
    kept = {k: v for k, v in kept.items() if k and v}
    record = work.get_field(ew.SCENARIO_INPUT_KEY)
    rows = [dict(r) for r in record.value] if record is not None and isinstance(record.value, list) else []
    seen = {str(r.get('설비번호', '')).strip() for r in rows}
    for row in rows:
        for column, value in kept.get(str(row.get('설비번호', '')).strip(), {}).items():
            row.setdefault(column, value)
    rows += [{'설비번호': tag, **values} for tag, values in kept.items() if tag not in seen]
    if rows:
        work.set_field(ew.SCENARIO_INPUT_KEY, old.get('label') or '사고시나리오 설비별 입력', rows, old.get('status') or 'HOLD')


def corrections(project):
    state = current(project)
    if not state:
        return []
    rows = list(state['issues'])
    for item in ew.review_queue(project):
        if item['kind'] != '충돌':
            continue
        facts = item['slot']['facts']
        rows.append({'파일·위치': ' / '.join(f"{state['name']} · {f['location']}" for f in facts),
                     '항목': ew.LABELS[item['field']], '확인된 문제': '같은 대상에 서로 다른 값이 적혀 있습니다.',
                     '수정 요청': '엑셀에서 같은 대상의 값을 일치시키고 다시 올려 주세요.'})
    for group in ew.problems(project):
        for fact in group['facts']:
            entry = {'파일·위치': f"{state['name']} · {fact['location']}", '항목': ew.LABELS[group['field']],
                     '확인된 문제': group['reason'], '수정 요청': '엑셀에서 값을 수정한 뒤 다시 올려 주세요.'}
            if entry not in rows:
                rows.append(entry)
    return rows
