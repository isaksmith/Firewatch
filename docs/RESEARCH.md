# Landscape and resources research

Compiled Fri 2026-11-06 for Firewatch 2026 (team Watch Dogs). It covers what Lockheed Martin, NASA/NOAA, agencies and startups are doing, plus the tools, data and field hardware we can reuse instead of building.

**How sure we are.** Every fact here was read on the source page itself: page text, a PDF run through `pdftotext`, a live API call, or the GitHub API. **Quoted text is exact.** Anything we could not open is listed under *Not confirmed* at the end and must not go on a slide. Downloaded sources are in the session scratchpad (`research/`).

---

## 1. The findings that shape the build

1. **Satellite alerts have already beaten 911 calls in this region, when a person is in the loop.** The National Weather Service's satellite fire-notification work, started after the Oklahoma Forestry Services fire chief "specifically asked for help to identify new fire starts" during the 2016 Oklahoma and Kansas fires, reports **"83 percent of notifications being received prior to local 911 calls."** ([Wildfire Today](https://wildfiretoday.com/?p=64611)) That is our strongest evidence the Detect layer can win minutes.
2. **The fastest public satellite feed is GOES-19 on AWS, not FIRMS.** In FIRMS, "GOES active fire detections (which are acquired every 10 minutes) are generally available within FIRMS in 20-30 minutes" ([NASA ARSET 2025, PDF](https://earthdata.nasa.gov/s3fs-public/2025-08/arset-2025-firms-part2-qa-spanish-updated-08-11.pdf)). The raw GOES-19 fire product (`ABI-L2-FDCC`) sits in NOAA's open S3 bucket ([noaa-goes19](https://noaa-goes19.s3.amazonaws.com)); a listing for 2026 day 310 returned live files. **We can ingest it directly and measure the delay ourselves**, and that measurement becomes our evidence.
3. **NOAA's Next Generation Fire System (NGFS) is not usable yet.** Its README says **"All NGFS products are non-operational and should be considered experimental."** The README gives no latency figure, and we found no machine-readable feed (only HTML alert pages). An earlier "<5 min" claim came from a search snippet and is **dropped**.
4. **Downed power lines started fires on the Starbuck day.** NWS Dodge City, March 6, 2017: **"Many fires were started by downed power lines as a result from weakened connections from the January ice storm."** ([NWS DDC Top 25 PDF](https://www.weather.gov/media/ddc/TOP_25_DDC_CWA_HISTORICAL_WEATHER_EVENTS_FINAL.pdf)) Line-fault detection already exists (EPRI's downed-conductor database lists SEL and GE/SCE methods), and Sentient Energy's MM3 line sensor reports faults over cellular or mesh. **We found no utility sending fault events to fire departments.** That is the gap Firewatch fills.
5. **Barber County already makes burners call dispatch.** Per a local-news repost of the March 24, 2025 county burn resolution, burners must notify Barber County Dispatch at least one hour before burning, and burning is banned on High or worse fire-danger days ([KCN](https://www.kcnonline.com/wp/?p=98329)). *We read this through a page summary; the site blocks direct downloads. Confirm the wording with the county clerk before quoting it.* **Dispatch already holds the burn log** we need to suppress false alarms. Barber County also runs **Everbridge** public alerts: "There is no cost to the user to sign up or maintain an Everbridge account." ([barber.ks.gov](https://barber.ks.gov/everbridge.html))
6. **Nobody sells detection to a district like Cottonwood Creek.** Pano AI: **"the typical pricing is $50,000 per station per year per customer"** ([TechCrunch 2023](https://techcrunch.com/2023/07/10/pano-series-a-extension)). In the Texas Panhandle, Xcel paid for 57 stations: "the cost was paid upfront by Xcel" ([KCBD 2025](https://www.kcbd.com/2025/11/18/xcel-using-ai-aid-wildfire-mitigation-efforts)). **Utilities pay, not fire districts.**
7. **Cheap sensors fail in wind.** The DHS Inspector General (OIG-26-05, Apr 2026) found DHS-funded N5 wildfire sensors "did not consistently detect fires or alert state and local partners", and "Wind speed and direction also negatively impacted the performance of wildfire sensors." ([OIG PDF](https://www.oig.dhs.gov/sites/default/files/assets/2026-04/OIG-26-05-Apr26.pdf)) On a 55 mph red-flag day this matters. **It argues for using data the district already has, not a field of new sensors.**

---

## 2. Lockheed Martin (the judges)

| What | Fact | Source |
|---|---|---|
| **EMBERPOINT LLC** (Jan 26, 2026) | Lockheed Martin, PG&E, Salesforce and Wells Fargo launched "a purpose-built venture that will integrate next-generation wildfire solutions to help first responders detect, prevent and fight catastrophic wildfires." Lockheed "will contribute its cutting-edge layered approach to prediction and detection, as well as military-grade autonomous response and suppression capabilities." Next: "targeting demonstrations in 2026." | [LM release](https://news.lockheedmartin.com/2026-01-26-Lockheed-Martin,-PG-E-Corporation,-Salesforce-and-Wells-Fargo-Launch-EMBERPOINT-TM-to-Transform-Americas-Wildfire-Prevention,-Detection-and-Response) |
| EMBERPOINT site | Mission page only: no products, pilots or customers. Lists State Farm as a founding member too. | [emberpoint.co](https://emberpoint.co/) |
| **Firefighting Intelligence** (LM product page) | "Our solution has proven to reduce the time to map a fire from hours to minutes." AI path prediction plus resilient comms. | [lockheedmartin.com](https://www.lockheedmartin.com/en-us/products/firefighting-intelligence.html) |
| Sikorsky + CAL FIRE (Sep 2025) | Five-year collaboration to "explore the development of an autonomous Sikorsky S-70i FIREHAWK helicopter." | [LM release](https://news.lockheedmartin.com/2025-09-03-Sikorsky-and-CAL-FIRE-Join-Forces-to-Enhance-Autonomous-Aerial-Firefighting-Technologies) |
| Cognitive Mission Manager (2021) | "an end-to-end AI-driven planning and orchestration platform" with NVIDIA and USFS Missoula. Nothing newer found. | [NVIDIA blog](https://blogs.nvidia.com/blog/lockheed-martin-wildfires-ai) |
| Skunk Works | **No wildfire program or statement found.** Don't claim one. | n/a |

**How we fit.** Lockheed works from the top down: space and air sensing, autonomous suppression, command and control, sold to agencies and utilities, with a West Coast utility partner. Firewatch is the **local first-minutes layer** that runs on a volunteer budget. It turns the data a rural county already has into a confirmed, located event with a spread forecast. That event is exactly what an autonomous responder (or EMBERPOINT) would need as input. Use their vocabulary: a **decision loop** of detect → fuse → confirm → recommend → act → log, with the human choosing the action.

---

## 3. Detection sources and how fast they are

| Source | Delay | Access | Use this weekend |
|---|---|---|---|
| **GOES-19 ABI fire product (FDC)** | Scans every 5–10 min over CONUS; delivery delay to S3 **to be measured by us** | Public S3 bucket, no key | **Yes**: new ingest |
| FIRMS VIIRS / MODIS (URT / RT / NRT) | Earthdata: URT "within 60 seconds of acquisition"; RT "Less than 1 hour"; NRT 1–3 h. ARSET 2025 gives URT about 5 min. **Only at satellite passes (a few a day).** | FIRMS area API, free MAP_KEY; sources `VIIRS_SNPP_NRT`, `VIIRS_NOAA20_NRT`, `VIIRS_NOAA21_NRT`, `MODIS_NRT` include RT and URT | Yes (already built) |
| FIRMS GOES | 20–30 min | FIRMS map and archive; **no GOES source on the area API page** | No: use S3 instead |
| FIRMS archive | VIIRS S-NPP from 2012-01-20; MODIS from 2000 | firms.modaps.eosdis.nasa.gov/download | Yes: historical test |
| NOAA NGFS | Not published | HTML alert pages only; experimental | No |
| FireSat | "at least twice daily"; "Q4 2026: Operational FireSat data will reach EFA's Early Adopters" ([HeliOps](https://www.heliopsmag.com/airattack/news/first-efa-operational-firesats-reach-orbit/)) | Early adopters only | Next-step slide |

**Fire timelines (for the historical test)**

| Fire | Verified facts | Source |
|---|---|---|
| Starbuck 2017 | Ignition **Mar 6, 2017, 11:51 AM CST**, "about 2 miles west of Gate Oklahoma"; about 662,687 acres | [NWS Amarillo](https://www.weather.gov/ama/2017_Wildfires_Feb_Mar) |
| Anderson Creek 2016 | First reported about **5:45 PM CDT, Mar 22, 2016**, western Woods County OK | [CIMSS blog](https://cimss.ssec.wisc.edu/satellite-blog/archives/20977) |
| Ranger Road 2026 | 283,283 acres; cause not identified | [NewsChannel10](https://www.newschannel10.com/2026/02/17/multiple-agencies-responding-fires-oklahoma-panhandle/), [RFD-TV](https://www.rfdtv.com/ranger-road-fire-now-55-percent-contained-as-ranchers-count-losses-start-recovery?p=63) |

No published study compares satellite first-detection with first report for these fires, so **our test would be original evidence**. Search boxes are in the research notes; no exact ignition coordinates were found.

---

## 4. Software and data to reuse (don't rebuild)

| Tool | What it gives us | License / status | Decision |
|---|---|---|---|
| **pyretechnics** (Spatial Informatics Group) | Python Rothermel surface fire and level-set spread (the ELMFIRE algorithm), Scott-Burgan fuel models | PyPI 2026.10.20; **license not declared in the GitHub API, check before adopting** | Replace the internals of `sim/spread.py`, keeping today's model as a fallback |
| ELMFIRE | Operational Fortran spread model behind Pyrecast | Release 1.1, Aug 2026 | Offline cross-check only |
| **NWS api.weather.gov** | Red Flag Warnings (`/alerts/active?area=KS&event=Red Flag Warning` returned valid GeoJSON), gridpoint forecasts | Public, no key, User-Agent required | Adopt: score boost on red-flag days |
| Open-Meteo | Hourly wind, gusts, RH | Free, non-commercial | Already used |
| **IEM ASOS** | Coldwater **3K8** (37.2281, -99.3309, Comanche), Medicine Lodge **K51** (37.266, -98.5481, Barber), Pratt, Dodge City | Public GeoJSON and CSV | Adopt: real observed wind and RH in the scenario counties |
| Kansas Mesonet REST | 5-min weather at Meade, Stafford, Harper and others | Public, but **automated ingest needs written consent** from the Weather Data Library | Ask before using |
| goes2go / raw S3 | GOES-19 FDC download | MIT | Raw S3 via httpx is enough |
| py3dep | USGS elevation | PyPI 0.19 | Optional (Kansas is flat) |
| **Apprise** | One Python call sends to SMS, email, ntfy, Pushover, Twilio | BSD-2, active | Adopt: alert fan-out |
| **ntfy** | Free push to volunteers' phones via HTTP POST | Apache-2.0, active | Adopt |
| **CAP 1.2** (OASIS) | Standard alert format that alerting software and IPAWS understand | Open standard | Adopt: export every alert as CAP |
| **PMTiles** | Single-file offline vector map for MapLibre | Active | Adopt: district map works with no signal |
| **Meshtastic** | LoRa mesh text messages without cell, Python API | GPL-3.0 lib (run as a separate process) | Adopt if we get a node; else show it |
| **Pyronear** | Open smoke-detection model for tower cameras | Apache-2.0, active | Demo on sample images |
| ArduPilot / QGroundControl / OpenDroneMap | Drone autopilot, ground station, mapping | GPL / Apache / AGPL | Pitch only |
| ChirpStack | Self-hosted LoRaWAN server | MIT | Pitch only |

---

## 5. Field hardware and existing field resources

**Already in the field (reuse first):**
- **Airport weather stations** in Comanche and Barber counties (see above).
- **County dispatch**, which already receives burn calls (Barber) and pages the district.
- **Everbridge** public alerting (Barber).
- **Electric co-ops** (Victory Electric HQ in Dodge City; outage line on their site) that own the line-fault data.
- **Kansas Forest Service**, which "provides vehicles and equipment to fire departments", runs the Excess Personal Property program, and lists a Fire Duty Officer and Situation Report ([KFS](https://www.kansasforests.org/fire_management/)).

**Hardware we priced:**

| Item | Detects | Power / link | Price (seen 2026-11-06) | Fit |
|---|---|---|---|---|
| Tempest weather station | Wind, RH, lightning | Solar; **WiFi only** | $349 ([Tempest](https://shop.tempest.earth/products/tempest)) | At the station or a ranch with WiFi |
| MLX90640 thermal (32×24) | Heat, short range | 3.3 V, I2C | $74.95 ([Adafruit](https://www.adafruit.com/product/4407)) | Fixed-asset watch only |
| FLIR Lepton 3.5 (160×120) | Heat | SPI | $172 ([GroupGets](https://groupgets.com/manufacturers/flir/products/lepton-3-5)) | Fixed-asset watch only |
| Sentient MM3 line sensor | Line faults with location | Line-powered; cell or mesh | Quote only ([Sentient](https://www.sentient-energy.com/products/mm3-line-sensor)) | The co-op's purchase; we consume its alerts |
| Dryad Silvanet | Gas | Solar; LoRaWAN; "Up to 300m" spacing | Not public ([Dryad](https://dryad.net/wildfiresensor)) | Too dense for 450 sq mi |

| DJI Matrice 4T thermal drone (aircraft, 2 batteries, hub) | Smoke and heat from the air | Battery | $8,000 ([Dronefly](https://www.dronefly.com/products/dji-matrice-4t-2x-batteries-1x-charging-hub-200w)) | Confirm-by-drone is a next step: price is real, but **its wind limit is not confirmed**, and red-flag days run 30–40 mph |

- **PurpleAir:** the public map showed **0 sensors in Clark, Comanche and Barber counties**. The nearest cluster was near Pratt. Crowd air-quality sensors are not a detection layer here.
- Cellular solar cameras, LTE routers and solar kits: search pages gave prices that couldn't be tied to a specific product, so they're **not confirmed**. Price a camera site from direct product pages before it goes on a slide.

---

## 6. Money: who pays

| Program | Fact | Source |
|---|---|---|
| Kansas Forest Service **VFA** | For rural departments, or city departments serving areas under 10,000 population; matching funds; 2027 window closes June 15, 2027 | [kansasforests.org](https://www.kansasforests.org/programs/vfa.html) |
| Kansas Volunteer Firefighter Grant | Volunteer-only departments; FY2027 applications were due 9/15/2026 | [KS Fire Marshal](https://firemarshal.ks.gov/306/Kansas-Volunteer-Firefighter-Grant) |
| USDA Community Wildfire Defense Grant | 10% match for plans, 25% for projects | [USFS](https://www.fs.usda.gov/managing-land/fire/grants/cwdg/how-to-apply) |
| FEMA AFG | FY2025 awards announced Sept 30, 2026 | [FEMA](https://www.fema.gov/grants/preparedness/firefighters/assistance-grants) |
| Sonoma County / Alchera (precedent) | "the $300,000 agreement", three-quarters FEMA hazard-mitigation funded | [GovTech](https://insider.govtech.com/california/news/sonoma-county-buys-ai-package-for-wildfire-detection.html) |

**Our answer to "who pays":** the software runs on free public data and is hosted once for the region (by the Kansas Forest Service or an emergency-management region), so it costs the district $0. Utilities pay for line sensors, as Xcel already does for cameras. Optional hardware comes through VFA or CWDG.

---

## Not confirmed (do not put on slides)

- NGFS latency and minimum fire size; any NGFS data feed.
- Whether the Wildfire Today 83% figure is from NWS Norman specifically, and its sample size.
- Clark and Comanche county burn rules; the Barber dispatch phone number and resolution number.
- Fire causes: Anderson Creek (vehicle vs power line, sources conflict), Ranger Road (undetermined).
- Exact ignition coordinates for all three fires.
- Utility-to-fire-department data sharing anywhere in Kansas.
- Watch Duty coverage of these counties (Kansas was "planned" in its 2024 annual report).
- KSICS 800 MHz radio, FirstNet and LoRa coverage; RAWS IDs; state aircraft (SEAT) bases; Guard timing; mutual-aid agreements.
- Twilio SMS price and 10DLC registration time; FAA Part 108 (drone BVLOS) status; dispatch-app APIs (Active911, IamResponding).
- pyretechnics license and runtime.
