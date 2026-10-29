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


def current(project):
    record = project.get_field(KEY)
    return record.value if record else None


def inspect(content, name, group=''):
    """입력 오류는 위치와 함께 반환하고, 오류 셀은 자동 작성에서 제외한다."""
    issues = []
    def issue(sheet, cell, label, reason, fix):
        issues.append({'파일·위치': f'{name} · {sheet}!{cell}', '항목': label,
                       '확인된 문제': reason, '수정 요청': fix})
    if not name.lower().endswith('.xlsx') or len(content) > 20 * 1024 * 1024:
        raise WorkbookFormatError([{'파일·위치': name, '항목': '파일 형식', '확인된 문제': '회사 작성용 .xlsx 파일(20MB 이하)이 필요합니다.', '수정 요청': '화면에서 양식을 내려받아 작성해 주세요.'}])
    try:
        with ZipFile(BytesIO(content)) as z:
            if sum(i.file_size for i in z.infolist()) > ew.MAX_UNZIPPED:
                raise ValueError('엑셀 압축 해제 크기가 너무 큽니다.')
        book = load_workbook(BytesIO(content))
    except (BadZipFile, ValueError, OSError, KeyError) as exc:
        raise WorkbookFormatError([{'파일·위치': name, '항목': '엑셀 읽기', '확인된 문제': '파일을 열지 못했습니다.', '수정 요청': 'Excel에서 .xlsx로 다시 저장한 뒤 올려 주세요.'}]) from exc
    expected = load_workbook(BytesIO(tpl.build_company()))
    for ws in expected:
        if ws.title not in book.sheetnames:
            issue(ws.title, 'A1', '시트', '필요한 시트가 없습니다.', '빈 시트도 삭제하지 말고 원래 양식에 값을 옮겨 주세요.')
            continue
        actual = book[ws.title]
        if actual.max_row > ew.MAX_ROWS or actual.max_column > ew.MAX_COLUMNS:
            issue(ws.title, 'A1', '표 크기', '읽을 수 있는 행·열 수를 초과했습니다.', '불필요한 빈 행·열을 제거해 주세요.')
            continue
        for col in range(1, ws.max_column + 1):
            if actual.cell(1, col).value != ws.cell(1, col).value:
                issue(ws.title, actual.cell(1, col).coordinate, '열 이름', '양식의 열 이름이나 순서가 바뀌었습니다.', f'열 제목을 ‘{ws.cell(1, col).value}’로 복원해 주세요.')
        if actual.max_column > ws.max_column and any(
                actual.cell(r, c).value is not None for r in range(1, actual.max_row + 1)
                for c in range(ws.max_column + 1, actual.max_column + 1)):
            issue(ws.title, 'A1', '추가 열', '양식에 없는 열에 내용이 있습니다.', '내용을 양식의 해당 입력 칸으로 옮겨 주세요.')
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
            if item.required or value not in (None, '') or item.id == 'cap-components.4':
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
                    if (item.unit == '%' or '(%)' in item.template_header) and not 0 <= number <= 100:
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
        ws = book[title]
        by_header = {i.template_header: i for i in items}
        headers = [c.value for c in ws[1]][:-1]
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
    removed = {}
    for key, record in list(work.fields.items()):
        if ((key in managed and key != 'business.company_name')
                or record.note.startswith(ew.LINK_NOTE) or record.status == 'AI_DRAFT'):
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
    project.fields = work.fields
    project.__dict__.pop('_evidence_memo', None)
    return True


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
