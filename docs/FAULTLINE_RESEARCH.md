# Faultline — Research Brief (Firewatch 2026)

> Context file for Claude Code. Compiled Fri Nov 6, 2026 during the WSU College of Innovation & Design × Lockheed Martin Skunk Works "Firewatch 2026" challenge weekend (Nov 6–8). Pitches are **Sunday Nov 8 at noon** to Lockheed Martin judges. Treat this as the source of truth for the concept, the evidence, and the build plan.

## 0. Rules for whoever builds from this file

- **Label anything simulated or synthetic** as such in the code, the UI, and the outputs. The judges explicitly check for the difference between observations, assumptions, and simulations.
- **Civil and commercial use only.** Avoid military framing: say "shared operating picture," not "kill chain."
- **Use public data only** for the weekend build. Real co-op data is a future step, so synthesize it.
- **Assume no unlimited power or connectivity** in the field.
- **Model infrastructure and areas, never individual people or households.** Store no personal data.
- **Scope to a single weekend.** Build one end-to-end slice in depth, not a platform.
- Items marked **[VERIFY]** are data-access details that were not confirmed during research. Check them before depending on them.

---

## 1. The challenge (from the official brief)

- **Ask:** "Propose a system, not a sensor." Cover the full chain of **Detect → Confirm → Respond** and show how the pieces connect.
- **Customer:** a Kansas rural fire district or a state wildfire agency. The pitch must give rough cost, how long it takes to stand up, and what the system does when it fails.
- **Pain points named in the brief:**
  - **Time:** most fires are detected by a 911 call, minutes to hours after ignition.
  - **False alarms:** dust, controlled burns, and haze look like smoke. A system that cries wolf gets switched off.
  - **Cost at rural scale:** volunteer budgets; anything needing fiber or a full-time operator won't be deployed.
- **Stats cited in the brief:**
  - 5.1M acres burned in the U.S. in 2025.
  - Extreme fires are about 3% of fires but cause about 80% of the damage.
  - The 2017 Starbuck fire burned 626,000 acres, the largest in Kansas history.
- **Pitch outline from the template:** Need → Evidence → Idea → Prototype → Learning → Next step.

---

## 2. Core insight

**The Plains' catastrophic fires are disproportionately power-line ignitions on extreme-wind days. The rural grid already detects those faults, but it reports them to the utility, not to the fire department.**

### Evidence

| Fire | Year | Size | Cause (as reported) | Source |
|---|---|---|---|---|
| Starbuck + others (KS/OK) | Mar 2017 | 626k ac (Starbuck) | Most fires started by downed power lines whose connections were weakened by a January ice storm (K-State) | K-State Weekly Weather |
| Four County + others (KS) | Dec 15, 2021 | ~164k ac, 16 fires, 11+ counties | Most likely power lines, per the state fire marshal. Winds up to ~100 mph. Several separate blazes were sparked by falling lines. | Hays Post, KCUR, Missouri Independent |
| Smokehouse Creek (TX) | Feb 2024 | >1M ac | Texas A&M Forest Service concluded power lines. Xcel acknowledged its facilities appear to have been involved. | NBC News |
| Morrill (NE) | Mar 2026 | ~643k ac | Governor described it as electrical (wind "popping wires"). **Official cause listed as undetermined.** | Wikipedia, NEMA |

### Other facts from Dec 15, 2021
- Downed lines also knocked out power at the **emergency dispatch center in Hays**.
- Firefighters **couldn't cross downed lines** until they were confirmed dead.
- Winds up to ~80 mph **grounded firefighting aircraft**.

### Base rates
- About **8% of all wildfires** are attributed to power-system faults (Texas A&M). This is a small share by count, but power-line fires tend to grow about **10× larger** than fires from other causes. That figure comes from Mitchell (2009), cited in California Senate testimony.

---

## 3. Why the "obvious" answer (cameras + satellite + drone) breaks on the days that matter

- **Satellites are slow.** NOAA's Next Generation Fire System (NGFS) detects fires **5–30 minutes after ignition**. It is now public through the NOAA Wildland Fire Data Portal.
- **Grassfires move fast.** Head-fire spread is about **20% of the 10-m open wind speed** (Cruz, Alexander & Kilinc 2022; validated for 20–62 km/h winds). At a 35 mph wind that is about 7 mph, so the fire could be **up to ~3.5 miles downwind** before a 30-minute satellite detection.
- **Drones can't fly.** A flagship enterprise drone (DJI Matrice 350 RTK) is rated for **12 m/s (~27 mph)** of wind. Extreme Plains fire days far exceed that.
- **Dispatch is overwhelmed.** Simultaneous ignitions arrive at once (16 fires in a single day in 2021), and the dispatch center itself can lose power.

