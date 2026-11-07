"""Signed FW1 codes and signed region packs (docs/mobile/FW1-CODEC.md, "Signatures")."""

import importlib.util
import json
import logging
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi.testclient import TestClient

from app import fw1, mesh

DOCS = Path(__file__).resolve().parents[2] / "docs" / "mobile"
VECTORS = json.loads((DOCS / "codec-vectors.json").read_text())
SIGNING = VECTORS["signing"]
ORIGIN = (VECTORS["origin"]["lat"], VECTORS["origin"]["lon"])
TEST_KEY = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SIGNING["test_only_seed_hex"]))
TEST_PUB = fw1.public_key_bytes(TEST_KEY)
GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
)


@pytest.fixture
def test_key_file(tmp_path, monkeypatch):
    path = tmp_path / "fw1_test.pem"
    path.write_bytes(TEST_KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()))
    monkeypatch.setenv(fw1.KEY_ENV, str(path))
    return path


@pytest.fixture
def no_key_file(tmp_path, monkeypatch):
    monkeypatch.setenv(fw1.KEY_ENV, str(tmp_path / "missing.pem"))


def test_reference_ed25519_matches_cryptography():
    assert fw1.b64url(TEST_PUB) == SIGNING["test_only_public_key"]
    spec = importlib.util.spec_from_file_location("fw1_reference", DOCS / "fw1_reference.py")
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    assert ref.ed25519_public(bytes.fromhex(SIGNING["test_only_seed_hex"])) == TEST_PUB


@pytest.mark.parametrize("v", SIGNING["vectors"], ids=lambda v: v["code"])
def test_signed_vectors_match_the_reference(v):
    assert fw1.sign(v["code"], TEST_KEY) == v["signed"]
    assert fw1.sign(v["signed"], TEST_KEY) == v["signed"]  # never signs twice
    sig = v["signed"].split(".")[12]
    assert len(sig) == 86 and len(v["signed"]) <= 126
    d = fw1.decode(v["signed"], ORIGIN, [TEST_PUB])
    plain = fw1.decode(v["code"], ORIGIN, [TEST_PUB])
    assert d["verified"] is True and plain["verified"] is False
    assert {k: x for k, x in d.items() if k != "verified"} == {k: x for k, x in plain.items() if k != "verified"}


@pytest.mark.parametrize("r", SIGNING["must_reject_signed"], ids=lambda r: r["why"])
def test_must_reject_signed(r):
    with pytest.raises(ValueError):
        fw1.decode(r["code"], ORIGIN, [TEST_PUB])


def test_bad_sig_shapes_are_refused():
    good = SIGNING["vectors"][1]["signed"]
    body, sig = good.rsplit(".", 1)
    last = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    i = last.index(sig[-1])
    noncanonical = sig[:-1] + last[i ^ 1]  # same 64 bytes, different spelling (the unused low bits)
    for bad in (f"{body}.{sig[:-1]}", f"{body}.{sig}A", f"{body}.{sig[:-1]}=", f"{body}.{noncanonical}", f"{body}.", good + ".x"):
        with pytest.raises(ValueError):
            fw1.decode(bad, ORIGIN, [TEST_PUB])
    with pytest.raises(ValueError):
        fw1.decode(good, ORIGIN, [])  # signed but nobody trusted


def test_pack_signature_vector():
    p = SIGNING["pack"]
    assert fw1.pack_message(p["code"], p["version"], p["sha256"]) == p["message"]
    assert fw1.sign_text(p["message"], TEST_KEY) == p["sig"]
    assert fw1.verify(TEST_PUB, p["message"], p["sig"])


PACK_CODES = ["cwc", "ks-barber", "ks-clark", "ks-comanche"]
assert {p["code"] for p in json.loads((Path(__file__).resolve().parents[1] / "data" / "packs" / "index.json").read_text())} == set(PACK_CODES)


def _worst_code(pack: str) -> str:
    """Every field at the most the phone accepts (FW1-CODEC.md ranges: |dlat|,|dlon| <= 100000, t before 2100,
    speed <= 400 half-mph, flags 31, score 100), with an event id of six base-36 digits (over 2 billion)."""
    return fw1.encode(
        {"pack": pack, "kind": "alert", "level": "escalate", "id": 36**6 - 1, "score": 100,
         "lat": ORIGIN[0] - 10.0, "lon": ORIGIN[1] - 10.0, "time": "2099-12-31T23:59:00Z",
         "toward_deg": 355, "mph": 200.0, "flags": list(fw1.FLAGS)},
        ORIGIN,
    )


@pytest.mark.parametrize("pack", PACK_CODES)
def test_worst_case_app_link_fits_one_sms_per_pack(pack, test_key_file):
    from app import notify

    code = _worst_code(pack)
    text = notify.app_link_text(code)
    assert text is not None, (len(notify.APP_LINK_PREFIX + fw1.sign(code)), code)
    assert len(text) <= 160 and set(text) <= GSM7, (len(text), text)
    signed = text.removeprefix(notify.APP_LINK_PREFIX)
    assert len(signed.split(".")) == 13 and len(signed) <= 146
    assert fw1.decode(signed, ORIGIN, [TEST_PUB])["verified"]
    assert mesh._fit(signed) == signed and len(signed.encode()) <= mesh.MESH_MAX_BYTES


