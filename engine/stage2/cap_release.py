from __future__ import annotations

"""누출공 크기와 누출률·누출량 계산(사고시나리오 분석의 입력).

기준: 사고시나리오 선정 및 위험도 분석에 관한 기술지침(화학물질안전원지침 제2021-3호)
3-1(누출량), 3-3(누출공·누출시간). 지침 3-3 ① 2)가 인정하는 KOSHA GUIDE P-92-2023
(누출원 모델링에 관한 기술지침)의 식을 쓴다: 기체 식(1)~(3)·표 1의 누출계수,
액체 식(4), 평형 포화액체 2상 유출 식(6). 지침 붙임의 염소 계산 예(붙임 1·2·3)와 같은
값이 나오는 것을 테스트로 확인했다. 비평형 포화액체(식 7), 과냉각 액체(식 9), 배관 누출
(7장)은 아직 구현하지 않았다.
"""

from dataclasses import dataclass, field
import math

GAS_CONSTANT = 8.314462618  # J/(mol·K)
ATMOSPHERIC_PA = 101325.0
GRAVITY = 9.80665
KGF_CM2_MPA = 0.0980665

CD_LIQUID = 0.61        # KOSHA GUIDE P-92 표 1: 오리피스/구멍, 음속 미만 0.61~0.67(붙임 2 예시는 0.61)
CD_GAS_SONIC_FAR = 0.84   # 표 1: 음속 이상, P1 >> Pa
CD_GAS_SONIC_NEAR = 0.75  # 표 1: 음속 이상, Pa/P1 ≃ PCF/P1
CD_GAS_SUBSONIC = 0.61    # 표 1: 음속 미만
DEFAULT_GAMMA = 1.4     # 비열비를 모를 때(이원자 기체 근사). 물질별 값이 있으면 그 값을 쓴다.
KGF_CM2_PA = 98066.5
K_MECHANICAL = 427.0    # m·kgf/kcal (P-92 식 6의 상수)
GC = 9.8                # kg·m/(kgf·s2)

# 지침 3-3 ① 3): 배관직경 전체를 누출공으로 보는 조건
FULL_BORE_BELOW_MM = 50.0
FULL_BORE_TEMPERATURE_C = 350.0
FULL_BORE_PRESSURE_MPA = 10 * KGF_CM2_MPA  # 10 kgf/cm2 (게이지)
HOLE_FRACTION = 0.20    # 지침 3-3 ① 1): 가장 큰 연결구 배관직경의 20% 이상

# 지침 3-3 ②는 누출시간을 API 581 방법으로 산정하라고만 한다. 아래는 API 581 감지·차단 등급별
# 누출시간(분)으로 알려진 값이며 원문을 확인하지 못했다. 지침은 사람이 현장에서 직접 차단하는
# 경우 차단 효과를 인정하지 않으므로 수동 차단은 C등급으로 본다. 전문가 확인 전 참고값이다.
API581_DURATION_MIN = {
    ("A", "A"): 20, ("A", "B"): 30, ("A", "C"): 40,
    ("B", "A"): 30, ("B", "B"): 30, ("B", "C"): 40,
    ("C", "A"): 40, ("C", "B"): 40, ("C", "C"): 60,
}
WORST_CASE_MIN = 10  # 지침 3-1 ① 2): 최악조건은 10분 동안 최대보유량이 모두 누출


@dataclass(frozen=True)
class Hole:
    diameter_mm: float
    reason: str


def hole_diameter(largest_connection_mm: float, *, operating_celsius: float | None = None,
                  gauge_mpa: float | None = None, is_tank_lorry: bool = False,
                  open_top_width_m: float | None = None, open_top_length_m: float | None = None,
                  has_other_piping: bool = True) -> Hole:
    """누출공 지름(mm)과 적용한 기준."""
    if open_top_width_m and open_top_length_m and not has_other_piping:
        size = (open_top_width_m + open_top_length_m) * 0.5 * HOLE_FRACTION * 1000.0
        return Hole(size, "상부 개방 설비(도금조 등): (가로+세로)×0.5의 20% (지침 3-3 ① 1) 가)")
    if is_tank_lorry:
        return Hole(largest_connection_mm, "탱크로리 체결부: 배관직경 전체 (지침 3-3 ① 3) 다)")
    if largest_connection_mm < FULL_BORE_BELOW_MM:
        return Hole(largest_connection_mm, "가장 큰 연결구 배관직경이 50mm 미만: 배관직경 전체 (지침 3-3 ① 3) 가)")
    if operating_celsius is not None and operating_celsius >= FULL_BORE_TEMPERATURE_C:
        return Hole(largest_connection_mm, "운전온도 350℃ 이상 특수설비: 배관직경 전체 (지침 3-3 ① 3) 나)")
    if gauge_mpa is not None and gauge_mpa >= FULL_BORE_PRESSURE_MPA:
        return Hole(largest_connection_mm, "운전압력 10kgf/cm2 이상 특수설비: 배관직경 전체 (지침 3-3 ① 3) 나)")
    return Hole(largest_connection_mm * HOLE_FRACTION, "가장 큰 연결구 배관직경의 20% (지침 3-3 ① 1)")