---

## 4. The concept: Faultline, a "fault-to-fire handoff"

### Detect
On high-fire-danger days, treat every utility line fault or outage over grassland as a **possible ignition with a known location**.

There are two levels of detection:
1. **Live co-op feed (future).** The co-op's outage management system and smart meters provide outage extent and location.
   - 87% of co-op meters had smart meters by 2024.
   - Most co-ops communicate with meters over **power line carrier**, which means **polling**, not instant "last gasp" messages.
   - One co-op's software detects an outage in **under 190 seconds**. Expect latency of about 3 minutes.
2. **Public outage maps (works today, no data agreement needed).** This is the same source DOE's EAGLE-I scrapes. It is coarser and slower, but it satisfies the public-data ground rule.

### Confirm (no drone)
Fuse independent evidence:
- Fire-weather gate
- Fuel and land cover
- The shape of the outage
- A satellite hot spot near the line
- A "see smoke?" text to co-op members near the fault
- The registered-burn check (see §8)

### Respond
1. **Page the fire district** with a packet containing:
   - the probable ignition point
   - confidence and the supporting evidence
   - a downwind spread cone
   - **which lines are confirmed dead**, so crews can cross safely
2. **Ask the co-op to hold the line dead** (no automatic re-energizing).
3. **Text co-op members in the downwind area.**

Alert delivery must not depend on the local dispatch center's power.

### Pitch line
"The grid already knows. Nobody tells the fire department."

### Fails safe
Faultline only **adds** an earlier signal. 911 and satellite detection keep working regardless. If the data feed stalls, show a **"coverage lost"** status to dispatch.

---

## 5. Prior art and differentiation

| Who | What it does | Who gets the alert |
|---|---|---|
| Texas A&M Distribution Fault Anticipation (DFA) | Substation waveform analytics that find failing equipment. Used at Texas co-ops (Pedernales, Bluebonnet, Mid-South Synergy). | Utility |
| Gridware Gridscope | Pole-mounted sensors (vibration, E-field) that detect line faults. About 13k units deployed. | Subscribing utilities |
| Whisker Labs Ting | In-home sensors that pick up grid faults. Data has mostly been used retrospectively (Maui, LA 2025). | Utility, insurers, investigators |
| Xcel / Colorado co-ops "Enhanced Powerline Safety Settings" | More sensitive tripping on red-flag days; tripped lines **stay off until patrolled**. | Utility operations |
| Watch Duty | Since Dec 2025, shows nationwide power outages as a map layer (via PowerOutage.com API). | Public |
| Lindsey FireSense FIREBird | Pole-mounted camera and thermal fire detectors along rights-of-way. | Utility |
| PG&E + Palantir Foundry | Utility-wide operational picture used for power-shutoff decisions. | Utility |

**The gap:** none of these turns a grid fault into a **ranked ignition alert for fire dispatch**, gated by fire weather and with burn awareness.

**Example of the cost of that gap** (California Senate testimony, Lindsey FireSense, 2022):
- A power outage was reported first.
- CAL FIRE was not notified until **~10.5 hours** later.
- The fire reached almost **100,000 acres within a week**.

---

## 6. Key numbers for the pitch

- **Base rate:** PG&E, fire season (May–Nov, excluding rain, winter storm, and lightning days). CPUC-reportable ignitions were **2.2% of outages** (3-year average on the relevant circuits) and **3.6%** system-wide. That is roughly **1 real ignition per 30–45 outages**. With Enhanced Powerline Safety Settings the figure fell to about **0.3%**.
  - **Implication:** never page on every outage. Rank and corroborate.
- **Latency comparison:**

  | Source | Typical latency |
  |---|---|
  | Co-op meter polling | ~3 min |
  | NGFS satellite | 5–30 min |
  | 911 | minutes to hours |

- **Coverage:** 87% of co-op meters have AMI (NRECA analysis of EIA-861, 2024 data). Kansas Electric Cooperatives has **29 co-ops serving 103 of 105 counties**.
- **Policy hook:** Kansas **HB 2107 (2025)** addresses utility wildfire liability and requires a KCC wildfire-risk workshop. Co-ops supported it, so they have an incentive to adopt mitigation tools. This is the business case: the utility side funds it, and the fire district pays about $0.

---

## 7. Data model (Palantir-style ontology, kept small)

