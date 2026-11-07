import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app import fw1

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "docs" / "mobile" / "codec-vectors.json").read_text())
ORIGIN = (VECTORS["origin"]["lat"], VECTORS["origin"]["lon"])


@pytest.mark.parametrize("v", VECTORS["vectors"], ids=lambda v: v["code"])
def test_vector_encodes_and_decodes(v):
    i = v["input"]
    assert fw1.encode(i, ORIGIN) == v["code"]
    d = fw1.decode(v["code"], ORIGIN)
    assert (d["pack"], d["kind"], d["level"], d["id"], d["score"]) == (i["pack"], i["kind"], i["level"], i["id"], i["score"])
    assert (d["lat"], d["lon"]) == (i["lat"], i["lon"])
    assert d["toward_deg"] == (None if i["toward_deg"] is None else round(i["toward_deg"] / 5) % 72 * 5)
    assert d["mph"] == i["mph"] or (d["mph"] == round(i["mph"] * 2) / 2)
    assert sorted(d["flags"]) == sorted(i["flags"])
    assert datetime.fromtimestamp(d["time"], timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") == v["decoded_time_iso"]


@pytest.mark.parametrize("bad", VECTORS["must_reject"])
def test_must_reject(bad):
    with pytest.raises(ValueError):
        fw1.decode(bad, ORIGIN)


def test_extra_garbage_is_rejected():
    good = VECTORS["vectors"][0]["code"]
    for bad in (good + ".x", good.replace("FW1", "fw1"), "FW1.cwc.zz.c.19.vg.-139.2c7f...5.5by", good[:-1]):
        with pytest.raises(ValueError):
            fw1.decode(bad, ORIGIN)


def test_codes_are_short_and_gsm_safe():
    for v in VECTORS["vectors"]:
        assert len(v["code"]) <= 45 and all(c.isalnum() or c in ".-" for c in v["code"])
