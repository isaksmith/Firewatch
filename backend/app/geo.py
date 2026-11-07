import math

EARTH_RADIUS_KM = 6371.0088
KM_PER_MILE = 1.609344

COMPASS_16 = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from north."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def compass(deg: float) -> str:
    return COMPASS_16[int((deg % 360) / 22.5 + 0.5) % 16]


def km_per_deg_lon(lat: float) -> float:
    return 111.320 * math.cos(math.radians(lat))


KM_PER_DEG_LAT = 110.574


def point_segment_km(lat: float, lon: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from a point to segment a-b (each (lon, lat)) using a local equirectangular projection."""
    kx = km_per_deg_lon(lat)
    px, py = 0.0, 0.0
    ax, ay = (a[0] - lon) * kx, (a[1] - lat) * KM_PER_DEG_LAT
    bx, by = (b[0] - lon) * kx, (b[1] - lat) * KM_PER_DEG_LAT
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(cx - px, cy - py)


def angle_diff(a: float, b: float) -> float:
    """Signed smallest difference b - a between two bearings, in (-180, 180]."""
    d = (b - a) % 360
    return d - 360 if d > 180 else d
