"""Grassland fire danger and grass-fire spread rate.

Constants are from McArthur Mk 4 GFDI (Noble et al. 1980) and the CSIRO grassland
model (Cheney et al. 1998), written from memory: verify against the sources.
"""

import math

# Month -> default degree of curing (%) for Kansas grass.
_CURING_BY_MONTH = {
    1: 95, 2: 95, 3: 95, 4: 95, 5: 72.5, 6: 50, 7: 50, 8: 50, 9: 65, 10: 80, 11: 95, 12: 95,
}


def default_curing(month: int, override: float | None = None) -> float:
    return override if override is not None else _CURING_BY_MONTH[month]


def gfdi(curing_pct: float, temp_c: float, rh_pct: float, wind_kmh: float) -> float:
    c = max(curing_pct, 1.0)
    return 2.0 * math.exp(
        -23.6
        + 5.01 * math.log(c)
        + 0.0281 * temp_c
        - 0.226 * math.sqrt(max(rh_pct, 0.0))
        + 0.633 * math.sqrt(max(wind_kmh, 0.0))
    )


def gfdi_band(value: float) -> str:
    if value < 12:
        return "Low-Moderate"
    if value < 25:
        return "High"
    if value < 50:
        return "Very High"
    if value < 100:
        return "Severe"
    return "Extreme"


def dead_fuel_moisture(temp_c: float, rh_pct: float) -> float:
    return max(9.58 - 0.205 * temp_c + 0.138 * rh_pct, 1.0)


def moisture_factor(mc: float, wind_kmh: float) -> float:
    if mc < 12:
        return math.exp(-0.108 * mc)
    if wind_kmh <= 10:
        return max(0.684 - 0.0342 * mc, 0.0)
    return max(0.547 - 0.0228 * mc, 0.0)


def curing_factor(curing_pct: float) -> float:
    return 1.12 / (1 + 59.2 * math.exp(-0.124 * (curing_pct - 50)))


def head_ros_kmh(wind_kmh: float, temp_c: float, rh_pct: float, curing_pct: float) -> float:
    """Head-fire rate of spread for natural pasture, km/h."""
    phi_m = moisture_factor(dead_fuel_moisture(temp_c, rh_pct), wind_kmh)
    phi_c = curing_factor(curing_pct)
    if wind_kmh < 5:
        base = 0.054 + 0.269 * wind_kmh
    else:
        base = 1.4 + 0.838 * (wind_kmh - 5) ** 0.844
    return base * phi_m * phi_c


def length_to_breadth(wind_kmh: float) -> float:
    return 1.1 * wind_kmh**0.464 if wind_kmh >= 1 else 1.0
