"""Reference encoder/decoder for the FW1 alert code (see FW1-CODEC.md). Generates codec-vectors.json.

Run: python3 fw1_reference.py   (writes codec-vectors.json next to this file)

Signatures (FW1-CODEC.md "Signatures"): Ed25519 over the 12-field code, appended as a 13th field in base64url with
no padding. Ed25519 here is the RFC 8032 section 6 reference code, in plain Python with no dependencies, so the
vectors can be checked against any other Ed25519 (the backend tests check them against `cryptography`).
"""
import base64
import hashlib
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


# --- Ed25519 (RFC 8032 section 6) ---------------------------------------------------------------------------
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, -1, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512(b: bytes) -> bytes:
    return hashlib.sha512(b).digest()


def _add(P, Q):
    A, B = (P[1] - P[0]) * (Q[1] - Q[0]) % _P, (P[1] + P[0]) * (Q[1] + Q[0]) % _P
    C, D = 2 * P[3] * Q[3] * _D % _P, 2 * P[2] * Q[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def _mul(s: int, P):
    Q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            Q = _add(Q, P)
        P = _add(P, P)
        s >>= 1
    return Q


def _equal(P, Q) -> bool:
    return (P[0] * Q[2] - Q[0] * P[2]) % _P == 0 and (P[1] * Q[2] - Q[1] * P[2]) % _P == 0


def _recover_x(y: int, sign: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, -1, _P)
    if x2 % _P == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    return _P - x if (x & 1) != sign else x


_GY = 4 * pow(5, -1, _P) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(P) -> bytes:
    zinv = pow(P[2], -1, _P)
    x, y = P[0] * zinv % _P, P[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(b: bytes):
    y = int.from_bytes(b, "little")
    sign, y = y >> 255, y & ((1 << 255) - 1)
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _expand(seed: bytes):
    h = _sha512(seed)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(seed: bytes) -> bytes:
    return _compress(_mul(_expand(seed)[0], _G))


def ed25519_sign(seed: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(seed)
    A = _compress(_mul(a, _G))
    r = int.from_bytes(_sha512(prefix + msg), "little") % _L
    R = _compress(_mul(r, _G))
    h = int.from_bytes(_sha512(R + A + msg), "little") % _L
    return R + int.to_bytes((r + h * a) % _L, 32, "little")


def ed25519_verify(public: bytes, msg: bytes, sig: bytes) -> bool:
    if len(public) != 32 or len(sig) != 64:
        return False
    A, R = _decompress(public), _decompress(sig[:32])
    s = int.from_bytes(sig[32:], "little")
    if A is None or R is None or s >= _L:
        return False
    h = int.from_bytes(_sha512(sig[:32] + public + msg), "little") % _L
    return _equal(_mul(s, _G), _add(R, _mul(h, A)))


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64url(s: str) -> bytes:
    """Strict: only A-Z a-z 0-9 - _, no padding, and the unused low bits of the last character must be zero."""
    if any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in s) or len(s) % 4 == 1:
        raise ValueError("bad base64url")
    b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    if b64url(b) != s:
        raise ValueError("bad base64url")
    return b


def sign_code(code: str, seed: bytes) -> str:
    """Append the 13th field: base64url Ed25519 over the ASCII 12-field code (chk included). Always 86 characters."""
    return code + "." + b64url(ed25519_sign(seed, code.encode("ascii")))


def pack_message(code: str, version: str, sha256_hex: str) -> bytes:
    return f"fwpack/1|{code}|{version}|{sha256_hex.lower()}".encode("ascii")


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


def decode(code: str, origin: tuple[float, float], keys: list[bytes] = ()) -> dict:
    """`keys`: trusted Ed25519 public keys. A `sig` that does not verify with one of them is refused."""
    parts = code.split(".")
    verified = False
    if len(parts) == 13 and parts[0] == "FW1":
        sig = unb64url(parts[12]) if len(parts[12]) == 86 else b""
        body12 = ".".join(parts[:12])
        if len(sig) != 64 or not any(ed25519_verify(k, body12.encode("ascii"), sig) for k in keys):
            raise ValueError("signature does not verify")
        parts, verified = parts[:12], True
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
        "verified": verified,
    }


# TEST-ONLY keys: anyone can read these seeds, so nothing outside tests may ever trust them.
TEST_SEED = hashlib.sha256(b"firewatch fw1 TEST-ONLY signing seed; never trust outside tests").digest()
OTHER_TEST_SEED = hashlib.sha256(b"firewatch fw1 TEST-ONLY other seed; a key nobody trusts").digest()


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

    pub = ed25519_public(TEST_SEED)
    signed = []
    for v in vectors:
        sc = sign_code(v["code"], TEST_SEED)
        assert len(sc.split(".")[12]) == 86 and len(sc) <= 126
        assert decode(sc, origin, [pub])["verified"] and ed25519_verify(pub, v["code"].encode(), unb64url(sc.split(".")[12]))
        signed.append({"code": v["code"], "signed": sc})
    s1 = signed[1]["signed"]
    sig1 = s1.split(".")[12]
    flipped = sig1[:40] + ("A" if sig1[40] != "A" else "B") + sig1[41:]
    other_key = sign_code(vectors[1]["code"], OTHER_TEST_SEED)
    changed = encode({**vectors[1]["input"], "score": 99}, origin)  # same alert, one field changed, good checksum
    moved = changed + "." + sig1
    reject_signed = [
        {"why": "one character of sig changed", "code": vectors[1]["code"] + "." + flipped},
        {"why": "valid sig from a key that is not trusted", "code": other_key},
        {"why": "valid sig moved onto a code with a changed field", "code": moved},
    ]
    for r in reject_signed:
        try:
            decode(r["code"], origin, [pub])
        except ValueError:
            continue
        raise AssertionError(r)
    pack_sha = hashlib.sha256(b"example pack bytes").hexdigest()
    pack_sig = b64url(ed25519_sign(TEST_SEED, pack_message("cwc", "2026-11-07.1", pack_sha)))
    out["signing"] = {
        "note": "TEST-ONLY key. The seed is public, so no app or server may ever trust this key outside tests.",
        "algorithm": "Ed25519 (RFC 8032) over the ASCII 12-field code; sig is base64url without padding (86 chars)",
        "test_only_seed_hex": TEST_SEED.hex(),
        "test_only_public_key": b64url(pub),
        "vectors": signed,
        "must_reject_signed": reject_signed,
        "pack": {"code": "cwc", "version": "2026-11-07.1", "sha256": pack_sha,
                 "message": pack_message("cwc", "2026-11-07.1", pack_sha).decode(), "sig": pack_sig},
    }
    Path(__file__).with_name("codec-vectors.json").write_text(json.dumps(out, indent=2) + "\n")
    for v in signed:
        print(len(v["signed"]), v["signed"])
