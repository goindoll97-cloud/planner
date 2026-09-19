from __future__ import annotations

"""독성 영향범위 끝점농도(사고시나리오 선정 및 위험도 분석에 관한 기술지침 붙임 1).

화학물질안전원지침 제2021-3호 2-3 ① 1): 끝점농도 적용 우선순위는
ERPG-2 → 1시간 AEGL-2 → PAC-2 → IDLH의 10%(IDLH × 0.1)이며, IDLH도 없으면
LC50·LCLo·LD50·LDLo 환산값을 IDLH 대신 쓸 수 있다.
표 값은 data/stage2/cap_endpoints/toxic_endpoints_2021-3.json 에 있고,
`parse_guideline_text`로 지침 본문 텍스트에서 다시 만들 수 있다.
"""

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
from typing import Any

DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "stage2" / "cap_endpoints" / "toxic_endpoints_2021-3.json"
PRIORITY = ("ERPG-2", "AEGL-2", "PAC-2", "IDLH")
MOLAR_VOLUME_L = 24.45  # 25℃, 1기압 (지침 붙임 1 비고 1)
_TABLE_HEADER = re.compile(r"^연번\s+화학물질명\s+CAS number\s+(ERPG-2|AEGL|PAC-2|IDLH)\s*$")
_CAS = re.compile(r"(\d{2,7}-\d{2}-\d)")
_VALUE = re.compile(r"([\d.,]+)\s*(ppm|mg[^/\d]*?/\s*m\s*[3³])", re.I)
_TABLE_KEY = {"ERPG-2": "ERPG-2", "AEGL": "AEGL-2", "PAC-2": "PAC-2", "IDLH": "IDLH"}


@dataclass(frozen=True)
class Endpoint:
    cas: str
    name: str
    table: str          # ERPG-2 / AEGL-2 / PAC-2 / IDLH
    value: float
    unit: str           # ppm 또는 mg/m3
    alternative: str    # 표에 두 단위가 함께 있으면 나머지 값
    basis: str          # 화면에 보여 줄 근거 문구
    factor: float = 1.0  # IDLH는 0.1을 곱해 끝점으로 쓴다

    @property
    def endpoint_value(self) -> float:
        return self.value * self.factor


def _to_number(text: str) -> float:
    return float(text.replace(",", ""))


def _unit(text: str) -> str:
    return "ppm" if text.lower().startswith("ppm") else "mg/m3"


def parse_guideline_text(text: str) -> dict[str, dict[str, dict[str, Any]]]:
    """Guideline body text -> {table: {cas: {name, value, unit, alternative}}}."""
    tables: dict[str, dict[str, dict[str, Any]]] = {key: {} for key in PRIORITY}
    current: str | None = None
    records: list[tuple[str, list[str]]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        header = _TABLE_HEADER.match(line)
        if header:
            current = _TABLE_KEY[header.group(1)]
            continue
        if current is None or line.startswith("- ") or line.startswith("출처)") or line.startswith("비고"):
            if line.startswith("출처)") or line.startswith("비고"):
                current = None if line.startswith("출처)") else current
            continue
        if re.match(r"^\d+\s", line):
            records.append((current, [line]))
        elif records and records[-1][0] == current:
            records[-1][1].append(line)
    for table, parts in records:
        joined = " ".join(parts)
        cas = _CAS.search(joined)
        if not cas:
            continue
        name = re.sub(r"^\d+\s+", "", joined[: cas.start()]).strip()
        values = _VALUE.findall(joined[cas.end():])
        if not values:
            continue
        number, unit = _to_number(values[0][0]), _unit(values[0][1])
        alternative = f"{values[1][0]} {_unit(values[1][1])}" if len(values) > 1 else ""
        tables[table].setdefault(cas.group(1), {"name": name, "value": number, "unit": unit, "alternative": alternative})
    return tables


@lru_cache(maxsize=1)
def load_tables() -> dict[str, dict[str, dict[str, Any]]]:
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    return payload["tables"]


def endpoint_for(cas: str) -> Endpoint | None:
    """First available table by 지침 priority; None when no table lists the CAS."""
    tables = load_tables()
    for table in PRIORITY:
        entry = tables.get(table, {}).get(cas.strip())
        if entry:
            factor = 0.1 if table == "IDLH" else 1.0
            label = "IDLH × 0.1" if table == "IDLH" else table
            return Endpoint(
                cas=cas.strip(), name=entry["name"], table=table, value=entry["value"], unit=entry["unit"],
                alternative=entry.get("alternative", ""),
                basis=f"{label} {entry['value'] * factor:g} {entry['unit']} (기술지침 붙임 1)", factor=factor,
            )
    return None


def ppm_to_mg_m3(ppm: float, molar_mass: float) -> float:
    return ppm * molar_mass / MOLAR_VOLUME_L


def mg_m3_to_ppm(mg_m3: float, molar_mass: float) -> float:
    return mg_m3 * MOLAR_VOLUME_L / molar_mass


def fallback_endpoint_mg_m3(*, lc50_mg_m3: float | None = None, lc50_minutes: int | None = None,
                            lclo_mg_m3: float | None = None, ld50_mg_kg: float | None = None,
                            ldlo_mg_kg: float | None = None) -> tuple[float, str] | None:
    """지침 2-3 ① 1) 나. (5): IDLH가 없는 물질의 끝점 대체값(mg/m3)과 근거."""
    if lc50_mg_m3 is not None and lc50_minutes in (30, 240):
        factor = 0.1 if lc50_minutes == 30 else 0.2
        return lc50_mg_m3 * factor, f"{factor:g} × LC50({lc50_minutes}분 노출)"
    if lclo_mg_m3 is not None:
        return lclo_mg_m3, "1 × LCLo"
    body_air = 70.0 / 0.4  # X mg/m3 = (Y mg/kg)(70 kg) / 0.4 m3
    if ld50_mg_kg is not None:
        return ld50_mg_kg * body_air * 0.01, "0.01 × LD50 (경구, 70kg/0.4m3 환산)"
    if ldlo_mg_kg is not None:
        return ldlo_mg_kg * body_air * 0.1, "0.1 × LDLo (경구, 70kg/0.4m3 환산)"
    return None
