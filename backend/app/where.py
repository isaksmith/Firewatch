"""Read a bearing and distance out of the text after FIRE ("5 MI NW", "N 5") and place the report there.

Pure functions. Whole tokens only, so "NEAR THE HOUSE" and "NO SMOKE" never read as a direction. A direction
with no distance is not placed: a distance is never guessed.
"""

import math
import re
from dataclasses import dataclass

from .geo import EARTH_RADIUS_KM, KM_PER_MILE, compass

MAX_MILES = 25.0

_DIRECTIONS = {
    "N": 0.0, "NORTH": 0.0,
    "NE": 45.0, "NORTHEAST": 45.0,
    "E": 90.0, "EAST": 90.0,
    "SE": 135.0, "SOUTHEAST": 135.0,
    "S": 180.0, "SOUTH": 180.0,
    "SW": 225.0, "SOUTHWEST": 225.0,
    "W": 270.0, "WEST": 270.0,
    "NW": 315.0, "NORTHWEST": 315.0,
}
_UNITS = {"MI", "MILE", "MILES"}
_TOKEN = re.compile(r"\d+(?:\.\d+)?|[A-Z]+")


@dataclass(frozen=True)
class Where:
    bearing: float
    miles: float

    @property
    def label(self) -> str:
        return f"{self.miles:g} mi {compass(self.bearing)}"


def parse_where(text: str | None) -> Where | None:
    """Parse the text after FIRE into a bearing and distance, or None when it has no usable pair.

    The distance must sit next to the direction (an optional MI/MILES between), either side.
    """
    if not text:
        return None
    toks = _TOKEN.findall(text.upper())
    dirs = [i for i, t in enumerate(toks) if t in _DIRECTIONS]
    nums = [i for i, t in enumerate(toks) if t[0].isdigit()]
    if len(dirs) != 1 or len(nums) != 1:
        return None
    d, n = dirs[0], nums[0]
    if n < d:  # "5 MI NW"
        between = toks[n + 1:d]
    else:  # "NW 5"
        between = toks[d + 1:n]
    if len(between) > 1 or (between and between[0] not in _UNITS):
        return None
    miles = float(toks[n])
    if not 0 < miles <= MAX_MILES:
        return None
    return Where(_DIRECTIONS[toks[d]], miles)


def point_from(lat: float, lon: float, w: Where) -> tuple[float, float]:
    """The point `w.miles` from (lat, lon) along `w.bearing` (great circle on the spherical earth)."""
    ang = w.miles * KM_PER_MILE / EARTH_RADIUS_KM
    b = math.radians(w.bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(ang) * math.cos(p1), math.cos(ang) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180
