"""Latest airport weather from the Iowa Environmental Mesonet (IEM) "currents" JSON service.

Docs: https://mesonet.agron.iastate.edu/api/1/docs  (operation GET /currents.json, params station, network).
Note: IEM lists Coldwater 3K8 as offline since 2022-04, so it returns no current row; that raises an error.
"""

from datetime import datetime, timezone

import httpx

CURRENTS_URL = "https://mesonet.agron.iastate.edu/api/1/currents.json"
STATIONS = ("3K8", "K51")  # Coldwater, Medicine Lodge
NETWORK = "KS_ASOS"
KT_TO_MPH = 1.15078


def _mph(knots) -> float | None:
    return None if knots is None else round(float(knots) * KT_TO_MPH, 1)


def parse_row(row: dict) -> dict:
    return {
        "station": row["station"],
        "obs_time": row["utc_valid"],
        "wind_mph": _mph(row.get("sknt")),
        "gust_mph": _mph(row.get("gust")),
        "wind_dir_deg": row.get("drct"),
        "rh_pct": row.get("relh"),
        "temp_f": row.get("tmpf"),
    }


def latest_obs(station: str, network: str = NETWORK) -> dict:
    """Latest observation for one station. Raises RuntimeError on any failure or if there is no current row."""
    try:
        resp = httpx.get(CURRENTS_URL, params={"station": station, "network": network}, timeout=20)
        resp.raise_for_status()
        rows = resp.json()["data"]
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"ASOS {station}: HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise RuntimeError(f"ASOS {station}: {type(e).__name__}") from None
    except (ValueError, KeyError, TypeError):
        raise RuntimeError(f"ASOS {station}: unexpected response") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise RuntimeError(f"ASOS {station}: malformed response")
    if not rows:
        raise RuntimeError(f"ASOS {station}: no current observation (station offline?)")
    try:
        obs = parse_row(rows[0])
        obs["age_min"] = round((datetime.now(timezone.utc) - datetime.strptime(
            obs["obs_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)).total_seconds() / 60, 1)
    except (KeyError, TypeError, ValueError):
        # A bad timestamp must fail this station only, not crash the whole poll.
        raise RuntimeError(f"ASOS {station}: unexpected response") from None
    return obs


def latest_observations(stations: tuple = STATIONS) -> dict:
    """{"observations": [obs, ...], "errors": {station: message}}: one bad station does not hide the others."""
    out: dict = {"observations": [], "errors": {}}
    for s in stations:
        try:
            out["observations"].append(latest_obs(s))
        except RuntimeError as e:
            out["errors"][s] = str(e)
    return out
