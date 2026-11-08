"""Create the server's FW1 signing key (docs/mobile/FW1-CODEC.md, "Signatures") and print its public key.

    .venv/bin/python -m scripts.make_signing_key            # writes FW1_SIGNING_KEY_FILE (default data/keys/fw1_ed25519.pem)

The private key never leaves the server and is git-ignored. Put the printed public key in mobile/app.json under
expo.extra.fw1Keys, so the phone app trusts codes and region packs signed with it. Refuses to overwrite a key:
replacing it means every phone needs an app update before it trusts new codes.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from app import fw1  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=None, help=f"key file (default: ${fw1.KEY_ENV} or {fw1.DEFAULT_KEY_FILE})")
    ap.add_argument("--id", default="firewatch-demo-2026-11", help="the key id to put in app.json")
    a = ap.parse_args(argv)
    path = a.out or fw1.key_path()
    if path.exists():
        print(f"{path} already exists; not replacing it.", file=sys.stderr)
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    else:
        key = Ed25519PrivateKey.generate()
        pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
        print(f"Wrote {path} (keep it secret; it is git-ignored).", file=sys.stderr)
    print(f'{{ "id": "{a.id}", "key": "{fw1.public_key_b64(key)}" }}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