### Object types
- `LineSegment`: geometry (synthetic for the weekend), feeder ID, protecting device
- `ProtectiveDevice`: fuse or recloser; links to the segments it protects
- `OutageEvent`: time, extent, device, duration (momentary vs. sustained), source (`eaglei` | `outage_map` | `coop_feed_simulated`)
- `WeatherObs`: wind speed and direction, relative humidity, time, station
- `FireDangerZone`: county, Grassland Fire Danger Index (GFDI) category, red flag warning active (bool), time window
- `SatDetection`: time, lat/lon, fire radiative power, NGFS `type` flag, source
- `CommunityReport`: text reply (yes / no / no reply), area, time. **No personal data**; store area-level only.
- `RegisteredBurn`: parcel or polygon, start/end window, acreage, status (`active` | `extinguished`), source (`simulated` for the weekend)
- `IgnitionCandidate`: **the central object**; aggregates the evidence and holds the score, tier, and status
- `FireDistrict`: coverage polygon, paging endpoint
- `DownwindArea`: polygon derived from the candidate plus wind

### Links (spatial and time joins)
- `OutageEvent → ProtectiveDevice → LineSegment`
- `SatDetection` within N km of `LineSegment` and within T minutes of `OutageEvent`
- `IgnitionCandidate` aggregates its evidence (each item records source, timestamp, and a label: `observed` | `inferred` | `simulated`)
- `FireDistrict` covers `IgnitionCandidate`

### Actions (human-in-the-loop, all logged)
- `page_district`
- `request_hold_dead` (ask the co-op not to re-energize)
- `text_downwind_area`
- `text_burn_holder`
- `close_candidate(outcome = fire | no_fire | unknown)`

### Access roles (demo with a role switcher)
- **Co-op:** sees grid layers and outage detail.
- **Dispatcher / fire district:** sees candidate location, confidence, evidence, and line-dead status. No customer data.
- **Resident:** sees only their own area alert.
- **Principle:** data stays with its owner; only answers cross the boundary. This is the answer to "will co-ops share data?"

---

## 8. False-alarm handling

### 8.1 Cheap filters (applied before anyone is alerted)
1. **Weather gate:** Faultline is active only when the GFDI is Very High or above, or a red flag warning is in effect. NWS Wichita issues a county-level GFDI product in 3-hour steps. The categories are:

   | GFDI | Category |
   |---|---|
   | 0–7 | Low–Moderate |
   | 8–19 | High |
   | 20–49 | Very High |
   | 50–79 | Extreme |
   | 80+ | Catastrophic |

   Rain, ice, and lightning storm days drop out entirely.
2. **Fuel and place:** count only faults over cured grass or crop stubble. Exclude faults in towns and over green wheat (use land cover).
3. **Outage shape:**
   - A fuse or recloser **lockout** on a branch line in high wind is a strong signal.
   - A single dark meter is likely a member-side problem, so it is a weak signal.
   - Momentary self-restoring blinks are low score.
4. **Legal burns:** many Kansas counties ban open burning during red flag warnings (e.g., Nemaha, Marion, Lyon-area counties).
5. **Known satellite false positives:** NGFS `type` flags mark known incidents, persistent emitters, solar farms, solar-farm-like reflections, and likely urban sources. Drop or discount these.

### 8.2 Escalation tiers

| Tier | Trigger | Action |
|---|---|---|
| Watch | Passes the filters | Dashboard only |
| Check | Score rising | Text nearby members "see smoke?"; wait for the next satellite scan (~5 min) |
| Advisory | One more signal | Shows on the dispatcher console; a human decides |
| Page | **Two independent sources agree** | Auto-page the district; the page states why and gives a confidence level |

### 8.3 Scoring (odds-based)
- **Prior:** about 3% (from the PG&E base rate), adjusted by the weather gate.
- Each **independent** piece of evidence multiplies the odds by a likelihood ratio (LR).
- **Illustrative only:**
  - Prior odds are 3:97 ≈ 0.031.
  - Suppose a satellite hit within 2 km of the line has an LR of 50.
  - The odds become 1.55, a probability of about 61%.
- **Real LRs must be estimated from the replay.** Never double-count correlated signals: two signals derived from the same outage count once.

### 8.4 Alert budget and feedback
- Ask the **fire chief** how many wasted pages per season they will tolerate. Set the paging threshold to meet that budget.
- Every alert gets a **one-tap outcome** from a responder (fire / no fire / unknown). Use these to recalibrate LRs and to learn per-feeder priors (lines that fault often but harmlessly).

### 8.5 What to measure
- **Precision:** the share of pages that were real fires.
- **Recall:** whether every 2021 fire got flagged.
- **Lead time:** how much earlier than the satellite detection and the reported start.
- Show the **precision/recall curve** and where the chief's threshold sits on it.

---

## 9. Legal / controlled burns

