from __future__ import annotations

"""PSM 별지 제19호의2 독성 끝점(ERPG 1·2·3) 해석.

값의 출처는 KOSHA GUIDE C-C-46-2026 <표1>이다(고시가 따르도록 한 KOSHA 기술지침 계열의 국내 근거표).
표에 값이 있으면 그것을 쓰고, 표에 값이 없으면 같은 규정 7(2)의 산정 규칙을 '추정'으로 표시해 쓴다.
표가 NA(적용하지 않음)라고 한 등급은 추정하지 않고 생략한다. 다른 지표(PAC·AEGL)로 몰래 바꾸지 않는다.
"""

from dataclasses import dataclass
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_endpoints" / "erpg_kosha_cc46_2026.json"
MOLAR_VOLUME_L = 24.45  # 25℃, 1기압(표 기준온도)
SOURCE = "KOSHA GUIDE C-C-46-2026 <표1>"


@dataclass(frozen=True)
class ErpgLevel:
    level: int
    status: str            # TABLE / ESTIMATED / NOT_APPLICABLE / HOLD
    mg_m3: float | None = None
    ppm: float | None = None
    basis: str = ""


@lru_cache(maxsize=1)
def _table() -> dict[str, dict[str, Any]]:
    doc = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {cas: item for item in doc["substances"] for cas in item["cas"]}


def substance(cas: str) -> dict[str, Any] | None:
    return _table().get(str(cas or "").strip())


def _mg(ppm: float, molar_mass: float) -> float:
    return ppm * molar_mass / MOLAR_VOLUME_L


def _from_table(level: int, entry: dict[str, Any], molar_mass: float) -> ErpgLevel | None:
    item = entry["erpg"][str(level)]
    if item["status"] == "NOT_APPLICABLE":
        return ErpgLevel(level, "NOT_APPLICABLE", basis=f"{SOURCE}에서 적용하지 않음(NA)")
    if item["status"] != "TABLE":
        return None
    ppm, mg = item.get("ppm"), item.get("mg_m3")
    mg = mg if mg is not None else (_mg(ppm, molar_mass) if ppm is not None else None)
    return ErpgLevel(level, "TABLE", mg_m3=mg, ppm=ppm, basis=SOURCE)


def resolve(cas: str, *, molar_mass: float | None = None, stel_mg_m3: float | None = None,
            twa_mg_m3: float | None = None) -> list[ErpgLevel]:
    """ERPG 1·2·3 각 등급의 농도. 표 값 > 규정 7(2) 산정(추정) > 보류 순서.

    산정 규칙: ERPG-2 = STEL(또는 CEILING) 또는 TWA의 3배, ERPG-1 = ERPG-2/10, ERPG-3 = ERPG-2의 5배.
    (다른 대안인 취기전단농도·LC50/30은 입력 자료가 별도로 필요해 여기서는 쓰지 않는다.)
    """
    entry = substance(cas)
    mw = entry["molar_mass"] if entry else molar_mass
    found: dict[int, ErpgLevel] = {}
    if entry:
        for level in (1, 2, 3):
            hit = _from_table(level, entry, mw)
            if hit is not None:
                found[level] = hit
    if 2 not in found:
        if stel_mg_m3 is not None:
            found[2] = ErpgLevel(2, "ESTIMATED", mg_m3=stel_mg_m3, basis="규정 7(2)(나) ① STEL 또는 CEILING 값")
        elif twa_mg_m3 is not None:
            found[2] = ErpgLevel(2, "ESTIMATED", mg_m3=3 * twa_mg_m3, basis="규정 7(2)(나) ② TWA의 3배")
    base = found.get(2)
    if base is not None and base.mg_m3 is not None:
        if 1 not in found:
            found[1] = ErpgLevel(1, "ESTIMATED", mg_m3=base.mg_m3 / 10, basis="규정 7(2)(가) ② ERPG-2를 10으로 나눈 값")
        if 3 not in found:
            found[3] = ErpgLevel(3, "ESTIMATED", mg_m3=base.mg_m3 * 5, basis="규정 7(2)(다) ② ERPG-2의 5배 값")
    out = []
    for level in (1, 2, 3):
        out.append(found.get(level) or ErpgLevel(level, "HOLD", basis=(
            "표에 없고 산정에 쓸 STEL·TWA 자료도 없어 계산하지 않았습니다." if not entry else
            "산정에 쓸 자료가 없어 계산하지 않았습니다.")))
    return out
