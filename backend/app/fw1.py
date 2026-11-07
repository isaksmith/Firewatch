"""FW1: the fire update code for phones with almost no signal (docs/mobile/FW1-CODEC.md).

One alert change fits in about 40 characters: `FW1.<pack>.<kind><level>.<id>.<score>.<dlat>.<dlon>.<t>.<dir>.<spd>.<flags>.<chk>`.
The format is fixed by the spec and the test vectors in docs/mobile/codec-vectors.json; do not change it here.

Signatures ("Signatures" in the spec): every code the server sends gets a 13th field, `sig`, an Ed25519 signature
over the 12-field code in base64url without padding, when the private key file exists (FW1_SIGNING_KEY_FILE,
default backend/data/keys/fw1_ed25519.pem, git-ignored). Without it codes go out unsigned. Region pack index
entries are signed the same way over `fwpack/1|<code>|<version>|<sha256>`.
"""

import base64
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .config import BACKEND_DIR

log = logging.getLogger(__name__)
KEY_ENV = "FW1_SIGNING_KEY_FILE"
DEFAULT_KEY_FILE = BACKEND_DIR / "data" / "keys" / "fw1_ed25519.pem"
SIG_LEN = 86  # base64url of 64 bytes, no padding
_B64URL = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")

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


def decode(code: str, origin: tuple[float, float], keys: list | None = None) -> dict:
    """Raises ValueError for anything that is not a good FW1 code (wrong version, shape, checksum, or signature).

    A signed code must verify with one of `keys` (raw 32-byte Ed25519 public keys; default: the server's own key).
    The result's `verified` says whether it carried a good signature."""
    parts = code.split(".")
    verified = False
    if len(parts) == 13 and parts[0] == "FW1":
        body12 = ".".join(parts[:12])
        if keys is None:
            own = signing_key()
            keys = [public_key_bytes(own)] if own else []
        if not any(verify(k, body12, parts[12]) for k in keys):
            raise ValueError("signature does not verify")
        parts, verified = parts[:12], True
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
        "verified": verified,
    }


# --- signatures ------------------------------------------------------------------------------------------------


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def unb64url(s: str) -> bytes:
    """Strict base64url without padding: a non-canonical last character is refused, so one signature has one spelling."""
    if not s or any(c not in _B64URL for c in s) or len(s) % 4 == 1:
        raise ValueError("bad base64url")
    b = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    if b64url(b) != s:
        raise ValueError("bad base64url")
    return b


def key_path() -> Path:
    return Path(os.environ.get(KEY_ENV) or DEFAULT_KEY_FILE)


_key_lock = threading.Lock()
_key_cache: dict = {}


def signing_key():
    """The server's Ed25519 private key, or None when the key file is missing or unreadable. Re-read if the file changes."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    path = key_path()
    try:
        st = path.stat()
    except OSError:
        return None
    stamp = (str(path), st.st_mtime_ns, st.st_size)
    with _key_lock:
        if _key_cache.get("stamp") == stamp:
            return _key_cache["key"]
        try:
            key = serialization.load_pem_private_key(path.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError("not an Ed25519 key")
        except Exception as e:  # a broken key file must not stop alerts: they go out unsigned
            log.error("FW1 signing key %s could not be read (%s); FW1 codes go out unsigned", path, type(e).__name__)
            key = None
        _key_cache.update(stamp=stamp, key=key)
        return key


def public_key_bytes(key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def public_key_b64(key) -> str:
    return b64url(public_key_bytes(key))


def signing_status() -> str:
    """One line for the startup log."""
    key = signing_key()
    if key is None:
        return f"FW1 codes go out unsigned: no signing key at {key_path()} (create one with scripts/make_signing_key.py)"
    return f"FW1 codes are signed (public key {public_key_b64(key)})"


def sign_text(text: str, key=None) -> str | None:
    key = key if key is not None else signing_key()
    return None if key is None else b64url(key.sign(text.encode("ascii")))


def sign(code: str, key=None) -> str:
    """The code with `.<sig>` appended, or the code unchanged when there is no key. Never signs twice."""
    if len(code.split(".")) != 12:
        return code
    sig = sign_text(code, key)
    return code if sig is None else f"{code}.{sig}"


def verify(public: bytes, text: str, sig: str) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if len(sig) != SIG_LEN or not text.isascii():
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public).verify(unb64url(sig), text.encode("ascii"))
        return True
    except (InvalidSignature, ValueError):
        return False


def pack_message(code: str, version: str, sha256_hex: str) -> str:
    return f"fwpack/1|{code}|{version}|{sha256_hex.lower()}"
