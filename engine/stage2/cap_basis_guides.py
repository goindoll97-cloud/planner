from __future__ import annotations

"""계산 근거로 쓰는 코샤가이드 목록과 현행 판 확인(조회서비스)."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Callable

from .. import kosha_guide

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_forms" / "basis_guides.json"


@dataclass(frozen=True)
class BasisStatus:
    number: str
    title: str
    used_in: str
    cited_year: int | None
    verified_edition: str
    latest: kosha_guide.GuideItem | None
    lookup_status: str
    lookup_message: str

    @property
    def newer_than_cited(self) -> bool:
        return bool(self.latest and self.latest.year and self.cited_year and self.latest.year > self.cited_year)

    @property
    def summary(self) -> str:
        if self.latest is None:
            return f"KOSHA GUIDE {self.number} — 현행 판 조회 안 됨({self.lookup_message})"
        text = f"KOSHA GUIDE {self.latest.number} (공표 {self.latest.announced})"
        if self.newer_than_cited:
            text += f" — 기술지침이 인용한 {self.number}-{self.cited_year}보다 새 판입니다"
        return text


def basis_guides() -> list[dict[str, Any]]:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))["guides"]


def basis_status(get: Callable | None = None) -> list[BasisStatus]:
    kwargs = {"get": get} if get else {}
    out = []
    for guide in basis_guides():
        latest, result = kosha_guide.latest_version(guide["number"], **kwargs)
        out.append(BasisStatus(guide["number"], guide["title"], guide["used_in"], guide.get("cited_year"),
                               guide.get("verified_edition", ""), latest, result.status, result.message))
    return out
