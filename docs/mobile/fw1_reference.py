"""Reference encoder/decoder for the FW1 alert code (see FW1-CODEC.md). Generates codec-vectors.json.

Run: python3 fw1_reference.py   (writes codec-vectors.json next to this file)
"""
import json
from datetime import datetime, timezone
from pathlib import Path

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
KINDS = {"alert": "a", "clear": "c", "notfire": "x"}
LEVELS = {"escalate": "e", "investigate": "i", "monitor": "m"}
FLAGS = {"red_flag": 1, "homes_in_path": 2, "exercise": 4, "mutual_aid": 8, "two_sources": 16}


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
    return -unb36(s[1:]) if s.startswith("-") else int(s, 36)


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


def encode(a: dict, origin: tuple[float, float]) -> str:
    t = int((datetime.fromisoformat(a["time"].replace("Z", "+00:00")) - EPOCH).total_seconds() // 60)
    fields = [
        "FW1",
        a["pack"],
        KINDS[a["kind"]] + LEVELS[a["level"]],
        b36(a["id"]),
        b36(a["score"]),
        b36(round((a["lat"] - origin[0]) * 1e4)),
        b36(round((a["lon"] - origin[1]) * 1e4)),
        b36(t),
        "" if a.get("toward_deg") is None else b36(round(a["toward_deg"] / 5) % 72),
        "" if a.get("mph") is None else b36(round(a["mph"] * 2)),
        b36(sum(FLAGS[f] for f in a.get("flags", []))),
    ]
    body = ".".join(fields)
    return body + "." + check(body)


def decode(code: str, origin: tuple[float, float]) -> dict:
    parts = code.split(".")
    if len(parts) != 12 or parts[0] != "FW1":
        raise ValueError("not an FW1 code")
    body, chk = ".".join(parts[:11]), parts[11]
    if check(body) != chk:
        raise ValueError("checksum mismatch")
    _, pack, kl, id_, score, dlat, dlon, t, d, spd, flags = parts[:11]
    kinds = {v: k for k, v in KINDS.items()}
    levels = {v: k for k, v in LEVELS.items()}
    fl = unb36(flags)
    minutes = unb36(t)
    return {
        "pack": pack,
        "kind": kinds[kl[0]],
        "level": levels[kl[1]],
        "id": unb36(id_),
        "score": unb36(score),
        "lat": round(origin[0] + unb36(dlat) / 1e4, 4),
        "lon": round(origin[1] + unb36(dlon) / 1e4, 4),
        "time": (EPOCH.timestamp() + minutes * 60),
        "toward_deg": None if d == "" else unb36(d) * 5,
        "mph": None if spd == "" else unb36(spd) / 2,
        "flags": [f for f, bit in FLAGS.items() if fl & bit],
    }


if __name__ == "__main__":
    origin = (37.2689, -99.3268)  # pack "cwc": Cottonwood Creek station 1 (Coldwater stand-in)
    cases = [
        {"pack": "cwc", "kind": "alert", "level": "investigate", "id": 12, "score": 45, "lat": 37.3821, "lon": -99.4681,
         "time": "2026-03-17T18:51:00Z", "toward_deg": None, "mph": None, "flags": ["red_flag", "exercise"]},
        {"pack": "cwc", "kind": "alert", "level": "escalate", "id": 12, "score": 88, "lat": 37.3821, "lon": -99.4681,
         "time": "2026-03-17T19:05:00Z", "toward_deg": 0, "mph": 3.0,
         "flags": ["red_flag", "homes_in_path", "exercise", "two_sources"]},
        {"pack": "cwc", "kind": "alert", "level": "escalate", "id": 12, "score": 91, "lat": 37.3902, "lon": -99.4655,
         "time": "2026-03-17T19:20:00Z", "toward_deg": 10, "mph": 7.5,
         "flags": ["red_flag", "homes_in_path", "exercise", "mutual_aid", "two_sources"]},
        {"pack": "cwc", "kind": "clear", "level": "monitor", "id": 12, "score": 20, "lat": 37.3902, "lon": -99.4655,
         "time": "2026-03-17T23:40:00Z", "toward_deg": None, "mph": None, "flags": ["exercise"]},
        {"pack": "cwc", "kind": "notfire", "level": "monitor", "id": 1295, "score": 0, "lat": 37.1500, "lon": -99.2001,
         "time": "2026-03-17T17:10:00Z", "toward_deg": 355, "mph": 0.5, "flags": []},
    ]
    vectors = []
    for c in cases:
        code = encode(c, origin)
        d = decode(code, origin)
        assert d["id"] == c["id"] and d["score"] == c["score"] and d["lat"] == c["lat"] and d["lon"] == c["lon"]
        vectors.append({"input": c, "code": code, "decoded_time_iso": datetime.fromtimestamp(d["time"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    bad = vectors[1]["code"][:-1] + ("0" if vectors[1]["code"][-1] != "0" else "1")
    out = {"origin": {"pack": "cwc", "lat": origin[0], "lon": origin[1]}, "vectors": vectors,
           "must_reject": [bad, "FW1.cwc.ae.c", "FW2" + vectors[1]["code"][3:], ""]}
    Path(__file__).with_name("codec-vectors.json").write_text(json.dumps(out, indent=2) + "\n")
    for v in vectors:
        print(len(v["code"]), v["code"])
