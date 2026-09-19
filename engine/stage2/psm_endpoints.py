from __future__ import annotations

"""PSM 별지 제19호의2(시나리오 및 피해예측 결과)의 끝점·기상 설정층.

물리 모델은 화학사고예방관리계획서와 같은 것을 쓰고, 어떤 끝점에서 거리를 구하는지만 다르다.
기본값은 서식 자체에 인쇄되어 있다(화재 4/12.5/37.5 kW/m2, 폭발 7/21/70 kPa, 인화성 25% LEL/LEL/UEL,
독성 ERPG 1/2/3). 서식 주석 ⑪~⑮가 관심 값을 바꿀 수 있게 하므로, 기본값과 '근거를 적은 사용자 지정값'을 함께 둔다.
공식 근거가 없는 값은 계산하지 않고 보류로 돌려준다.
"""

from dataclasses import dataclass, field

from . import cap_fire as fire

FIRE_KW_M2 = (4.0, 12.5, 37.5)
OVERPRESSURE_KPA = (7.0, 21.0, 70.0)
FLAMMABLE_LABELS = ("25% LEL", "LEL", "UEL")
TOXIC_LABELS = ("ERPG 1", "ERPG 2", "ERPG 3")

# 주석 ①②: 풍속은 1.5 m/s 또는 통상의 풍속, 대기안정도는 F 또는 통상의 대기안정도.
WORST_WEATHER = {"풍속(m/s)": 1.5, "대기안정도": "F"}
# 계산 검증이 끝난 과압: 1 psi = 6.895 kPa 이므로 7 kPa는 지침 계수(1 psi) 식으로 근사한다.
VERIFIED_OVERPRESSURE_KPA = (7.0,)


@dataclass(frozen=True)
class Endpoints:
    fire_kw_m2: tuple[float, ...] = FIRE_KW_M2
    overpressure_kpa: tuple[float, ...] = OVERPRESSURE_KPA
    custom_basis: str = ""  # 기본값과 다른 값을 쓸 때 그 근거

    def problems(self) -> tuple[str, ...]:
        if (self.fire_kw_m2 != FIRE_KW_M2 or self.overpressure_kpa != OVERPRESSURE_KPA) and not self.custom_basis.strip():
            return ("기본값(화재 4/12.5/37.5 kW/m2, 과압 7/21/70 kPa)과 다른 관심 값을 쓰려면 그 근거를 적어야 합니다.",)
        return ()


@dataclass(frozen=True)
class Distance:
    label: str
    meters: float | None
    status: str  # OK / HOLD
    note: str = ""


def fire_distances(*, kind: str, endpoints: Endpoints = Endpoints(), heat_kj_kg: float,
                   release_rate_kg_s: float = 0.0, pool_area_m2: float = 0.0, burning_rate: float = 0.0) -> list[Distance]:
    """제트('jet') 또는 풀('pool') 화재에서 끝점 열류별 거리."""
    out = []
    for flux in endpoints.fire_kw_m2:
        if kind == "jet":
            meters = fire.jet_fire_distance_m(release_rate_kg_s, heat_kj_kg, flux)
        else:
            meters = fire.pool_fire_distance_m(pool_area_m2, burning_rate, heat_kj_kg, flux)
        out.append(Distance(f"{flux:g} kW/m2", meters, "OK"))
    return out


def explosion_distances(mass_kg: float, heat_kj_kg: float, endpoints: Endpoints = Endpoints()) -> list[Distance]:
    """증기운 폭발 과압별 거리. 검증된 식은 1 psi(≈7 kPa)뿐이라 다른 과압은 근거가 생길 때까지 보류한다."""
    out = []
    for kpa in endpoints.overpressure_kpa:
        if kpa in VERIFIED_OVERPRESSURE_KPA:
            out.append(Distance(f"{kpa:g} kPa", fire.vce_distance_1psi_m(mass_kg, heat_kj_kg), "OK",
                                "1 psi(6.9 kPa) 식으로 계산"))
        else:
            out.append(Distance(f"{kpa:g} kPa", None, "HOLD",
                                "이 과압의 환산거리 근거(TNT 과압-환산거리 표 등)가 확인되지 않아 계산하지 않았습니다."))
    return out


@dataclass(frozen=True)
class ErpgRecord:
    cas: str
    name: str
    values: dict[int, float | None] = field(default_factory=dict)  # 1·2·3 -> ppm
    statuses: dict[int, str] = field(default_factory=dict)         # 값이 없을 때 사유(Insufficient Data 등)
    source: str = "AIHA_ERPG"
    source_year: str = ""


def toxic_distance_inputs(record: ErpgRecord | None) -> list[Distance]:
    """ERPG 1·2·3 각각을 사용 가능/보류로 나눈다. 없는 등급을 다른 지표(PAC·AEGL)로 대신하지 않는다."""
    out = []
    for level, label in zip((1, 2, 3), TOXIC_LABELS):
        value = record.values.get(level) if record else None
        if value is not None:
            out.append(Distance(label, float(value), "OK", "ppm"))
        else:
            reason = (record.statuses.get(level) if record else "") or "공식 ERPG 자료가 확인되지 않음"
            out.append(Distance(label, None, "HOLD", f"{reason}. 다른 지표로 대체하지 않고 보류합니다."))
    return out
