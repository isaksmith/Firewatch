# FW1: the fire update code for phones with almost no signal

One fire update fits in about 40 characters. A text message carries it. The app already has the region pack (map, roads, homes, places), so the code only says what changed. The phone works out the rest offline: the nearest road, homes in the path, and worst-case arrival times.

The reference implementation is [fw1_reference.py](fw1_reference.py). It writes [codec-vectors.json](codec-vectors.json). The backend (Python) and the app (TypeScript) must both pass every vector, and must reject every `must_reject` string.

## Format

```
FW1.<pack>.<kind><level>.<id>.<score>.<dlat>.<dlon>.<t>.<dir>.<spd>.<flags>.<chk>
```

Twelve fields joined by `.`. Every number is base 36, written with the lowercase digits `0-9a-z`. A negative number has a leading `-`. Every character is in GSM-7 and safe in a URL path.

| Field | Meaning |
|---|---|
| `FW1` | Version. Reject anything else. |
| `pack` | Region pack code, lowercase (for example `cwc`, Cottonwood Creek). The app needs that pack installed to place the fire. |
| `kind` | `a` new or updated alert, `c` cleared or contained, `x` not a fire (dismissed). |
| `level` | `e` escalate (page), `i` investigate, `m` monitor. |
| `id` | Alert id from the server. |
| `score` | 0 to 100. |
| `dlat`, `dlon` | (lat or lon minus the pack origin) × 10,000, rounded. Precision is about 11 m. |
| `t` | Whole minutes since 2026-01-01T00:00Z. |
| `dir` | The direction the fire head is moving toward, in degrees ÷ 5, rounded, mod 72. Empty means unknown. |
| `spd` | Head speed in half mph (mph × 2, rounded). Empty means unknown. |
| `flags` | A bit sum: 1 Red Flag day, 2 homes in path, 4 exercise or demo, 8 mutual aid requested, 16 two sources agree. |
| `chk` | CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) of the ASCII text before the last `.`, mod 46656, written in base 36 and left-padded with `0` to 3 characters. |

## How it travels

1. **Text message:** works with one bar and no data.
   - The person's normal alert text stays as it is (160 characters or fewer, plain words).
   - People who use the app get a second short text, just the link: `firewatch://a/<code>`.
   - Tapping it opens the app and needs no data.
   - iOS does not let apps read texts. On both iOS and Android, the app also offers **Paste alert**: copy the text, tap the button, and the app finds `FW1.` anywhere in the pasted text.
2. **Tiny feed:** when there is a bar of data. `GET /api/m/feed?pack=<code>&since=<seq>` returns `text/plain`, one line per change in the form `<seq> <code>`, with an ETag (304 when nothing changed). It is a few hundred bytes at most.
3. **Region pack:** download it once, over Wi-Fi at the station. `GET /api/m/packs` lists the packs. `GET /api/m/packs/<code>` returns one pack: the origin, the boundary, named roads, towns, homes and buildings, stations and power lines, plus a version and a sha256. A state is the set of its county packs.

## Rules

- Never trust a code that fails its checksum. Show "This alert code is damaged. Ask dispatch to resend."
- A newer `t` for the same `pack` and `id` replaces the older one. An older `t` never overwrites a newer one.
- Every estimate the app derives is a worst case ("as little as 25 min"), following the team's rule.
- The app never sends anything when it opens a code. Reading a code is offline and private.

## Region pack format (`fwpack/1`)

A JSON file, served gzipped. Coordinates are `[lon, lat]`, rounded to 5 decimals. The target size is at most 1.5 MB gzipped per county.

```json
{
  "format": "fwpack/1",
  "code": "cwc",
  "name": "Cottonwood Creek Fire District",
  "state": "KS",
  "counties": ["Comanche"],
  "version": "2026-11-07.1",
  "tz": "America/Chicago",
  "origin": {"lat": 37.2689, "lon": -99.3268},
  "bbox": [-99.6, 37.0, -99.0, 37.6],
  "boundary": {"type": "Polygon", "coordinates": [[[-99.6, 37.0], [-99.0, 37.0], [-99.0, 37.6], [-99.6, 37.6], [-99.6, 37.0]]]},
  "roads": [{"name": "Rd K", "kind": "county", "line": [[-99.46, 37.30], [-99.46, 37.40]]}],
  "towns": [{"name": "Coldwater (stand-in)", "lon": -99.3268, "lat": 37.2689}],
  "buildings": [{"lon": -99.4681, "lat": 37.4250, "kind": "home", "name": "Miller house"}],
  "stations": [{"name": "Station 1", "lon": -99.3268, "lat": 37.2689}],
  "power_lines": [{"line": [[-99.47, 37.38], [-99.46, 37.39]]}],
  "places": [{"id": "p1", "name": "Miller house", "kind": "home", "lon": -99.4681, "lat": 37.4250}]
}
```

