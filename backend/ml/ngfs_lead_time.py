"""NGFS (GOES) first-detection lead time vs WFIGS FireDiscoveryDateTime for KS/OK wildfires.

Run: backend/.venv/bin/python backend/ml/ngfs_lead_time.py
Responses are cached on disk; reruns make no network calls. Requests paced at 1/s.
"""
import hashlib
import json
import math
import statistics as st
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE = Path("/private/tmp/claude-501/-Users-michaelgoldberg-Founder-OS/3aad9011-0277-442d-b3f8-d224aa2b3654/scratchpad/ngfs/lead")
WFIGS = "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations/FeatureServer/0/query"
NGFS = "https://fire.data.nesdis.noaa.gov/api/ogc/detections/collections/ngfs_schema.ngfs_detections_scene_{}_conus/items"
START = "2026-02-01"
PRE_H, POST_H = 3, 6
_last = [0.0]


def get(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    f = CACHE / (hashlib.sha1(full.encode()).hexdigest() + ".json")
    if f.exists():
        return json.loads(f.read_text())
    wait = 1.05 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(4):
        try:
            _last[0] = time.time()
            with urllib.request.urlopen(urllib.request.Request(full, headers={"User-Agent": "firewatch-research"}), timeout=60) as r:
                data = json.loads(r.read())
            break
        except Exception as e:
            print("retry", attempt, e, file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    else:
        raise RuntimeError("fetch failed " + full)
    f.write_text(json.dumps(data))
    return data


def fires():
    out, off = [], 0
    while True:
        d = get(WFIGS, dict(
            where=f"IncidentTypeCategory='WF' AND POOState IN ('US-KS','US-OK') AND FireDiscoveryDateTime >= TIMESTAMP '{START} 00:00:00'",
            outFields="IncidentName,FireDiscoveryDateTime,POOState,POOCounty,IncidentSize,IncidentTypeCategory",
            outSR=4326, f="json", resultOffset=off, resultRecordCount=1000, orderByFields="FireDiscoveryDateTime"))
        for f in d.get("features", []):
            a, g = f["attributes"], f.get("geometry")
            if g and a["FireDiscoveryDateTime"]:
                out.append(dict(name=a["IncidentName"], t=a["FireDiscoveryDateTime"] / 1000, st=a["POOState"],
                                county=a["POOCounty"], size=a["IncidentSize"], lon=g["x"], lat=g["y"]))
        if not d.get("exceededTransferLimit"):
            return out
        off += len(d["features"])


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hav(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


def detections(fire, radius_km=10):
    dl = radius_km / 111.0 * 1.05
    dn = dl / math.cos(math.radians(fire["lat"]))
    bbox = f"{fire['lon']-dn:.4f},{fire['lat']-dl:.4f},{fire['lon']+dn:.4f},{fire['lat']+dl:.4f}"
    dt = f"{iso(fire['t'] - PRE_H*3600)}/{iso(fire['t'] + POST_H*3600)}"
    rows = []
    for side in ("east", "west"):
        off = 0
        while True:
            d = get(NGFS.format(side), dict(f="json", limit=1000, bbox=bbox, datetime=dt, sortby="acq_date_time", offset=off))
            fs = d.get("features", [])
            for x in fs:
                p = x["properties"]
                rows.append((datetime.strptime(p["acq_date_time"][:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc).timestamp(), p["latitude"], p["longitude"]))
            if len(fs) < 1000:
                break
            off += 1000
    return rows


def first_match(fire, rows, r):
    c = [(t, la, lo) for t, la, lo in rows if hav(fire["lat"], fire["lon"], la, lo) <= r]
    return min(c) if c else None


def band(s):
    if s is None:
        return "unknown size"
    return "<10 ac" if s < 10 else "10-100 ac" if s < 100 else "100-1000 ac" if s < 1000 else ">1000 ac"


def summ(res, label):
    n = len(res)
    if not n:
        return f"| {label} | 0 | | | |"
    L = [x["lead"] for x in res]
    return f"| {label} | {n} | {st.median(L):.0f} | {100*sum(l<0 for l in L)/n:.0f}% | {100*sum(0<=l<=15 for l in L)/n:.0f}% |"


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    F = fires()
    print("fires", len(F), file=sys.stderr)
    for i, f in enumerate(F):
        rows = detections(f)
        for r in (10, 5):
            m = first_match(f, rows, r)
            f[f"m{r}"] = None if not m else dict(lead=(m[0] - f["t"]) / 60, dlat=abs(m[1] - f["lat"]), dlon=abs(m[2] - f["lon"]))
        if i % 50 == 0:
            print(i, file=sys.stderr)
    json.dump(F, open(CACHE / "results.json", "w"))
    out = []
    for scope, sel in (("Kansas", lambda f: f["st"] == "US-KS"), ("Kansas + Oklahoma", lambda f: True)):
        S = [f for f in F if sel(f)]
        out.append(f"\n## {scope}\n")
        for r in (10, 5):
            M = [dict(f, **f[f"m{r}"]) for f in S if f[f"m{r}"]]
            out.append(f"\n### Radius {r} km: considered {len(S)}, matched {len(M)}, unmatched {len(S)-len(M)} ({100*(len(S)-len(M))/max(len(S),1):.0f}%)\n")
            out.append("| Group | Matched | Median lead (min) | Before discovery | 0-15 min after |\n|---|---|---|---|---|")
            out.append(summ(M, "All matched"))
            for b in ("<10 ac", "10-100 ac", "100-1000 ac", ">1000 ac", "unknown size"):
                sub = [x for x in M if band(x["size"]) == b]
                tot = [f for f in S if band(f["size"]) == b]
                if tot:
                    out.append(summ(sub, f"{b} (of {len(tot)} fires, {100*len(sub)/len(tot):.0f}% matched)"))
            same = [x for x in M if x["dlat"] <= 0.002 and x["dlon"] <= 0.002]
            rest = [x for x in M if x not in same]
            out.append(f"\nIndependence: {len(same)} matched fires have the WFIGS point within 0.002 deg of the first NGFS pixel centroid.\n")
            out.append("| Group | Matched | Median lead (min) | Before discovery | 0-15 min after |\n|---|---|---|---|---|")
            out.append(summ(rest, "Excluding point-coincident"))
            out.append(summ(same, "Point-coincident only"))
            pre = [x for x in M if x["lead"] < 0]
            out.append(f"\nMatched with detection before discovery (unrelated-burn risk): {len(pre)}; of these, more than 60 min early: {sum(x['lead'] < -60 for x in pre)}.\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