def test_truncation_never_cuts_into_a_signed_code(test_key_file):
    from app import notify

    signed = fw1.sign(_worst_code("ks-comanche"))
    contact = {"opted_in": 1, "phone": "+15550100", "mesh_id": None, "id": 1, "name": "x", "app": 1}
    for body in ("Fire update: " + "x" * 40 + " " + signed, notify.APP_LINK_PREFIX + signed + " " + "y" * 20):
        assert len(body) > notify.SMS_MAX
        with pytest.raises(ValueError, match="must not be truncated"):
            notify.send(None, contact, body, "app_link", None, None, True, channels=("sms",))
    # a code too long for one SMS gives no link at all, never a cut one
    assert notify.app_link_text(fw1.encode({**fw1.decode(_worst_code("cwc"), ORIGIN), "pack": "x" * 20,
                                            "time": "2099-12-31T23:59:00Z"}, ORIGIN)) is None


def test_key_file_signs_and_missing_key_does_not(test_key_file, monkeypatch, tmp_path):
    code = SIGNING["vectors"][0]["code"]
    assert fw1.sign(code) == SIGNING["vectors"][0]["signed"]
    monkeypatch.setenv(fw1.KEY_ENV, str(tmp_path / "missing.pem"))
    assert fw1.signing_key() is None and fw1.sign(code) == code
    assert "unsigned" in fw1.signing_status()
    bad = tmp_path / "broken.pem"
    bad.write_text("not a key")
    monkeypatch.setenv(fw1.KEY_ENV, str(bad))
    assert fw1.signing_key() is None and fw1.sign(code) == code


def test_feed_app_link_and_radio_carry_signed_codes(test_key_file):
    from app import scenario
    from app.db import connect
    from app.main import app

    with TestClient(app) as client:
        scenario.run_now("cottonwood-creek")
        lines = client.get("/api/m/feed?pack=cwc&since=0").text.strip().split("\n")
    codes = [l.split(" ")[1] for l in lines]
    assert codes and all(len(c.split(".")) == 13 for c in codes)
    assert all(fw1.decode(c, ORIGIN, [TEST_PUB])["verified"] for c in codes)
    with connect() as conn:
        links = [r["body"] for r in conn.execute("SELECT body FROM messages WHERE body LIKE 'firewatch://a/%'")]
        stored = [r["code"] for r in conn.execute("SELECT code FROM fw1_feed")]
    assert links and all(len(b) <= 160 and set(b) <= GSM7 and b.startswith("firewatch://a/FW1.") for b in links)
    assert all(fw1.decode(b.split("/a/")[1], ORIGIN, [TEST_PUB])["verified"] for b in links)
    assert stored and all(len(c.split(".")) == 13 for c in stored)  # what the radio posts is the stored code


def test_no_key_file_server_runs_and_codes_are_unsigned(no_key_file, caplog):
    from app import scenario
    from app.main import app

    with caplog.at_level(logging.WARNING, logger="app.mobile"), TestClient(app) as client:
        assert client.get("/api/m/packs").status_code == 200
        scenario.run_now("cottonwood-creek")
        lines = client.get("/api/m/feed?pack=cwc&since=0").text.strip().split("\n")
    assert [r for r in caplog.records if "unsigned" in r.getMessage()]
    codes = [l.split(" ")[1] for l in lines]
    assert codes and all(len(c.split(".")) == 12 for c in codes)
    assert all(fw1.decode(c, ORIGIN)["verified"] is False for c in codes)


def test_unsigned_rows_are_signed_on_the_way_out(test_key_file):
    from app.db import connect
    from app.main import app

    code = SIGNING["vectors"][0]["code"]
    with connect() as conn:
        conn.execute("INSERT INTO fw1_feed(pack, event_id, kind, level, flags, code, created_at) "
                     "VALUES ('cwc', 1, 'alert', 'investigate', 5, ?, '2026-03-17T18:51:00Z')", (code,))
    body = TestClient(app).get("/api/m/feed?pack=cwc&since=0").text
    assert body.strip().split(" ")[1] == SIGNING["vectors"][0]["signed"]


def test_pack_index_entries_are_signed_with_the_real_key():
    """index.json is signed with the demo key whose public half the phone app ships (mobile/app.json)."""
    from app.config import DATA_DIR

    app_json = json.loads((Path(__file__).resolve().parents[2] / "mobile" / "app.json").read_text())
    keys = [fw1.unb64url(k["key"]) for k in app_json["expo"]["extra"]["fw1Keys"]]
    assert TEST_PUB not in keys and all(len(k) == 32 for k in keys)
    for p in json.loads((DATA_DIR / "packs" / "index.json").read_text()):
        msg = fw1.pack_message(p["code"], p["version"], p["sha256"])
        assert any(fw1.verify(k, msg, p["sig"]) for k in keys), p["code"]
        assert not fw1.verify(TEST_PUB, msg, p["sig"])


def test_build_pack_signs_index_entries(test_key_file):
    from scripts import build_pack

    raw = b'{"code":"cwc"}'
    e = build_pack.index_entry({"code": "cwc", "name": "x", "state": "KS", "counties": [], "version": "v1"}, raw)
    assert fw1.verify(TEST_PUB, fw1.pack_message("cwc", "v1", e["sha256"]), e["sig"])
    Ed25519PublicKey.from_public_bytes(TEST_PUB)  # the public key is a real point