- **The trigger is a grid fault, not smoke**, so a legal burn alone never creates a candidate. It can only fool the satellite-confirmation step.
- **Low overlap with dangerous days:**
  - Permits commonly prohibit burning in high wind. The Cheney form cites a 15 mph limit under state law; Kansas City, Kansas suspends burning at sustained winds over 15 mph or gusts over 25 mph.
  - Faultline runs mostly on high-wind days, so use the measured wind at the hot spot as evidence.
- **The registry already exists, county by county:**
  - Many counties require a call to dispatch **before and after** burning (Brown: 2 hours ahead; Gray: 24 hours ahead; Barber: 1 hour ahead; Phillips: the call lets dispatch track the location and know when the burn is no longer monitored).
  - Some counties run **online permits**: Franklin (daily, to decide whether to deploy), Reno (per parcel), Sedgwick FD1, and Osage (a permit database).
- **Downgrade, never suppress.** A hot spot inside an active `RegisteredBurn` counts as weak evidence. **Escalate** if any of these happens:
  - heat appears outside the parcel
  - heat appears after the burn was called extinguished
  - the fire grows beyond the registered acreage (FRP growth or multiple pixels)
  - the wind rises or a red flag warning is issued
  - the adjacent line faults
- **Ask the burner:** auto-text the permit holder "Satellite sees heat at your burn. Under control? 1 = yes, 2 = need help." A "2" or no reply becomes an escape alert.
- **Flint Hills season:**
  - About 35% of Flint Hills prairie acres burn each year.
  - KDHE's April restrictions cover 16 counties but **still allow prairie and grassland burning**: Butler, Chase, Chautauqua, Cowley, Elk, Geary, Greenwood, Johnson, Lyon, Marion, Morris, Pottawatomie, Riley, Sedgwick, Wabaunsee, Wyandotte.
  - KDHE already reviews satellite imagery; ksfire.org provides a smoke model.
  - **In these counties during March and April, a satellite hit alone never pages.** It needs a fault, a 911 call, or signs of escape.
- **Pitch line:** "We don't ignore legal burns. We watch them for escape."
- **Future step:** a single statewide "I'm burning" text or web form that feeds every county's dispatch.

---

## 10. Data sources (public, for the weekend)

| Data | Use | Access | Notes |
|---|---|---|---|
| EAGLE-I outage data (ORNL/DOE) | Outage time series for the replay | OSTI datasets: 2014–2022 `doi:10.13139/ORNLNCCS/1975202`; 2023 OSTI 2297398; 2024 OSTI 2500278 | **County-level, 15-minute** customers out, scraped from utilities' public outage maps. A coarse proxy, so real meter-level data would be faster. |
| NWS GFDI products (Wichita: `FNUS63 KICT`, `RFDICT`) | Weather gate | Iowa Environmental Mesonet API, e.g. `https://mesonet.agron.iastate.edu/api/1/nwstext/<product_id>` | Confirmed the API serves these products. **[VERIFY]** archive coverage back to Dec 2021 and the other Kansas NWS offices (Dodge City, Goodland, Topeka). |
| Red flag warnings (archive) | Weather gate, burn-ban proxy | IEM watch/warning archive **[VERIFY]** endpoint and format | |
| GOES fire detection (ABI L2 FDC) | Satellite evidence for the 2021 replay | NOAA GOES on AWS open data **[VERIFY]** bucket and product name (e.g. `noaa-goes16`, `ABI-L2-FDCC`) | NGFS itself became public in Jan 2026 (`https://fire.data.nesdis.noaa.gov/map/`). Its 2021 history may not exist, so use GOES FDC or FIRMS for the replay. |
| NASA FIRMS (VIIRS/MODIS) | Satellite evidence, Flint Hills burn simulation | FIRMS archive download **[VERIFY]** | |
| Kansas Mesonet | Wind and RH at the fault | `mesonet.k-state.edu` **[VERIFY]** historical download | Can fall back to ASOS stations via IEM. |
| Land cover (USDA Cropland Data Layer / NLCD) | Fuel filter (grass vs. town vs. green wheat) | **[VERIFY]** download method | |
| Distribution lines | Line geometry | **Not public.** Synthesize feeders along section-line roads (OSM), labeled **SYNTHETIC** | HIFLD has transmission lines and service territories; **[VERIFY]** whether HIFLD Open is still available. |
| Fire start times and locations, Dec 15 2021 | Ground truth | Kansas Forest Service, news reports, NIFC **[VERIFY]** | Collect manually into a CSV with a source column. |
| Burn registry | Legal-burn handling | No statewide source. **Simulate** from historical spring Flint Hills satellite detections, labeled **SIMULATED** | |

---

## 11. Weekend build plan