- `kind` for roads is one of: `highway`, `state`, `county`, `local`, `track`.
- `kind` for buildings is one of: `home`, `farm`, `commercial`, `other`.
- `name` is optional on roads and buildings.
- `places` are the named spots used in messages and arrival-time lists.
- The pack index (`GET /api/m/packs`) lists `{code, name, state, counties, version, bytes, sha256}` for each pack. The app checks the sha256 after downloading.

## Signatures (FW1 with `sig`, added 2026-11-07)

The checksum only catches typing and transmission errors. A signature proves a code came from dispatch's server, so a made-up code that is texted, pasted or radioed cannot pose as a real alert.

**Signed code:** the 12-field code, then `.`, then `sig`:

```
FW1.<pack>.<kind><level>.<id>.<score>.<dlat>.<dlon>.<t>.<dir>.<spd>.<flags>.<chk>.<sig>
```

- `sig` is an Ed25519 signature (64 bytes) over the ASCII bytes of the 12-field code exactly as written (everything before the last `.`, `chk` included), written in base64url (RFC 4648 section 5) with no padding: always 86 characters from `A-Z a-z 0-9 - _`. All are GSM-7 and safe in a URL path.
- A signed code is the 12-field code plus 87 characters. Measured worst case, with every field at the most the app accepts and a six-digit id: 145 characters for pack `ks-comanche` (137 for `cwc`). The app-link text `firewatch://a/<signed code>` (no label, to leave room) is then at most 159 GSM-7 characters, within one 160-character SMS, and a mesh message stays well within 233 bytes.
- The server never cuts a text that holds a signed code. If an app link would not fit one SMS, it is not sent, and the server logs an error.
- The finder (Paste alert) also matches a 13th field: `FW1.` followed by 11 dot-separated fields and an optional `.` plus 86 base64url characters.

**Keys:**
- The server holds the private key. It loads it from the file named by `FW1_SIGNING_KEY_FILE` (default `backend/data/keys/fw1_ed25519.pem`, git-ignored, never committed). `backend/scripts/make_signing_key.py` creates one and prints the public key.
- Without a key file the server still sends 12-field codes, unsigned, and logs that once at startup.
- The app trusts only the public keys built into it: `expo.extra.fw1Keys` in `mobile/app.json`, a list of `{ "id": "...", "key": "<base64url of the 32-byte public key, 43 chars>" }`. A code has no key id; the app tries each trusted key. Keys that arrive from a server, a pack or a radio are never trusted.

**What the app does:**

| Code | Result |
|---|---|
| Valid checksum, valid signature from a trusted key | Verified. Normal rules (a newer `t` replaces an older one). |
| Valid checksum, no `sig` | Shown, marked "Not confirmed by dispatch". It never replaces, clears or downgrades an alert that is verified. A `c` or `x` code without a signature changes nothing that already exists. |
| `sig` present but it does not verify | Refused: "This alert code is damaged or did not come from dispatch. Ask dispatch to resend." Nothing is stored. |
| Checksum fails | Refused, as before. |

A verified code may replace an unverified one for the same `pack` and `id` regardless of `t`.

**Region packs are signed too.** Each entry in the pack index gains `sig`: base64url Ed25519 over the ASCII text `fwpack/1|<code>|<version>|<sha256 lowercase hex>`. The app refuses a downloaded pack unless its sha256 matches and `sig` verifies with a trusted key. Packs built into the app are trusted as they are.

**Test vectors:** `codec-vectors.json` gains a `signing` block with a TEST-ONLY seed (never used outside tests), its public key, a signed version of every vector, and `must_reject_signed` cases: one changed character in `sig`, a valid `sig` from a different key, and a valid `sig` moved onto a code with a changed field.
