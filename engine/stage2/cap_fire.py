from __future__ import annotations

"""화재·폭발 피해반경(끝점: 폭발 1 psi 과압, 화재 5 kW/m²).

기준: 사고시나리오 선정 및 위험도 분석에 관한 기술지침(화학물질안전원지침 제2021-3호) 2-3 ① 2)
(폭발은 1 psi 과압, 화재는 40초 동안 5 kW/m² 복사열)와 3-2 ③(증기운 폭발 효율은 TNT 당량·TNO 멀티에너지
등의 값). 지침이 식을 정하지 않아 공개 표준 식을 쓴다.

- 증기운 폭발: EPA 위험관리프로그램(RMP) 장외영향분석 지침의 TNT 당량식
  X[m] = 17 · (0.1 · W[lb] · HC / HC_TNT)^(1/3), HC_TNT = 1,943 Btu/lb, 폭발효율 10%
- 화재: 점광원 복사열 모델 q = τ · f · Q / (4π r²) (풀 화재는 Burgess–Zabetakis 연소속도,
  제트 화재는 누출률 × 연소열). 대기 투과율 τ=1, 복사분율 f는 보수적인 상한을 쓴다.

한계: TNO 멀티에너지 모델·고체화염 모델·BLEVE 화구는 구현하지 않았고, 점광원 모델은
화염 가까이에서 복사열을 과대·과소 평가할 수 있다. 결과는 제안값이며 확정 전에 대조해야 한다.
"""

import math

BTU_LB_TO_KJ_KG = 2.326
LB_PER_KG = 2.20462
HC_TNT_BTU_LB = 1943.0
EXPLOSION_YIELD = 0.10              # EPA RMP OCA 기본 폭발효율
EXPLOSION_COEFFICIENT_M = 17.0      # 1 psi(6.9 kPa) 거리 계수
FIRE_ENDPOINT_KW_M2 = 5.0           # 지침: 40초 동안 5 kW/m2
POOL_RADIATIVE_FRACTION = 0.35      # 탄화수소 풀 화재 0.15~0.35 중 상한(보수)
JET_RADIATIVE_FRACTION = 0.30       # 제트 화재 0.2~0.3 중 상한(보수)
TRANSMISSIVITY = 1.0


def vce_distance_1psi_m(mass_kg: float, heat_of_combustion_kj_kg: float,
                        yield_fraction: float = EXPLOSION_YIELD) -> float:
    """증기운 폭발로 1 psi 과압이 걸리는 거리(m)."""
    if mass_kg <= 0 or heat_of_combustion_kj_kg <= 0:
        return 0.0
    weight_lb = mass_kg * LB_PER_KG
    hc_btu_lb = heat_of_combustion_kj_kg / BTU_LB_TO_KJ_KG
    return EXPLOSION_COEFFICIENT_M * (yield_fraction * weight_lb * hc_btu_lb / HC_TNT_BTU_LB) ** (1.0 / 3.0)


def point_source_radius_m(heat_release_w: float, radiative_fraction: float,
                          endpoint_kw_m2: float = FIRE_ENDPOINT_KW_M2, transmissivity: float = TRANSMISSIVITY) -> float:
    """점광원 복사열 q = τ·f·Q/(4π r²) 가 끝점 열류에 이르는 거리(m)."""
    if heat_release_w <= 0:
        return 0.0
    return math.sqrt(transmissivity * radiative_fraction * heat_release_w / (4.0 * math.pi * endpoint_kw_m2 * 1000.0))


def burning_rate_kg_m2_s(heat_of_combustion_kj_kg: float, liquid_cp_kj_kg_k: float, boiling_c: float,
                         ambient_c: float, latent_heat_kj_kg: float) -> float:
    """풀 화재 질량 연소속도 m'' = 0.001·ΔHc / (Cp·(Tb − Ta) + ΔHv) (Burgess–Zabetakis, 상한 상관식)."""
    denominator = liquid_cp_kj_kg_k * max(boiling_c - ambient_c, 0.0) + latent_heat_kj_kg
    return 0.001 * heat_of_combustion_kj_kg / denominator


def pool_fire_distance_m(pool_area_m2: float, burning_rate: float, heat_of_combustion_kj_kg: float,
                         endpoint_kw_m2: float = FIRE_ENDPOINT_KW_M2) -> float:
    """풀 화재 중심에서 끝점 열류(기본 5 kW/m2)에 이르는 거리(m)."""
    heat_release_w = burning_rate * pool_area_m2 * heat_of_combustion_kj_kg * 1000.0
    return point_source_radius_m(heat_release_w, POOL_RADIATIVE_FRACTION, endpoint_kw_m2)


def jet_fire_distance_m(release_rate_kg_s: float, heat_of_combustion_kj_kg: float,
                        endpoint_kw_m2: float = FIRE_ENDPOINT_KW_M2) -> float:
    """제트 화재(기체 누출 점화) 화염 중심에서 끝점 열류(기본 5 kW/m2)에 이르는 거리(m)."""
    return point_source_radius_m(release_rate_kg_s * heat_of_combustion_kj_kg * 1000.0, JET_RADIATIVE_FRACTION,
                                 endpoint_kw_m2)