### MVP: one end-to-end slice
**Replay Dec 15, 2021 in central and western Kansas** and show `IgnitionCandidate`s appearing on a map with a time slider, then compare against the satellite detections and the known fire starts.

### Suggested stack
- Python: data classes or pydantic for the ontology, NetworkX for links, SQLite for storage, pandas and geopandas.
- A small FastAPI (or Flask) backend.
- Frontend: Leaflet or deck.gl with a time slider, plus a triage list ranked by score.
- Paging demo: **Active911 accepts alerts by email from any system** (SMTP/SNPP; free trial). Faultline sends an email to an Active911 alert address and a phone gets paged. A plain SMS or email fallback also works.

### Suggested repo layout
```
faultline/
  data/raw/            # downloaded public data (gitignored)
  data/derived/        # cleaned parquet/csv
  data/synthetic/      # SYNTHETIC feeders, SIMULATED burns, co-op feed
  faultline/ontology.py
  faultline/ingest/    # eaglei.py, gfdi.py, goes_fdc.py, mesonet.py, firms.py
  faultline/score.py   # filters + odds model + tiers
  faultline/burns.py   # registered-burn logic
  faultline/actions.py # page/text/hold-dead (stubs + Active911 email)
  faultline/replay.py  # time-stepped replay engine
  app/                 # API + map UI with role switcher
  notebooks/eval.ipynb # precision/recall/lead-time
```

### Schedule
- **Fri night:**
  - Lock the ontology.
  - Pull EAGLE-I for Kansas counties on Dec 15–16, 2021.
  - Pull GFDI and red flag warnings for that day.
  - Hand-build the ground-truth CSV of fire starts.
- **Sat AM:**
  - Ingest pipeline.
  - Synthetic feeders.
  - Scoring v0.
  - Replay engine.
- **Sat midday (design review with Lockheed engineers):** bring the lead-time number and the false-alarm count. Ask them to attack the confirm logic.
- **Sat PM:**
  - Map UI with time slider.
  - Role switcher.
  - Active911 email page.
  - Burn-registry simulation.
  - Evaluation notebook.
- **Sun AM:**
  - Freeze the code.
  - Rehearse the demo.
  - Make the slides.
  - Test link-sharing permissions.

### Stretch goals
- Non-fire red-flag days to measure the false-alarm rate.
- Flint Hills spring replay to show the burn-registry effect.

---

## 12. Optional hardware demo ("last gasp" node)

- **Hardware:** ESP32 plus a supercapacitor holdup plus voltage sensing on its supply. When power is cut, the node sends a last-gasp message (LoRa preferred; Wi-Fi if simpler) before it dies.
- **Path:** the backend receives the message, creates an `OutageEvent`, the gate passes, a candidate is created, and **a judge's phone gets paged** via Active911 or SMS.
- **Keep the firmware minimal.** The point is the tactile "unplug → alert" moment, not the hardware.

---

## 13. Demo script (~3 min)
1. **The problem in one slide:** four Plains megafires, all linked to power lines; satellites take 5–30 min; drones are grounded above ~27 mph.
2. **Replay Dec 15, 2021:** candidates appear X minutes before the satellite. Show precision and recall.
3. **Role switcher:** the same candidate seen as the co-op, as dispatch, and as a resident.
4. **Unplug the ESP32:** a judge's phone buzzes.
5. **Honest limits and next steps** (see §14).

---

## 14. Risks, limits, open questions

- It **only catches grid-caused ignitions**. Cigarettes, combines, and debris burns still rely on satellite and 911.
- **EAGLE-I is county-level and 15-minute**, so replay lead times are conservative relative to a real meter feed.
- **Co-op data sharing** is the biggest adoption risk. Mitigations: the access-control design, the HB 2107 liability incentive, and starting with public outage maps.
- **Power line carrier AMI** is polled (~3 min), not instant. If the co-op's backhaul or substation loses power, the system is blind, so show "coverage lost" to dispatch.
- **Enhanced Powerline Safety Settings reduce ignitions per outage** (0.3% vs. 2–4%). That is good for safety but lowers the precision of an outage-based signal.
- **Open questions** for the customer (non-engineering teammates own these):
  - Fire chief's tolerance for wasted pages.
  - Which paging app the district uses.
  - Whether the county dispatch keeps a digital burn log.
  - Contacts at a co-op in the 2021 burn area. Western Cooperative Electric (WaKeeney) runs an outage management system, a real-time outage map, and SmartHub text and email outage alerts.

---

