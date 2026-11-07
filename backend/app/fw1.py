"""FW1: the fire update code for phones with almost no signal (docs/mobile/FW1-CODEC.md).

One alert change fits in about 40 characters: `FW1.<pack>.<kind><level>.<id>.<score>.<dlat>.<dlon>.<t>.<dir>.<spd>.<flags>.<chk>`.
The format is fixed by the spec and the test vectors in docs/mobile/codec-vectors.json; do not change it here.
"""

from datetime import datetime, timezone

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
KINDS = {"alert": "a", "clear": "c", "notfire": "x"}
LEVELS = {"escalate": "e", "investigate": "i", "monitor": "m"}
FLAGS = {"red_flag": 1, "homes_in_path": 2, "exercise": 4, "mutual_aid": 8, "two_sources": 16}
_KIND_BY_CODE = {v: k for k, v in KINDS.items()}
_LEVEL_BY_CODE = {v: k for k, v in LEVELS.items()}
_B36 = set(DIGITS)


def b36(n: int) -> str:
    if n < 0:
        return "-" + b36(-n)
    s = ""
    while True:
        n, r = divmod(n, 36)
        s = DIGITS[r] + s
        if n == 0:
            return s


def unb36(s: str) -> int:
    body = s[1:] if s.startswith("-") else s
    if not body or any(c not in _B36 for c in body):
        raise ValueError("bad number")
    return -int(body, 36) if s.startswith("-") else int(body, 36)


def crc16(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, no reflection, no xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def check(body: str) -> str:
    return b36(crc16(body.encode("ascii")) % 46656).rjust(3, "0")


def minutes_since_epoch(time: str | datetime) -> int:
    if isinstance(time, str):
        time = datetime.fromisoformat(time.replace("Z", "+00:00"))
    return int((time - EPOCH).total_seconds() // 60)


def encode(a: dict, origin: tuple[float, float]) -> str:
    """`a`: pack, kind (alert|clear|notfire), level (escalate|investigate|monitor), id, score, lat, lon,
    time (ISO string or datetime), optional toward_deg and mph (None = unknown), flags (names). origin is (lat, lon)."""
    fields = [
        "FW1",
        a["pack"],
        KINDS[a["kind"]] + LEVELS[a["level"]],
        b36(a["id"]),
        b36(a["score"]),
        b36(round((a["lat"] - origin[0]) * 1e4)),
        b36(round((a["lon"] - origin[1]) * 1e4)),
        b36(minutes_since_epoch(a["time"])),
        "" if a.get("toward_deg") is None else b36(round(a["toward_deg"] / 5) % 72),
        "" if a.get("mph") is None else b36(round(a["mph"] * 2)),
        b36(sum(FLAGS[f] for f in a.get("flags", []))),
    ]
    body = ".".join(fields)
    return body + "." + check(body)


def decode(code: str, origin: tuple[float, float]) -> dict:
    """Raises ValueError for anything that is not a good FW1 code (wrong version, shape, or checksum)."""
    parts = code.split(".")
    if len(parts) != 12 or parts[0] != "FW1":
        raise ValueError("not an FW1 code")
    body, chk = ".".join(parts[:11]), parts[11]
    if not body.isascii() or check(body) != chk:
        raise ValueError("checksum mismatch")
    _, pack, kl, id_, score, dlat, dlon, t, d, spd, flags = parts[:11]
    if len(kl) != 2 or kl[0] not in _KIND_BY_CODE or kl[1] not in _LEVEL_BY_CODE:
        raise ValueError("bad kind or level")
    fl, minutes = unb36(flags), unb36(t)
    return {
        "pack": pack,
        "kind": _KIND_BY_CODE[kl[0]],
        "level": _LEVEL_BY_CODE[kl[1]],
        "id": unb36(id_),
        "score": unb36(score),
        "lat": round(origin[0] + unb36(dlat) / 1e4, 4),
        "lon": round(origin[1] + unb36(dlon) / 1e4, 4),
        "time": EPOCH.timestamp() + minutes * 60,
        "toward_deg": None if d == "" else unb36(d) * 5,
        "mph": None if spd == "" else unb36(spd) / 2,
        "flags": [f for f, bit in FLAGS.items() if fl & bit],
    }
