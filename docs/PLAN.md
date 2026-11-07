# Firewatch: build plan (rebuilt Fri Nov 6, 2026)

Rebuilt from the printed competitor packet, the verified research in [RESEARCH.md](RESEARCH.md), and the code already on `main`. Where this plan and the old one disagree, this one wins. The old version is in git history.

## 1. What we are building, in one breath

**Firewatch turns the data a rural Kansas county already has into one confirmed, located fire alert with a 60-minute spread forecast, sent to the right phones within minutes, on a volunteer budget.**

- **Detect:** watch four signals the district can get for free: the GOES-19 satellite fire product, NASA FIRMS passes, power-line fault events from the electric co-op, and reports from the public.
- **Confirm:** score each event 0–100 with reasons. Check it against dispatch's burn-call log, the red-flag status and the live wind. A permitted pasture burn scores down instead of paging anyone.
- **Respond:** show where the fire will be in 60 minutes and who is in its path. Push the alert to the district page group, the chief's phone and the downwind landowners. Export it as a standard alert (CAP) for county dispatch and Everbridge.

**Humans decide.** Firewatch ranks, explains, forecasts and delivers.

## 2. Who we are building for

The chief of **Cottonwood Creek Fire District** (fictional; Clark, Comanche and Barber counties). 450 sq mi, 18 volunteers, 5 free on a weekday, 2 brush trucks and a tanker, one bar of cell, no fiber. County 911 pages by radio pager and an app. Budget: the mill levy plus grants.

**The minutes we go after:** ignition 1:50, 911 call 2:21, first truck 2:52. For **27 minutes nobody knows.** Our target is a page by **about 1:55 (line fault) and a confirmed alert by about 2:05 (GOES)**, with a forecast that sends Brush 1 to the right road and calls the rancher downwind.

## 2a. The three barriers, minute by minute

**What happened in the scenario vs. what needs to happen.** Firewatch times are targets, not results. Every one depends on a condition we have to test, listed in the last table.

