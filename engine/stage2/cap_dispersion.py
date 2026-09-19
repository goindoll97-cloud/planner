from __future__ import annotations

"""독성 누출의 피해반경(끝점농도 도달거리) 계산.

기준: 사고시나리오 선정 및 위험도 분석에 관한 기술지침(화학물질안전원지침 제2021-3호)
2-3(끝점), 2-4~2-7(풍속·안정도·기온·지형·누출높이), 3-2 ②(누출 형태별 확산), 붙임 4(증발속도).
지침은 확산 식을 정하지 않아 공개된 표준 식을 쓴다: 지표 연속 누출의 가우시안 플룸
C = Q / (π·u·σy·σz), 확산계수는 Briggs(1973) 도시·전원 상관식(파스퀼 안정도 A~F).
한계: 중가스(염소 등) 효과, 건물 후류, 지형, 유한 시간 누출(퍼프) 효과는 반영하지 않는다.
"""

from dataclasses import dataclass
import math

MOLAR_VOLUME_L = 24.45  # 25℃, 1기압 (지침 붙임 1 비고)
DEFAULT_WIND_MS = 3.0
DEFAULT_STABILITY = "D"
WORST_WIND_MS = 1.5
WORST_STABILITY = "F"
MAX_DISTANCE_M = 100_000.0

# Briggs 1973 (x in m): (σy 계수 a, σy 보정 b, σz 형식) — σy = a·x·(1+b·x)^-1/2
_RURAL = {
    "A": (0.22, 1e-4, lambda x: 0.20 * x),
    "B": (0.16, 1e-4, lambda x: 0.12 * x),
    "C": (0.11, 1e-4, lambda x: 0.08 * x * (1 + 2e-4 * x) ** -0.5),
    "D": (0.08, 1e-4, lambda x: 0.06 * x * (1 + 1.5e-3 * x) ** -0.5),
    "E": (0.06, 1e-4, lambda x: 0.03 * x * (1 + 3e-4 * x) ** -1),
    "F": (0.04, 1e-4, lambda x: 0.016 * x * (1 + 3e-4 * x) ** -1),
}
_URBAN = {
    "A": (0.32, 4e-4, lambda x: 0.24 * x * (1 + 1e-3 * x) ** 0.5),
    "B": (0.32, 4e-4, lambda x: 0.24 * x * (1 + 1e-3 * x) ** 0.5),
    "C": (0.22, 4e-4, lambda x: 0.20 * x),
    "D": (0.16, 4e-4, lambda x: 0.14 * x * (1 + 3e-4 * x) ** -0.5),
    "E": (0.11, 4e-4, lambda x: 0.08 * x * (1 + 1.5e-3 * x) ** -0.5),
    "F": (0.11, 4e-4, lambda x: 0.08 * x * (1 + 1.5e-3 * x) ** -0.5),
}
URBAN, RURAL = "도시", "전원"


def sigmas(distance_m: float, stability: str, terrain: str) -> tuple[float, float]:
    table = _URBAN if terrain == URBAN else _RURAL
    a, b, sigma_z = table[stability.upper()]
    return a * distance_m * (1.0 + b * distance_m) ** -0.5, sigma_z(distance_m)


def ground_concentration(rate_kg_s: float, distance_m: float, *, wind_ms: float = DEFAULT_WIND_MS,
                         stability: str = DEFAULT_STABILITY, terrain: str = RURAL) -> float:
    """지표 연속 누출원의 지표 중심선 농도(kg/m3)."""
    sigma_y, sigma_z = sigmas(distance_m, stability, terrain)
    return rate_kg_s / (math.pi * wind_ms * sigma_y * sigma_z)


def ppm_to_kg_m3(ppm: float, molar_mass: float) -> float:
    return ppm * molar_mass / MOLAR_VOLUME_L * 1e-6


def mg_m3_to_kg_m3(mg_m3: float) -> float:
    return mg_m3 * 1e-6


def distance_to_endpoint(rate_kg_s: float, endpoint_kg_m3: float, *, wind_ms: float = DEFAULT_WIND_MS,
                         stability: str = DEFAULT_STABILITY, terrain: str = RURAL) -> float:
    """중심선 농도가 끝점농도가 되는 풍하 거리(m). 1 m에서도 끝점보다 낮으면 0."""
    if rate_kg_s <= 0 or endpoint_kg_m3 <= 0:
        return 0.0

    def excess(distance: float) -> float:
        return ground_concentration(rate_kg_s, distance, wind_ms=wind_ms, stability=stability, terrain=terrain) - endpoint_kg_m3

    if excess(1.0) <= 0:
        return 0.0
    if excess(MAX_DISTANCE_M) > 0:
        return MAX_DISTANCE_M
    low, high = 1.0, MAX_DISTANCE_M
    for _ in range(80):
        mid = math.sqrt(low * high)
        if excess(mid) > 0:
            low = mid
        else:
            high = mid
    return high


# ---- 액체 풀 증발 (지침 붙임 4, 출처: EPA RMP Offsite Consequence Analysis Appendix D) ------------

EPA_EVAP_COEFFICIENT = 0.284          # QR[lb/min] = 0.284·U^0.78·MW^(2/3)·A[ft2]·VP[mmHg] / (82.05·T[K])
_FT2_PER_M2 = 10.7639
_LB_PER_KG = 2.20462


def pool_area_m2(released_kg: float, density_g_cm3: float, dike_area_m2: float | None = None) -> float:
    """붙임 4 주1): 1 cm 깊이 액체층 면적 A = 누출량/(밀도×10). 방류벽이 있으면 두 값 중 작은 값."""
    unrestrained = released_kg / (density_g_cm3 * 10.0)
    return min(unrestrained, dike_area_m2) if dike_area_m2 else unrestrained


def evaporation_rate_kg_min(wind_ms: float, molar_mass: float, area_m2: float, vapor_pressure_mmhg: float,
                            kelvin: float) -> float:
    """증발속도(kg/분). 원 식(lb/min, ft2)을 kg·m2로 환산해 적용한다."""
    per_area_lb_ft2 = (EPA_EVAP_COEFFICIENT * wind_ms ** 0.78 * molar_mass ** (2.0 / 3.0) * vapor_pressure_mmhg
                       / (82.05 * kelvin))
    return per_area_lb_ft2 * area_m2 * _FT2_PER_M2 / _LB_PER_KG


@dataclass(frozen=True)
class Weather:
    wind_ms: float = DEFAULT_WIND_MS
    stability: str = DEFAULT_STABILITY
    terrain: str = RURAL
    label: str = "사고시나리오 기본 기상(풍속 3 m/s, 안정도 D)"


WORST_CASE = Weather(WORST_WIND_MS, WORST_STABILITY, RURAL, "최악조건 기상(풍속 1.5 m/s, 안정도 F)")
