"""Partial HWP draft written directly into the supplied HWPX form."""
from pathlib import Path
from hashlib import sha256

from hwpx import HwpxDocument
from .hwp5_binary import from_hwpx
from . import statutory_report as base

SOURCE = Path(__file__).resolve().parents[2] / 'data/templates/cap/cap_direct_source.hwpx'
SOURCE_SHA256 = '28391863c280d5154bb0d40631505f2ec10bf50a0516d0205a67264e2c039d49'


def build_partial_hwp(project) -> bytes:
    source = SOURCE.read_bytes()
    if sha256(source).hexdigest() != SOURCE_SHA256:
        raise ValueError('HWPX 원본서식이 변경되었습니다.')
    doc = HwpxDocument.open(source)
    table = doc.tables[12]
    if ''.join(table.rows[1].cells[0].element.itertext()).strip() != '사업장명':
        raise ValueError('사업장 일반정보 서식 위치를 확인할 수 없습니다.')
    values = {
        (1, 1): project.company_name or '',
        (2, 1): base._text(project, 'cap.business.unit_plant_name', default=project.site_name or ''),
        (3, 1): base._text(project, 'cap.business.registration_no', default=''),
        (4, 1): base._text(project, 'cap.business.representative', default=''),
        (5, 1): base._text(project, 'business.address', default=''),
        (6, 1): base._text(project, 'cap.business.industrial_complex', default=''),
        (7, 1): base._text(project, 'cap.business.contact', default=''),
        (14, 1): base._text(project, 'cap.business.writer_info', default=''),
        (15, 1): base._text(project, 'cap.business.writer_contact', default=''),
        (15, 3): base._text(project, 'cap.business.writer_email', default=''),
    }
    for (row, col), value in values.items():
        if value:
            table.set_cell_text(row, col, str(value), preserve_format=True)
    return from_hwpx(doc.to_bytes())
