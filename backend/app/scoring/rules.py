"""Points-based rules scorer (v0, and permanent fallback). See docs/DESIGN.md section 5.2."""

from ..fire_weather import gfdi_band

SCORER_NAME = "rules-v0"
BASE_SCORE = 30
KMH_PER_MPH = 1.609344


def _reason(feature: str, label: str, points: int, rank: int | None = None) -> dict:
    r = {"feature": feature, "label": label, "contribution": points}
    if rank is not None:
        r["rank"] = rank  # story reasons are shown first, in this order (see design/SCENARIO.md)
    return r


def _looks_text(clocks: list[str]) -> str:
    first, rest = clocks[0], clocks[1:]
    again = rest[0] if len(rest) == 1 else ", ".join(rest[:-1]) + " and " + rest[-1]
    return f"The satellite saw new heat at {first}, and again at {again}; it is growing"


def score_rules(f: dict) -> tuple[int, list[dict]]:
    reasons: list[dict] = []
    ctx = f.get("ctx") or {}
    red_flag = bool(f.get("red_flag"))
    has_signal = bool(f.get("line_fault") or f.get("n_reports"))

    # Dispatch's burn log: a detection on a burn called in for this time is almost certainly that burn.
    if f.get("burn_match"):
        reasons.append(_reason(
            "burn_match", f"Matches a burn called in to dispatch at {ctx['burn']['called_in_clock']}", -50, rank=1))

    if f.get("burn_escape"):
        reasons.append(_reason(
            "burn_escape", f"Near a burn called in at {ctx['burn']['called_in_clock']}, but growing past it. Call the burner.",
            10, rank=1))

    if f.get("line_fault"):
        fa = ctx["fault"]
        base = f"A power-line fault on the {fa['circuit']} at {fa['clock']}"
        if f["fault_corroborated"] and fa["miles"] is not None:
            reasons.append(_reason("line_fault", f"{base}, {fa['miles']:.1f} mi away", 20, rank=1))
        elif f["n_detections"] == 0:
            reasons.append(_reason("line_fault", f"{base}. No satellite has seen heat yet", 12, rank=1))
        else:
            reasons.append(_reason("line_fault", base, 8, rank=1))

    # Repeat looks with growing heat replace the plain "heat grew" rule when a signal or Red Flag backs them.
    looks_story = (has_signal or red_flag) and f.get("n_looks", 0) >= 2 and f.get("looks_growing")
    if looks_story:
        reasons.append(_reason("looks_growing", _looks_text(ctx["look_clocks"]), 12, rank=2))

    if red_flag:
        mph = f["wind_kmh"] / KMH_PER_MPH
        gust = f["gust_kmh"] / KMH_PER_MPH
        reasons.append(_reason(
            "red_flag", f"Red Flag Warning: wind {mph:.0f} mph gusting {gust:.0f}, humidity {f['rh_pct']:.0f}%", 14, rank=3))

    if f.get("no_burn_near"):
        reasons.append(_reason("no_burn_near", "No burn has been called in near here", 3, rank=4))

    if f.get("n_reports"):
        rp = ctx["report"]
        away = f", {rp['miles']:.1f} mi away" if rp["miles"] is not None else ""
        corroborating = f["n_detections"] > 0 or f.get("line_fault")
        reasons.append(_reason("report", f"A person reported smoke at {rp['clock']}{away}", 3 if corroborating else 15, rank=5))

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

    if f["frp_growth"] >= 2 and not looks_story:
        reasons.append(_reason("frp_growth", f"Heat grew {f['frp_growth']:.1f}x between passes", 8))

    g = f["gfdi"]
    if red_flag:
        pass  # the Red Flag reason already carries wind, gusts and humidity
    elif g >= 50:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 20))
    elif g >= 25:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 12))
    elif g >= 12:
        reasons.append(_reason("gfdi", f"Fire danger {gfdi_band(g)} ({g:.0f})", 5))

    if f["gust_kmh"] >= 64 and not red_flag:
        mph = f["gust_kmh"] / KMH_PER_MPH
        reasons.append(_reason("gust_kmh", f"Gusts {f['gust_kmh']:.0f} km/h ({mph:.0f} mph)", 8))

    if f["rh_pct"] <= 20 and not red_flag:
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