## 15. Pitch mapping (template's 6 beats)
1. **Need:** rural districts learn about wind-day fires from 911, too late. Extreme fires cause most of the damage.
2. **Evidence:** the Plains megafires and their power-line causes; satellite and drone limits; the 2021 dispatch outage.
3. **Idea:** Faultline, a fault-to-fire handoff on high-danger days, with layered confirmation.
4. **Prototype:** the 2021 replay, the role switcher, and the live ESP32 page.
5. **Learning:** lead time, precision and recall vs. the 2–4% base rate, and what remains uncertain.
6. **Next step:** a pilot with one co-op and one fire district; a live outage-map feed; a statewide burn-notification form.

---

## 16. Sources

- K-State Weekly Weather (2017 fires): https://secondary.climate.ksu.edu/news/stories/2018/03/ww_mar_7
- Hays Post (2021 Ellis County report, Hays dispatch outage): https://hayspost.com/posts/3036a06a-6e63-45aa-9fd8-1f906cd07bce
- KCUR (Dec 15, 2021; lines dead before crossing): https://www.kcur.org/news/2021-12-15/the-storms-across-kansas-fanned-fires-and-smoke-that-carried-as-far-as-the-great-lakes
- KCUR (16 fires recorded): https://www.kcur.org/news/2021-12-23/kansas-ranchers-face-a-long-road-to-recovery-after-devastating-wildfires
- Missouri Independent (Four County fire was multiple line-sparked blazes): https://missouriindependent.com/2021/12/20/ball-of-rolling-fire-and-smoke-wildfires-rip-through-north-central-kansas/
- Wikipedia, 2021 Kansas wildfire outbreak (aircraft grounded): https://en.wikipedia.org/wiki/2021_Kansas_wildfire_outbreak
- NBC News (Smokehouse Creek cause): https://www.nbcnews.com/news/us-news/broken-power-pole-downed-wires-caused-smokehouse-creek-fire-rcna142579
- Morrill Fire: https://en.wikipedia.org/wiki/Morrill_Fire and NEMA https://nema.nebraska.gov/articles.php?nid=352
- NOAA NGFS (5–30 min detection; Morrill Fire): https://www.nesdis.noaa.gov/news/noaas-wildfire-detection-system-game-changer-nebraskas-record-breaking-morrill-fire
- NOAA Wildland Fire Data Portal launch: https://www.nesdis.noaa.gov/news/noaa-launches-wildfire-data-portal-expanding-public-access-satellite-fire-information
- NGFS README (type flags): https://bin.ssec.wisc.edu/pub/volcat/ngfs_docs/NGFS_README_Feb2025.pdf
- DJI M350 wind spec: https://4kshooters.net/2023/05/23/dji-upgrades-their-enterprise-drone-line-with-matrice-350-rtk
- Grassfire 20% rule: https://frames.gov/catalog/66907 and https://nrfirescience.org/node/24474
- Texas A&M DFA: https://tees.tamu.edu/news/2020/03/a-crystal-ball-to-prevent-power-outages-and-wildfires.html and https://wildfiremitigation.tees.tamus.edu/
- EPRI line sensing (Gridware): https://distribution.epri.com/wildfire/public/wildfire-tech-database/asset-condition-monitoring/line-sensing-technology/
- Whisker Labs Ting Insights: https://www.whiskerlabs.com/ting-insights/
- Watch Duty outage layer: https://napavalleyregister.com/calistogan/watch-duty-updates/article_0f5057b4-df1f-4ded-9ff7-93c23458c560.html
- Lindsey FireSense testimony (10.5-hour gap; 10× size): https://sins.senate.ca.gov/sites/sins.senate.ca.gov/files/testimony_of_jack_mccall_for_lindsey_firesense.pdf
- PG&E ignition-to-outage ratios (CPUC): https://www.cpuc.ca.gov/-/media/cpuc-website/divisions/safety-and-enforcement-division/documents/batjer-letter/update-on-public-safety-additional-measures_09-28-21-0900.pdf
- Xcel EPSS: https://www.cbsnews.com/colorado/news/xcel-energy-slow-power-restoration-high-winds-colorado
- PVREA settings: https://www.aol.com/articles/xcel-energy-could-shut-off-165152543.html
- NRECA AMI 2026: https://www.cooperative.com/programs-services/bts/Documents/Advisories/Advisory-AMI-Deployment-Update-May-2026.pdf
- NRECA PLC note: https://www.cooperative.com/programs-services/bts/Documents/Advisories/Advisory-AMI-Deployment-Update-May-2020.pdf
- Vermont Electric Co-op (<190 s outage detection): https://vermontelectric.coop/automated-metering-infrastructure-ami
- Itron outage detection: https://na.itron.com/documents/d/asset-library-120736/outage-detection
- EAGLE-I 2024 dataset: https://www.osti.gov/biblio/2500278 (2014–2022: https://www.osti.gov/biblio/1975202)
- KEC testimony on HB 2107: https://kslegislature.gov/li/b2025_26/committees/ctte_s_utils_1/documents/testimony/20250306_06.pdf
- NWS Wichita GFDI via IEM: https://mesonet.agron.iastate.edu/api/1/nwstext/202607141344-KICT-FNUS63-RFDICT
- Nemaha County red-flag burn ban: https://www.mscnews.net/news/?nk=77140
- Marion County red-flag burn ban: https://nixle.us/BJWM8
- Active911 dispatch connection: https://active911.com/documentation/connecting-activealert-to-your-dispatch-center/
- Active911 integrations: https://europe.active911.com/integrations
- Western Cooperative Electric OMS and SmartHub alerts: https://westerncoop.com/sites/default/files/documents/KCL/2022/KCLFEB22_WES_v6.pdf
- Palantir/PG&E Foundry: https://www.datanami.com/this-just-in/palantir-providing-technology-to-enhance-safety-of-electric-grid-in-california/
- Burn notification rules:
  - Brown County: https://brcoks.org/1220/Burn-Permits
  - Phillips County: https://www.phillipscountyks.org/media/Emergency%20Management/Open%20Burn%20FAQs.pdf
  - Franklin County: https://franklincoks.org/930
  - Reno County: https://renocountyks.gov/media/Burn%20Permits%20Required%20June%201,%202023.pdf
  - Osage County: https://overbrookks.municipalimpact.com/documents/138/Osace-Co.-Burn-Permit-QA5.pdf
  - Gray County: https://www.grayco.org/media/1256
  - Cheney: https://www.cheneyks.org/forms/burnpermit.html
