from __future__ import annotations

"""계산·서식의 근거로 쓰는 KOSHA GUIDE 목록, 로컬 원문 캐시, 새 판본 감시.

원문 PDF는 저장소가 아니라 data/runtime/kosha_guides/ 캐시에 둔다(Git 제외). 저장소에는 판본·원문 SHA-256·
추출한 구조화 자료의 위치만 적는다. 새 판본이 공표되면 '재검토 필요'로 알리기만 하고 값을 자동으로 바꾸지 않는다.
"""

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Callable

from . import kosha_guide

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "stage2" / "kosha_guides" / "registry.json"
CACHE_DIR = ROOT / "data" / "runtime" / "kosha_guides"


@dataclass(frozen=True)
class GuideEntry:
    base_number: str
    aliases: tuple[str, ...]
    title: str
    edition: str
    announced: str
    source_sha256: str
    used_by: tuple[str, ...]
    extracted: tuple[str, ...]
    verification: str

    @property
    def year(self) -> int | None:
        found = re.search(r"-(\d{4})$", self.edition)
        return int(found.group(1)) if found else None


@dataclass(frozen=True)
class UpdateCheck:
    entry: GuideEntry
    status: str          # UP_TO_DATE / REVIEW_NEEDED / NOT_REGISTERED / NOT_HELD / NOT_CHECKED / ERROR
    latest: kosha_guide.GuideItem | None = None
    message: str = ""
    checked_numbers: tuple[str, ...] = field(default_factory=tuple)


def entries() -> list[GuideEntry]:
    doc = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return [GuideEntry(g["base_number"], tuple(g.get("aliases", ())), g["title"], g.get("edition", ""),
                       g.get("announced", ""), g.get("source_sha256", ""), tuple(g.get("used_by", ())),
                       tuple(g.get("extracted", ())), g.get("verification", "")) for g in doc["guides"]]


def entry(base_number: str) -> GuideEntry | None:
    wanted = base_number.strip().upper()
    for item in entries():
        if wanted == item.base_number.upper() or wanted in (a.upper() for a in item.aliases):
            return item
    return None


def used_by(purpose: str) -> list[GuideEntry]:
    """예: 'psm.form19-2' 가 근거로 삼는 지침들."""
    return [item for item in entries() if purpose in item.used_by]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cached_file(item: GuideEntry, cache_dir: Path | None = None) -> Path | None:
    """캐시에 있고 등록된 SHA-256과 일치하는 원문만 돌려준다. 일치하지 않으면 없는 것으로 본다."""
    if not item.source_sha256:
        return None
    path = (cache_dir or CACHE_DIR) / f"{item.edition}.pdf"
    return path if path.is_file() and sha256_of(path) == item.source_sha256 else None


def cache_local_copy(item: GuideEntry, source: Path, cache_dir: Path | None = None) -> Path:
    """사용자가 가진 원문을 캐시에 복사한다. 등록된 SHA-256과 다르면 판본이 다른 파일이므로 거부한다."""
    actual = sha256_of(source)
    if item.source_sha256 and actual != item.source_sha256:
        raise ValueError(f"{item.edition} 등록본과 다른 파일입니다(SHA-256 불일치). 새 판본이면 검토 후 목록을 갱신해야 합니다.")
    target_dir = cache_dir or CACHE_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{item.edition}.pdf"
    target.write_bytes(Path(source).read_bytes())
    return target


def check_updates(get: Callable[[str, dict[str, Any]], tuple[int, str]] | None = None) -> list[UpdateCheck]:
    """등록된 지침마다 조회서비스로 현행 판을 찾아 등록 판본과 비교한다. 바뀌었어도 값은 자동으로 바꾸지 않는다."""
    kwargs = {"get": get} if get else {}
    out = []
    for item in entries():
        latest, checked, last = None, [], None
        for number in (item.base_number, *item.aliases):
            checked.append(number)
            found, result = kosha_guide.latest_version(number, **kwargs)
            last = result
            if found is not None and (latest is None or (found.year or 0) > (latest.year or 0)):
                latest = found
            if result.status in ("NOT_CONFIGURED", "ERROR"):
                break
        if last is not None and last.status in ("NOT_CONFIGURED", "ERROR") and latest is None:
            status = "NOT_CHECKED" if last.status == "NOT_CONFIGURED" else "ERROR"
            out.append(UpdateCheck(item, status, None, last.message, tuple(checked)))
        elif latest is None:
            out.append(UpdateCheck(item, "NOT_HELD", None, "조회서비스에서 이 지침을 찾지 못했습니다.", tuple(checked)))
        elif not item.edition:
            out.append(UpdateCheck(item, "NOT_REGISTERED", latest,
                                   f"원문을 아직 등록하지 않았습니다. 현행 판은 {latest.number}(공표 {latest.announced})입니다.",
                                   tuple(checked)))
        elif item.year and latest.year and latest.year > item.year:
            out.append(UpdateCheck(item, "REVIEW_NEEDED", latest,
                                   f"등록 판본 {item.edition}보다 새 판 {latest.number}(공표 {latest.announced})가 있습니다. "
                                   "이전 값과 비교해 검토한 뒤 반영하세요.", tuple(checked)))
        else:
            out.append(UpdateCheck(item, "UP_TO_DATE", latest, "등록 판본이 현행입니다.", tuple(checked)))
    return out
