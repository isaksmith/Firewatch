# Shared scenario facts for every concept screen and slide

Use these exactly. All numbers are **sample data for a concept**; every screen shows a small footer: "Concept screen. Sample data from the Cottonwood Creek scenario."

> **Geography update (canonical).** The place and positions below replace the earlier map. They come from `backend/data/scenarios/cottonwood-creek.json` and `backend/data/districts/cottonwood-creek/` on this branch. The screens, PNGs and PDF decks in this folder still show the old map positions (road labels such as "Rd K", "CR 12", and the old family names) and **need a redraw** before they go in the deck. The story times in this file are unchanged. The Butler County version of the scenario is dropped.

## Place (fictional, modeled on Clark / Comanche / Barber counties KS)
- The district is Cottonwood Creek Fire District, 450 sq mi, placed on a stand-in square centered on Coldwater (Comanche County) so real terrain and land cover are used.
- **Station 1 (Coldwater stand-in):** 37.2689, -99.3268.
- **Ignition:** 37.3821, -99.4681, beside a 40-year-old oil-lease power line in CRP grass, about 11 miles northwest of the station. Co-op feeder 4 recloser locks out at 1:50 pm.
- **Neighbors to text (roster positions):**
  - Wes Kittle (rancher), 37.3821, -99.4512, about 1 mile east of the ignition
  - June Pfannenstiel (rancher), 37.3611, -99.4783
  - Dale Hutchins (rancher), 37.3991, -99.4603
  - Marla Ostrander (rancher), 37.4076, -99.4565
  - Gary Pruitt (rancher), 37.3621, -99.3537
  - Cody Brandt (lease pumper), 37.3841, -99.4910
  - Luis Orozco (lease pumper), 37.4421, -99.5477
  - Ray Delk (lease water truck), 37.3981, -99.4631
  - Harlan Shafer (disc), 37.4031, -99.4601
  - Tom Wiebe (disc), 37.4111, -99.4482
- **Mutual-aid stand-ins:** Protection FD 37.2006, -99.4835; Wilmore FD 37.3364, -99.2093; Mullinville FD 37.5872, -99.4757; Greensburg FD 37.6028, -99.2932; Ashland FD 37.1886, -99.7657.
- **Permitted burns today (the decoys), from the scenario file:** a 160-acre pasture burn at 37.384, -99.585 (Saturday permit) and a 240-acre burn at 37.3, -99.56 (Sunday permit). Both are marked extinguished in the file. The story in this document has two called-in burns that morning; match the times to the scenario file when the screens are redrawn.
- Roads are described on the redrawn map from real OpenStreetMap data, not the old invented section grid.

## Weather (Tuesday, mid-March)
Red Flag Warning since 6:00 am. South wind 35 mph, gusts 55, humidity 11%, 78°F, no rain in 5 weeks. Wind from the south, so the **fire head runs north**.

## Fire (scenario)
- 1:50 pm: line falls, ignition.
- The head moves north at about 3 mph on average; the flanks widen.
- Head reaches CR 14 about **2:29 pm**, the Miller house about **2:49 pm**.
- The 60-min forecast from 2:05 is a north-pointing teardrop about 3 mi long and 1.2 mi wide.
- **Worst case (decided 2026-11-06):** the existing spread model (`backend/app/sim/spread.py`) runs the head at about 7.5 mph in this wind. Timed from ignition at 1:50 (corrected 2026-11-06), the fire reaches CR 14 about **2:05**, as the page goes out, and the Miller house about **2:15**. So in the worst case the Miller ranch gets about 10 minutes' warning, and none at all today. Show both: the story uses about 3 mph, and the model's run is labelled "worst case (spread model)". Never present either as a measurement.

## Weather station
IEM lists Coldwater (3K8) as offline since 2022. Use **Medicine Lodge airport (K51)** for live weather and data-age labels: "Weather (Medicine Lodge airport): 6 min ago". Older screens and decks that say Coldwater need this change.

## Timeline: today vs Firewatch (targets, not results)
| Time | Today | With Firewatch |
|---|---|---|
| 1:50 | Nobody knows | Co-op line fault + red flag + dry grass → quiet **"Possible fire"** notice to chief and duty officer |
| ~2:00 | (nothing) | GOES satellite hotspot 0.3 mi from the fault → score 87 → **district paged ~2:05** |
| 2:05 | (nothing) | Henderson and Ortiz burns stay "Monitor": "Matches a burn called in to dispatch at 10:40" |
| 2:05 | Chief at work, 30 mi away | Chief's phone: map, path, "Request mutual aid" (mutual aid asked at 2:06, not 3:10) |
| 2:06 | Rancher unaware | Miller, Hale, Ortiz lease get a text; disc line and water truck move |
| 2:17 | Driver sees smoke, no signal | His text sends when he gets a bar (2:21); it joins the same fire |
| 2:21–2:23 | 911 call, district paged | Already paged ~16 min earlier |
| 2:16 / 2:34 | Brush 1 rolls 2:34, on scene 2:52 (fire age 62 min, head 2–3 mi out) | Rolls ~2:16, on scene ~2:34 (fire age ~44 min), sent to the east flank on CR 12 |

## Alert score and reasons (plain words)
Score **87 out of 100**, recommendation **Page the district**. Reasons, in this order:
1. A power-line fault on the Ortiz lease line at 1:50, 0.3 mi away.
2. The satellite saw new heat at 2:00, and again at 2:05; it is growing.
3. Red Flag Warning: wind 35 mph gusting 55, humidity 11%.
4. No burn has been called in near here.

Data age shown per source, e.g. "Satellite: 3 min ago", "Line fault: 15 min ago", "Weather (Coldwater airport): 6 min ago".

## Messages
- **Text to chief (≤160 chars):** `FIRE 87/100 Rd K half mi S of CR 12, 11mi NW of station. Head going N ~3mph. CR 14 by 2:29. Reply 1=on it 2=not a fire`
- **Text to Miller ranch:** `Cottonwood Creek FD: grass fire 3 mi south of your house, moving north. Could reach you near 2:49. Reply 1 if you can move cattle or disc a line.`
- **Quiet notice at 1:51:** "Possible fire: power-line fault near Rd K and CR 12 on a red flag day. No smoke seen yet. We'll page if the satellite confirms."

## Delivery routes (all at once)
App push → text message → county dispatch radio pager (by email-to-page; works with no cell) → LoRa mesh radio at the station (optional).

## Copy rules
Plain words, sentence case, no all-caps labels, no em dashes, no jargon (say "satellite", not "GOES FDC" on user screens; technical names are fine on the integration slide). One obvious main action per screen. Undo instead of "Are you sure?".