| Time | What happened (packet) | What needs to happen | Firewatch does | Barrier |
|---|---|---|---|---|
| 1:50 | Line falls into CRP grass. **Nobody knows.** | The fault itself raises the alarm | Co-op fault event + red flag + dry grass → **"possible ignition" push to the chief and duty officer**, low confidence, not a full page | Time |
| 1:52 | 15 acres, smoke column, nobody within 4 mi | Something sees it without a person there | Waits for the next GOES scan (every 5–10 min) | Time |
| ~2:00–2:10 | Smoke is normal this month: two permitted pasture burns | Tell the real fire from Tuesday's burns **without driving out** | GOES hotspot within 2 km of the fault → score climbs, **district paged**. Both burns match dispatch's burn-call log → stay "monitor," nobody paged | **False alarms** |
| ~2:05 | (chief at work 30 mi away) | The chief acts from the phone | The push carries the map, 60-min spread, and the roads and houses in the path. Chief requests **mutual aid now, not at 3:10** | Time |
| ~2:05 | (rancher downwind doesn't know) | Respond means more than the station | Downwind landowners, the lease water truck and the county grader get texts and can start a disc line ahead of the head | Time, cost |
| 2:17 | Driver sees smoke, **no signal for 3 miles** | His report arrives whenever he gets a bar | His text or call joins the existing event as a confirmation, not a new alarm | Field reality |
| 2:21–2:23 | 911 call; district paged | n/a | **Already paged about 15–20 min earlier** | Time |
| 2:34 → 2:52 | Brush 1 rolls with 2 volunteers; on scene at **fire age 62 min**, head 2–3 mi out | Truck arrives at a fire it can still flank, aimed at the right road | Paged at ~2:05, rolling ~2:16, on scene **~2:34 (fire age ~44 min)**, sent to the flank the forecast shows. The packet warns that even a fast page leaves the head ~1.5 mi out, so the disc line and early mutual aid carry the rest | Time |
| 3:10 | Mutual aid requested, 30–40 min out | Ask sooner | Requested ~2:05, so it could arrive ~2:45 | Time |

**Cost at rural scale: nothing new to buy for the core loop.** Every input already exists:
- **Satellites:** GOES-19 is free.
- **Line faults:** the co-op's own fault data.
- **Burn calls:** Barber County dispatch already takes them.
- **Phones:** texts get through on one bar.
- **Landowner contacts:** the county's Everbridge list.

There's no fiber, no full-time operator and no sensor field to maintain. We found that low-cost sensors fail in wind, and Pano-class camera towers cost $50K per station per year.

**What has to be true (each is a test or an ask):**

| Condition | If it fails | How we check it this weekend |
|---|---|---|
| The co-op can see a fault on that line and share it | No 1:50 signal. GOES alone pages ~2:05–2:15, and only a few minutes before 911 | Pitch it as an ask to the co-op. Note that 40-year-old oil-lease taps may have only fuses, no telemetry |
| GOES flags a fast grass fire within ~10–20 min of ignition | No confirmation before 911 | **Historical test:** first GOES and FIRMS detections for Starbuck (ignition 11:51 AM CST) and Anderson Creek. Live GOES delay log |
| Dispatch's burn log has location and time window | A permitted burn pages the district | Scenario decoys. The reason text says "no burn logged here," and dismissal takes one tap and is logged |
| Fault-only alerts stay rare enough to keep | Windy-day faults without fire → the chief mutes it | Fault alone = quiet "watch" push. Only fault + satellite or a report = page |

## 2b. Simulation: two kinds, both count as evidence

The packet says "Something built, simulated or tested beats a slide." The established players simulate too: Lockheed's Cognitive Mission Manager and Technosylva both predict spread. We should simulate as well, and be clear about which kind we mean.

1. **Fire spread simulation (already built).** `backend/app/sim/spread.py` runs a 60-min wind and slope spread forecast that the 3D view animates. Upgrade it only if time allows: pyretechnics with a grass fuel model, after a license check. The forecast drives "who is in the path" and where to send Brush 1.
2. **System simulation (new, and our strongest evidence).** `backend/app/sim/scenario.py` replays the Cottonwood Creek afternoon twice: **today's chain** (911 only) and **Firewatch**. It uses the same fire and weather and models each source's timing:
   - GOES scan cadence plus measured delivery delay
   - FIRMS pass times
   - whether the line has fault telemetry
   - the driver's report when he regains signal
   - each delivery channel's delay and failure rate on one bar

   Output: a side-by-side timeline, plus **fire size and distance from the head when Brush 1 arrives**. Then sweep it: ignition at random minutes against the GOES scan, fault telemetry on or off, push vs. text vs. radio page. Report the **range** of minutes saved, not one lucky number.
   - Calibrate it with real data: the historical test sets GOES and FIRMS first-detection times; spread rates come from the packet (15,000 acres in the first hour on Ranger Road).

## 2c. Built for one bar of cell and no fiber

**Principle:** the heavy work happens where the bandwidth is. The district only has to *receive* small messages, and every alert can reach it through more than one route.

- **Compute in the region, not the station.** The regional server pulls GOES from S3, FIRMS, weather and co-op faults, and does the scoring and the spread. The station and the phones need no inbound data feed.
- **Alerts are tiny.**
  - The text version is under 160 characters: what, where, score, which way it's heading and which road. Example: `FIRE 87/100 CR12 & Rd K, 11mi NW stn, head N 2mi/hr, Miller ranch 34min. Reply 1 ack 2 escalate`.
  - The full alert is a few KB of GeoJSON. The base map is cached in advance over station WiFi (an offline PMTiles file), so the field never downloads map tiles.
- **A delivery ladder, all channels at once:**
  1. App push (ntfy) when there's data.
  2. **Text (SMS)**, which gets through on one bar and is held until signal returns.
  3. **County dispatch's radio pager** via email-to-page. **It works with zero cell**, so it's the backbone. Firewatch feeds dispatch rather than going around it.
  4. **Meshtastic LoRa mesh** from the station to trucks and ranches with no cell. It's optional at about $30–60 per node.
  5. Satellite-to-phone texting is the next step (pricing not confirmed).
- **Reports from the field work the same way.** A text or a Meshtastic message goes into a queue and is sent when a bar appears. The driver's report joins the event when it arrives, even late.
- **Fail visible.** Every alert shows the age of its data. If a phone hasn't acknowledged, the next route is tried. Acknowledgements are tiny replies (1 or 2).
- **What we test this weekend:**
  - Measure our alert and spread payload sizes.
  - Load the dashboard with the browser throttled to a slow mobile connection, and once fully offline with only cached tiles.
  - Put a "time to deliver on one bar" column per channel in the system simulation.

## 3. Deadlines (from the packet)

| When | What | We need |
|---|---|---|
| Fri 8:00 pm | Team name on Slack | **Watch Dogs** posted |
| Fri 9:00 pm | Leave building | Plan agreed, jobs assigned, scenario file drafted |
| **Sat 12:30** | Review round: 10 min, 2 judges, top 2 per room advance | Scenario replay running end to end on a laptop |
| Sat 2:00 | 8 finalists announced | n/a |
| Sat 8:00 pm | Doors close | Feature-complete; historical test numbers |
| Sun 10:00 | **Code freeze** | n/a |
| **Sun 11:00** | **PowerPoint** in Slack `#slides`, named "Watch Dogs"; declare a live demo in Slack | Deck plus a **demo video embedded in the deck** |
| **Sun 11:30** | Pitch: **10 min plus 3 min questions**, hard cutoff | Rehearsed twice |

## 4. What exists today (on `main`)

All 12 backend tests pass. Already built:
- **Backend:** FIRMS ingest, grouping hotspots into events, weather and terrain enrichment, rule-based scoring with reasons, a wind and slope spread model, and an API.
- **Frontend:** the dashboard, map, alert list and drawer, and a 3D spread view.
- **Sample events:** Starbuck, Anderson Creek, three Flint Hills prescribed burns, a refinery, a made-up line ignition, and a humid single detection.

**Not built:** the ML model, the Cottonwood Creek scenario, GOES direct ingest, line-fault and burn-log inputs, public reports, alert delivery, CAP export, offline map, and the historical test.

## 5. Architecture (what changes)

```
 DETECT                          CONFIRM                       RESPOND
 GOES-19 FDC (S3, every 5–10 min) ─┐                          ┌─ 60-min spread + "in the path" list
 FIRMS VIIRS/MODIS (have)        ─┤                          ├─ Apprise → ntfy push (volunteers, chief)
 Line-fault event (co-op, POST)  ─┼─► events ─► score + reasons ─┤            email-to-page (dispatch)
 Public report (SMS / Meshtastic)─┘     ▲                       │            SMS (landowners, stub)
                                        │                       ├─ CAP 1.2 feed (county CAD, Everbridge, IPAWS later)
     burn-call log (dispatch) ──────────┤                       └─ action log (ack / escalate / dismiss)
     NWS Red Flag + ASOS wind/RH ───────┘
```

**Rules every signal follows:** each alert names its source and the age of its data. A missing feed shows as a gap, never as "no fire."

## 6. Workstreams

Five people, five workstreams. Each one has a cut line so we never ship nothing.

### W1: Detect (backend)
1. **GOES-19 ingest** in `backend/app/ingest/goes.py`. List `noaa-goes19/ABI-L2-FDCC/<year>/<doy>/<hour>/`, download the newest file, read fire pixels inside the Kansas box, and turn them into detections. Log the **scan time vs. file time vs. our ingest time** for the latency evidence. (Needs `netCDF4` or `xarray`; check the install first.)
2. **Line-fault input:** a `POST /api/signals/line-fault` endpoint {lat, lon, time, circuit, kind}. It creates a low-confidence "possible ignition" event when the red-flag status or the GFDI is high.
3. **Public report input:** `POST /api/signals/report` {lat, lon, text, phone}. Meshtastic and SMS gateways feed this.
- *Cut line:* if GOES ingest fails by Sat 11:00, replay recorded GOES detections in the scenario and show the live ingest as "next."

### W2: Confirm (scoring)
1. **Burn-call log:** `POST /api/burns` {lat, lon, start, end, caller}. Scoring subtracts points when a detection falls within 1.5 km of a logged burn during its window, and adds the reason "matches a burn called in to dispatch at 10:40."
2. **Corroboration:** add points for a line fault plus a GOES detection within 2 km and 15 min, for repeat GOES looks, and for an NWS Red Flag Warning (from api.weather.gov). Use real observed wind and RH from the **Coldwater 3K8 / Medicine Lodge K51** weather stations (IEM).
3. **ML (stretch):** only if W4 produces labels. Otherwise say plainly that we use rules plus calibration, with reasons, so a chief can audit them.
- *Cut line:* rules plus burn-log suppression is enough for the demo.

### W3: Respond (alerts and spread)
1. **Alert fan-out with Apprise:** ntfy push to a "Cottonwood Creek" topic on every phone in the room, email-to-page, and SMS as a stub. Messages are under 160 characters: what, where, score, which way it's heading, and a link.
2. **CAP 1.2 export:** `GET /api/alerts/{id}.cap.xml`. This is our hook into county dispatch, Everbridge and IPAWS.
3. **"In the path":** intersect the 60-min spread with a demo list of landowners and roads. Output "Notify: Miller ranch (house in 34 min), CR 12 at mile 4 (22 min)."
4. **Spread upgrade (stretch):** try **pyretechnics** with a grass fuel model after checking its license. Keep today's model as the fallback.
- *Cut line:* ntfy plus the in-path list. CAP and pyretechnics are extras.

### W4: Evidence (scenario and historical test)
1. **Cottonwood Creek scenario** in `backend/data/samples/10-cottonwood-creek.json`: the 1:50 line fault, GOES first look, FIRMS pass, the driver's report at 2:17, and **two permitted pasture burns as decoys** (logged with dispatch). Wind S 35 gusting 55, RH 11%, 78°F. Expected result: the fire escalates and both burns stay "monitor."
2. **Historical test:** pull FIRMS archive detections (VIIRS SNPP and MODIS) and GOES FDC for **Starbuck** (ignition Mar 6, 2017, 11:51 AM CST, near Gate OK) and **Anderson Creek** (first reported about 5:45 PM CDT, Mar 22, 2016). Report the **first satellite detection vs. the known time**. Add Ranger Road if we can find an ignition time.
3. **False-alarm test:** run every sample through scoring and show a table of expected vs. actual results.
4. **System simulation** (`backend/app/sim/scenario.py`, section 2b): today's chain vs. Firewatch, then a sweep over ignition minute, fault telemetry and delivery channel. The headline output is the range of minutes saved and fire size when Brush 1 arrives.
- *Cut line:* the scenario replay is required. The historical test needs at least one fire. The simulation sweep can shrink to three hand-picked cases.

### W5: Field kit, offline and pitch
1. **Offline and low bandwidth:** a PMTiles extract of the district plus a service worker, so the dashboard loads with no signal. Measure alert and spread payload sizes. Test the dashboard with the browser throttled to a slow mobile connection and fully offline (section 2c). W3 adds the email-to-page route to county dispatch, since the radio pager works with zero cell.
2. **Field kit slide:** what the district reuses (county dispatch, co-op line sensors, airport weather stations, Everbridge) vs. what it might add later (one tower camera running Pyronear, a Meshtastic node at the station). Show prices only from RESEARCH.md.
3. **Meshtastic demo** if anyone has a LoRa board. Otherwise a slide.
4. **Deck** in PowerPoint, and the demo video.
- *Cut line:* deck and video are never cut.

## 7. Timeline

| Block | W1 Detect | W2 Confirm | W3 Respond | W4 Evidence | W5 Field / pitch |
|---|---|---|---|---|---|
| Fri to 9 pm | GOES S3 spike: read one file | Burn-log schema | Apprise + ntfy hello-world | Scenario JSON draft | Deck outline; post team name |
| Sat 9–11 | GOES ingest working | Burn-log suppression + Red Flag | ntfy alerts from real events | Scenario plays end to end | Review-round script |
| Sat 11–12:30 | Line-fault endpoint | Corroboration rules | In-path list | Dry-run review | **Rehearse review** |
| **Sat 12:30** | **Review round:** show the scenario replay live | | | | |
| Sat 2–5 | Public report endpoint; latency log | Reasons wording | CAP export | Historical FIRMS test | PMTiles offline |
| Sat 5–8 | Hardening, failure banners | Expected-vs-actual table | pyretechnics (stretch) | Historical GOES test | Deck draft; record video |
| Sun 9–10 | Fixes only | Fixes only | Fixes only | Final numbers | Final deck |
| **Sun 10** | **Code freeze** | | | | |
| Sun 10–11 | | | | | Re-record video; post deck by 11 |

## 8. The 10-minute pitch

1. **The 27 minutes** (1 min): the Cottonwood Creek timeline, and why fast detection alone isn't enough when burn smoke is normal that month.
2. **Live replay** (4 min): the line fault at 1:50 pages the chief at low confidence. GOES confirms it at about 2:00 and the score climbs with reasons. Both pasture burns stay quiet ("matches a burn called in to dispatch"). The 3D spread shows the head reaching CR 12 in 22 min. Phones in the room buzz with the alert and the Miller ranch notice.
3. **Evidence** (2 min): GOES delay as we measured it, the historical first-detection results, the expected-vs-actual table, and the 83% figure from the NWS notification work.
4. **Field reality** (1.5 min): one bar of cell means short texts, an offline map and an optional mesh. Lead with the reuse list. **What it does when it fails** (table below).
5. **Honest numbers and next steps** (1.5 min): cost, who pays, time to stand up. Next: co-op line-fault sharing, tower camera with Pyronear, FireSat in 2027, and handing confirmed events to autonomous responders like the ones Lockheed is building.

## 9. Honest numbers

- **Cost to the district:** $0 for software, using free public data and hosted once for the region. Hosting is a small cloud VM (estimate about $10–25/month for the state; confirm before the deck).
- **Comparison:** camera detection costs "$50,000 per station per year" (Pano AI, 2023), and utilities pay for it.
- **Who pays:** the region or state hosts it. Co-ops pay for their line sensors because it lowers their wildfire liability. Optional hardware comes through Kansas Forest Service VFA (matching) or USDA CWDG (10–25% match).
- **Stand-up time:** a day of setup (district boundary, roads, landowner contacts, dispatch email-to-page, burn-log entry). The co-op feed takes weeks of agreements.

**What it does when it fails**

| Failure | Behavior |
|---|---|
| GOES or FIRMS late or down | Banner with data age; a coverage gap shown, never "no fire"; 911 stays the primary path |
| Co-op feed down | Fault input greyed out; satellite and reports still score |
| Burn log missing an entry | A burn can alert. The reason text says "no burn logged here," so dispatch can dismiss it in one tap. Each dismissal is logged |
| No cell in the field | Alerts are under 160 characters; offline map; Meshtastic as the fallback channel |
| Model wrong | Human decides; every override is logged for tuning |

## 10. Setup (tonight)

- [ ] FIRMS MAP_KEY (free): https://firms.modaps.eosdis.nasa.gov/api/map_key/
- [ ] Python venv: `pip install -r backend/requirements.txt` plus `apprise` and a netCDF reader for GOES
- [ ] Install the ntfy app on every phone; agree on one topic name
- [ ] Node 20+ for the frontend: `cd frontend && npm install && npm run dev`
- [ ] Everyone works on their own branch and merges to `main` through PRs
- [ ] Ask K-State's Weather Data Library for Mesonet ingest consent (kansas-wdl@k-state.edu); use IEM ASOS until then