- Flint Hills SMP and April restrictions:
  - https://www.kdhe.ks.gov/508/Flint-Hills-Smoke-Management-Plan-Develo
  - https://www.kdhe.ks.gov/DocumentCenter/View/2815/Draft-Smoke-Management-Plan-Outline-PDF
  - https://www.kdhe.ks.gov/DocumentCenter/View/2822/Wichita-Meeting-Press-Release-PDF

---

## 17. Operating-picture design, borrowing from Palantir Gotham (added Fri Nov 6)

> **Internal inspiration only.** The packet's ground rule is civil use only. Don't name Gotham or use defense vocabulary in slides or UI. Say "shared operating picture," "case file," and "evidence graph."

### 17.1 What Gotham does, and the Faultline equivalent

Sources on Gotham's features are secondary (blogs and interviews) except the Foundry→Gaia doc page. Treat the feature names as approximate.

| Gotham idea | What it is | Faultline version (weekend scope) |
|---|---|---|
| **Ontology** | Typed objects, properties, and links shared by every app | §7 object types. `IgnitionCandidate` is the hub object. It maps onto the forecast team's `Situation` contract (`backend/app/situation.py`). |
| **Entity resolution** | Merges records from different feeds that describe the same thing | Merge outage-map polygon, EAGLE-I county count, meter last-gasp, and satellite pixel into **one** candidate. Use space-time windows: same feeder or within 2 km, within 20 min. This is also how §8.3 avoids double-counting. |
| **Graph / link analysis** | Expands from one object to see what connects to it | Candidate panel: "this outage → recloser R-12 → 3 line segments → 1 registered burn 1.4 km away → 2 sat pixels." Render as a small evidence graph, not a hairball. |
| **Gaia (shared live map)** | One map that every role sees, filtered to what they're allowed to see | The main console map. Layers: feeders (SYNTHETIC), outages, GFDI zones, sat detections, burns, candidates, spread cone. |
| **Timeline / temporal analysis** | Scrub events through time | Replay slider for Dec 15 2021 and for the Cottonwood Creek scenario. A per-candidate timeline compares fault, satellite hit, 911, and first truck: 1:50 → 2:21 → 2:52. |
| **Dossier (shared case file)** | A collaborative living report on one entity | **Candidate case file:** evidence list with provenance labels, score history, actions taken, and the responder's one-tap outcome. It doubles as the after-action record for honest numbers. |
| **Alerting on ontology changes** | Rules fire when objects meet conditions | §8.2 tiers (Watch → Check → Advisory → Page), triggered when a candidate's score crosses the chief's alert-budget threshold. |
| **Granular access + markings** | Per-object and per-property ACLs; users see redacted views | Role switcher (co-op / dispatch / resident). Grid detail and meter data are marked `coop-only`; dispatch gets only derived answers: location, confidence, line-dead. |
| **Provenance / lineage** | Every derived fact traces back to its sources | Already present in `situation.Provenance` (`observed | forecast | inferred | simulated | assumed`). Every candidate field carries one, and the UI shows the badge. |
| **Actions (writeback)** | Users act through typed, logged actions, not free edits | `page_district`, `request_hold_dead`, `text_downwind_area`, `text_burn_holder`, `close_candidate`. All are logged to the case file. |
| **Edge / disconnected ops (Apollo)** | Runs offline at the edge, syncs when reconnected | Field reality: one bar of cell signal and possible dispatch power loss. The candidate packet must fit in **one SMS or pager message** (location + confidence + line status + link). The dispatch console caches the last state and shows "coverage lost" when the feed goes stale. |

