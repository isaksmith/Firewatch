"""Points-based rules scorer (v0, and permanent fallback). See docs/DESIGN.md section 5.2."""

from ..fire_weather import gfdi_band

SCORER_NAME = "rules-v0"
BASE_SCORE = 30
KMH_PER_MPH = 1.609344


def _reason(feature: str, label: str, points: int) -> dict:
    return {"feature": feature, "label": label, "contribution": points}


def score_rules(f: dict) -> tuple[int, list[dict]]:
    reasons: list[dict] = []

    if f["conf_high_frac"] > 0:
        reasons.append(_reason("conf_high_frac", "High-confidence detection", 10))

    if f["frp_max"] >= 50:
        reasons.append(_reason("frp_max", f"Intense heat ({f['frp_max']:.0f} MW)", 12))
    elif f["frp_max"] >= 10:
        reasons.append(_reason("frp_max", f"Moderate heat ({f['frp_max']:.0f} MW)", 6))

    if f["n_satellites"] >= 3:
        reasons.append(_reason("n_satellites", f"Seen by {f['n_satellites']} satellites", 14))
    elif f["n_satellites"] == 2:
        reasons.append(_reason("n_satellites", "Seen by 2 satellites", 8))

    if f["frp_growth"] >= 2:
        reasons.append(_reason("frp_growth", f"Heat grew {f['frp_growth']:.1f}x between passes", 8))

    g = f["gfdi"]
    if g >= 50:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 20))
    elif g >= 25:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 12))
    elif g >= 12:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 5))

    if f["gust_kmh"] >= 64:
        mph = f["gust_kmh"] / KMH_PER_MPH
        reasons.append(_reason("gust_kmh", f"Gusts {f['gust_kmh']:.0f} km/h ({mph:.0f} mph)", 8))

    if f["rh_pct"] <= 20:
        reasons.append(_reason("rh_pct", f"Humidity {f['rh_pct']:.0f}%", 6))

    if f["dist_town_km"] <= 3:
        reasons.append(_reason("dist_town_km", f"{f['dist_town_km']:.1f} km from a town", 8))
    elif f["dist_line_km"] <= 1:
        reasons.append(_reason("dist_line_km", f"{f['dist_line_km']:.1f} km from a transmission line", 8))

    if f["dist_static_km"] <= 1:
        reasons.append(_reason("dist_static_km", "At a known industrial heat source", -45))

    if f["in_flint_hills"] and f["month"] in (3, 4) and g < 12:
        reasons.append(_reason("in_flint_hills", "Flint Hills burn season, mild conditions", -20))

    if f["nearby_events_24h"] >= 5 and g < 12:
        reasons.append(_reason("nearby_events_24h", f"{f['nearby_events_24h']} other fires nearby on a mild day", -10))

    if f["precip_72h_mm"] >= 10:
        reasons.append(_reason("precip_72h_mm", f"{f['precip_72h_mm']:.0f} mm rain in past 72 h", -10))

    score = BASE_SCORE + sum(r["contribution"] for r in reasons)
    return max(0, min(100, score)), reasons
