"""Read a bearing and distance out of the text after FIRE ("5 MI NW", "N 5") and place the report there.

Pure functions. The whole text must be the pair, so "NEAR THE HOUSE" and "S 5 ACRES ON FIRE" never place a report. A direction
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
_DIR = "|".join(sorted(_DIRECTIONS, key=len, reverse=True))
_NUM = r"\d+(?:\.\d+)?"
_UNIT = r"(?:\s*(?:MILES|MILE|MI))?"
# The whole trimmed text, nothing else: "<dir> <num>[ unit]" or "<num>[ unit] <dir>".
_PATTERN = re.compile(
    rf"(?:(?P<d1>{_DIR})\s+(?P<n1>{_NUM}){_UNIT}|(?P<n2>{_NUM}){_UNIT}\s+(?P<d2>{_DIR}))"
)


@dataclass(frozen=True)
class Where:
    bearing: float
    miles: float

    @property
    def label(self) -> str:
        return f"{self.miles:g} mi {compass(self.bearing)}"


def parse_where(text: str | None) -> Where | None:
    """Parse the text after FIRE into a bearing and distance, or None when it has no usable pair.

    The whole text must be a direction and a distance, either order, with an optional MI/MILES unit after
    the number. Any other word means no parse.
    """
    if not text:
        return None
    m = _PATTERN.fullmatch(text.strip().upper())
    if not m:
        return None
    miles = float(m["n1"] or m["n2"])
    if not 0 < miles <= MAX_MILES:
        return None
    return Where(_DIRECTIONS[m["d1"] or m["d2"]], miles)


def point_from(lat: float, lon: float, w: Where) -> tuple[float, float]:
    """The point `w.miles` from (lat, lon) along `w.bearing` (great circle on the spherical earth)."""
    ang = w.miles * KM_PER_MILE / EARTH_RADIUS_KM
    b = math.radians(w.bearing)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(ang) * math.cos(p1), math.cos(ang) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180