**Takeaway:** what's worth copying is **one object model, many role-filtered views, provenance on everything, and actions logged against a case file.** That gives four screens (map, candidate case file, timeline, alert queue) driven by one data model. Don't copy the platform breadth.

### 17.2 How Faultline feeds the forecast/recommendation layer

The forecast team's `Situation` already carries `ignition` + `weather` + provenance. Faultline's job is to **produce `Situation.ignition` earlier than anyone else can**:

- `Ignition.lat/lon` comes from the fault location. For an outage polygon, use its upwind edge on the faulted feeder. For a device lockout, use the protected segment's midpoint. Provenance is `inferred`, with source `outage map` or `coop feed (simulated)`.
- `Ignition.time` comes from the outage start time. `fire_age_min` = now − fault time.
- When a satellite pixel arrives, append it to `Ignition.points` and upgrade provenance to `observed`.
- Recommendation output (spread cone, resources) flows back into the case file, and the page carries the cone.

The result is a single chain: **fault → candidate → Situation → forecast → page**. That is the packet's detect→confirm→respond chain, in code.

### 17.3 Can we get co-op outage data today? (checked live)

- **Western Cooperative Electric (WaKeeney, KS)** publishes its outage map at `https://westerncoop.ebill.coop/maps/OutageWebMap/`.
  - Inspected Nov 6: it's a GWT app whose bundle contains `coop.nisc.mapwise.maps.services.RpcMapsService`. So it is **NISC MapWise OutageWebMap**, fetching data over GWT-RPC (`text/x-gwt-rpc`, XSRF token), **not a clean JSON API**.
- **Implication:** NISC is the dominant co-op software vendor (SmartHub / iVUE / MapWise), so many Kansas co-ops likely share this same map stack **[VERIFY by checking a few more `<coop>.ebill.coop/maps/OutageWebMap/` URLs]**.
  - One adapter could cover many co-ops, but GWT-RPC is brittle to scrape.
  - **Weekend recommendation:** don't scrape it live. Use EAGLE-I for the replay, and show the NISC map as proof that the feed exists.
  - **Pilot pitch:** the co-op enables an export from NISC OMS directly. That is a vendor-level integration, so it could serve many co-ops at once.
- **Meter-level and SCADA data stay private.** See the earlier answer: member privacy, critical-infrastructure rules, and no disclosure requirement for co-ops. Synthesize it and label it SIMULATED.

### 17.4 Prior art in the "shared picture between utilities and fire agencies" space

- **Pano AI** sells cameras plus a platform shared by utilities and first responders. It integrates Technosylva spread modeling and Western Weather Group stations.
- **Technosylva (2026)** added network sharing across agencies and utilities.
- **Indji Watch** monitors fire dispatches and satellite hotspots for utilities, with alerts within about 5 minutes.
- **Tablet Command / CentralSquare Unify** share incidents CAD-to-CAD between agencies. **None of these route a utility outage feed into fire CAD.** That is still the gap (consistent with §5).

### 17.5 Sources (added)
- Foundry → Gaia (official): https://www.palantir.com/docs/foundry/geospatial/add-ontology-data-to-gaia
- Gotham features (secondary): https://goldingresearch.substack.com/p/inside-palantir-gotham, https://ctovision.com/the-titan-release-of-palantir-gotham/, https://www.bdemerson.com/article/palantir-gotham
- Western Co-op outage page: https://www.westerncoop.com/outages-emergencies
- NISC MapWise/OMS: https://www.rfp.wiki/vendors/nisc-mapwise
- Pano AI utilities: https://www.pano.ai/utilities ; Technosylva + Pano: https://internationalfireandsafetyjournal.com/wildfire-technosylva-pano/
- Indji / situational awareness: https://tdworld.com/sponsored/article/55284215/better-situational-awareness-drives-smarter-wildfire-mitigation
- Tablet Command incident sharing: https://www.firehouse.com/events/press-release/55280462/tablet-command-inc-tablet-commands-real-time-incident-sharing-for-emergency-response-agencies-at-fdic