def _area_m2(diameter_mm: float) -> float:
    return math.pi * (diameter_mm / 1000.0) ** 2 / 4.0


def liquid_release_rate(diameter_mm: float, density_kg_m3: float, gauge_pa: float, head_m: float,
                        cd: float = CD_LIQUID) -> float:
    """액상 누출률(kg/s): m = Cd·A·√(2ρ·ΔP + 2ρ²·g·h)."""
    driving = 2.0 * density_kg_m3 * max(gauge_pa, 0.0) + 2.0 * density_kg_m3 ** 2 * GRAVITY * max(head_m, 0.0)
    return cd * _area_m2(diameter_mm) * math.sqrt(driving)


def gas_discharge_coefficient(absolute_pa: float, ambient_pa: float, gamma: float) -> float:
    """P-92 표 1: 음속 미만 0.61, 음속 이상은 P1 >> Pa이면 0.84, 임계압력비 근처이면 0.75."""
    critical = (2.0 / (gamma + 1.0)) ** (gamma / (gamma - 1.0))   # PCF/P1
    ratio = ambient_pa / absolute_pa                               # Pa/P1
    if ratio > critical:
        return CD_GAS_SUBSONIC
    return CD_GAS_SONIC_FAR if ratio <= 0.5 * critical else CD_GAS_SONIC_NEAR


def gas_release_rate(diameter_mm: float, absolute_pa: float, kelvin: float, molar_mass_g_mol: float,
                     gamma: float = DEFAULT_GAMMA, cd: float | None = None,
                     ambient_pa: float = ATMOSPHERIC_PA) -> float:
    """기체 누출률(kg/s): 임계압력비 이상이면 초크 유동, 아니면 아임계 유동(P-92 식 2·3)."""
    if absolute_pa <= ambient_pa:
        return 0.0
    if cd is None:
        cd = gas_discharge_coefficient(absolute_pa, ambient_pa, gamma)
    molar = molar_mass_g_mol / 1000.0
    area = _area_m2(diameter_mm)
    critical_ratio = ((gamma + 1.0) / 2.0) ** (gamma / (gamma - 1.0))
    if absolute_pa / ambient_pa >= critical_ratio:
        flux = absolute_pa * math.sqrt(gamma * molar / (GAS_CONSTANT * kelvin)) * (
            2.0 / (gamma + 1.0)) ** ((gamma + 1.0) / (2.0 * (gamma - 1.0)))
    else:
        ratio = ambient_pa / absolute_pa
        flux = math.sqrt(2.0 * absolute_pa * absolute_pa * molar / (GAS_CONSTANT * kelvin) * gamma / (gamma - 1.0)
                         * (ratio ** (2.0 / gamma) - ratio ** ((gamma + 1.0) / gamma)))
    return cd * area * flux


def equilibrium_flashing_rate(diameter_mm: float, latent_heat_kcal_kg: float, vapor_density_kg_m3: float,
                              liquid_density_kg_m3: float, liquid_cp_kcal_kg_k: float, kelvin: float) -> float:
    """평형 포화액체(누출지점이 설비 외면에서 0.1 m 이상) 2상 유출 누출률(kg/s), P-92 식 (6).

    Q = [A·ΔHv / (1/ρG − 1/ρL)] · [K·gc / (T1·CpL)]^½
    """
    specific_volume_change = 1.0 / vapor_density_kg_m3 - 1.0 / liquid_density_kg_m3
    return (_area_m2(diameter_mm) * latent_heat_kcal_kg / specific_volume_change) * math.sqrt(
        K_MECHANICAL * GC / (kelvin * liquid_cp_kcal_kg_k))


def flash_fraction(liquid_cp: float, latent_heat: float, operating_k: float, boiling_k: float) -> float:
    """P-92 식 (5): 대기압으로 방출될 때 증기로 바뀌는 비율."""
    return 1.0 - math.exp(-liquid_cp / latent_heat * (operating_k - boiling_k))


def leak_duration_min(detection: str = "C", isolation: str = "C") -> int:
    """API 581 등급(A~C)별 누출시간. 잘못된 등급은 가장 보수적인 C로 본다."""
    return API581_DURATION_MIN[(detection if detection in "ABC" else "C", isolation if isolation in "ABC" else "C")]


@dataclass(frozen=True)
class Release:
    hole_mm: float
    hole_reason: str
    rate_kg_s: float | None
    duration_min: float | None
    amount_kg: float | None
    model: str
    problems: tuple[str, ...] = field(default_factory=tuple)


def release_amount_kg(rate_kg_s: float, duration_min: float, inventory_kg: float) -> float:
    """누출량은 누출률 × 누출시간이되 보유량을 넘을 수 없다."""
    return min(rate_kg_s * duration_min * 60.0, inventory_kg)


def worst_case_amount_kg(inventory_kg: float) -> float:
    """최악조건 시나리오: 10분 동안 최대보유량 전량(지침 3-1 ① 2)). 누출률은 전량 ÷ 600초."""
    return inventory_kg
