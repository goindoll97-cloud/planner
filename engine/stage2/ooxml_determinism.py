from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo


FIXED_ZIP_DATETIME = (1980, 1, 1, 0, 0, 0)
_REQUIRED_DOCX_MEMBERS = {
    "[Content_Types].xml",
    "word/document.xml",
}


def canonicalize_docx_zip(data: bytes) -> bytes:
    """Return a deterministic DOCX ZIP representation without changing member bytes.

    OOXML documents are ZIP containers. python-docx may write different ZIP
    entry timestamps on otherwise identical saves, which changes the outer file
    SHA-256. For statutory-output provenance we need the same confirmed document
    content to produce the same bytes, so entry order and ZIP metadata are
    normalized while each member payload is preserved byte-for-byte.
    """

    if not isinstance(data, (bytes, bytearray)) or not data:
        raise ValueError("DOCX bytes가 비어 있어 재현성 정규화를 수행할 수 없습니다.")

    try:
        with ZipFile(BytesIO(bytes(data)), "r") as source:
            infos = source.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("DOCX ZIP에 중복 entry가 있어 재현성 정규화를 중단했습니다.")
            missing = sorted(_REQUIRED_DOCX_MEMBERS.difference(names))
            if missing:
                raise ValueError(
                    "DOCX 필수 OOXML entry가 없어 재현성 정규화를 중단했습니다: "
                    + ", ".join(missing)
                )
            entries = [
                (info.filename, source.read(info), info.is_dir())
                for info in infos
            ]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"유효한 DOCX ZIP을 읽지 못했습니다: {exc}") from exc

    out = BytesIO()
    with ZipFile(
        out,
        "w",
        compression=ZIP_DEFLATED,
        compresslevel=9,
        strict_timestamps=True,
    ) as target:
        for name, payload, is_dir in sorted(entries, key=lambda item: item[0]):
            info = ZipInfo(filename=name, date_time=FIXED_ZIP_DATETIME)
            info.create_system = 0
            info.comment = b""
            info.extra = b""
            if is_dir:
                info.compress_type = ZIP_STORED
                info.external_attr = 0x10
                target.writestr(info, b"", compress_type=ZIP_STORED)
            else:
                info.compress_type = ZIP_DEFLATED
                info.external_attr = 0
                target.writestr(
                    info,
                    payload,
                    compress_type=ZIP_DEFLATED,
                    compresslevel=9,
                )
    return out.getvalue()
