"""Short alert texts. Plain ASCII only, so they stay in GSM-7 and fit one SMS (160 characters)."""

from typing import Callable

from ..fire_weather import head_ros_kmh
from .common import KM_PER_MILE, compass8, crossroads, miles, road_phrase
from ..geo import bearing_deg

SMS_LIMIT = 160
REPLY = "Reply 1=on it 2=not a fire"


EXTENSION = set("^{}\\[]~|\u20ac")  # GSM-7 extension characters cost two septets


def septets(s: str) -> int:
    return sum(2 if c in EXTENSION else 1 for c in s)


def _ascii(s: str) -> str:
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("—", "-"), ("–", "-")):
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode().replace("?", "?")


def _motion(event: dict) -> tuple[str | None, float | None]:
    """Heading letter(s) and head speed in mph, from event keys or from the observed wind."""
    heading, speed = event.get("heading"), event.get("speed_mph")
    f = event.get("features") or {}
    if heading is None and "wind_dir_deg" in f:
        heading = compass8(f["wind_dir_deg"] + 180)
    if speed is None and "wind_kmh" in f:
        speed = head_ros_kmh(f["wind_kmh"], f.get("temp_c", 15.0), f.get("rh_pct", 50.0), f.get("curing_pct", 95.0)) / KM_PER_MILE
    return heading, speed


def chief_text(event: dict, place_name_fn: Callable[[float, float], str] | None = None) -> str:
    """Text to the chief. Optional event keys: score, heading, speed_mph, next_crossing {name, time}."""
    where = (place_name_fn or road_phrase)(event["lat"], event["lon"])
    heading, speed = _motion(event)
    parts = [f"FIRE {event.get('score', 0)}/100 {where}."]
    if heading and speed:
        parts.append(f"Head going {heading} ~{speed:.0f}mph.")
    nc = event.get("next_crossing")
    if nc:
        parts.append(f"{nc['name']} by {nc['time']}.")
    parts.append(REPLY)
    text = _ascii(" ".join(parts))
    if septets(text) > SMS_LIMIT:  # shorten the location first, never the reply line
        room = SMS_LIMIT - septets(text) + len(where)
        where = where[: max(room - 1, 10)].rstrip(" ,") + "."
        parts[0] = f"FIRE {event.get('score', 0)}/100 {where}"
        text = _ascii(" ".join(parts))
    return text


def landowner_text(place: dict, eta_local: str, event: dict | None = None) -> str:
    """Text to a landowner. Place may carry miles_from_fire and fire_dir_from_place (from in_path)."""
    mi, direction = place.get("miles_from_fire"), place.get("fire_dir_from_place")
    if (mi is None or direction is None) and event is not None:
        mi = miles(place["lat"], place["lon"], event["lat"], event["lon"])
        direction = compass8(bearing_deg(place["lat"], place["lon"], event["lat"], event["lon"]), words=True)
    heading = None
    if event is not None:
        h, _ = _motion(event)
        if h:
            heading = {"N": "north", "NE": "northeast", "E": "east", "SE": "southeast",
                       "S": "south", "SW": "southwest", "W": "west", "NW": "northwest"}[h]
    thing = {"house": "your house", "cattle": "your cattle", "water": "your tank battery"}.get(place.get("kind"), "your place")
    dist = f"{mi:.0f} mi {direction} of {thing}" if mi is not None else f"near {thing}"
    move = f", moving {heading}" if heading else ""
    return _ascii(
        f"Cottonwood Creek FD: grass fire {dist}{move}. Could reach you near {eta_local}. "
        "Reply 1 if you can move cattle or disc a line."
    )


def quiet_notice(event: dict) -> str:
    """Soft notice for a possible fire. No page."""
    trigger = event.get("trigger", "power-line fault")
    near = event.get("where") or crossroads(event["lat"], event["lon"])
    wx = event.get("weather") or {}
    red = event.get("red_flag", wx.get("red_flag", False))
    flag = " on a red flag day" if red else ""
    return _ascii(
        f"Possible fire: {trigger} near {near}{flag}. No smoke seen yet. We'll page if the satellite confirms."
    )
