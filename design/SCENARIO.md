# Shared scenario facts for every concept screen and slide

Use these exactly. All numbers are **sample data for a concept**; every screen shows a small footer: "Concept screen. Sample data from the Cottonwood Creek scenario."

## Place (fictional, modeled on Clark / Comanche / Barber counties KS)
- Town and station: **Cottonwood** (pop. 900), Cottonwood Creek Fire District, 450 sq mi.
- Roads on a 1-mile section grid. East-west county roads are numbered (CR 10, CR 12, CR 14, CR 16), and run 1 mile apart northward. North-south roads are lettered (Rd H, Rd J, Rd K, Rd L), also 1 mile apart. Gravel.
- Station at CR 10 & Rd P (southeast). **Ignition: Rd K, half a mile south of CR 12**, 11 miles northwest of the station, beside an oil-lease power line in CRP grass.
- **Miller ranch house:** Rd K, 3 miles north of ignition (just north of CR 14 and CR 16 are further). Families: Miller (house), Hale (cattle on CR 14 east), Ortiz lease (water truck at the tank battery on CR 12 & Rd J).
- **Permitted burns today (the decoys):**
  - **Henderson pasture burn:** 4 mi east of ignition near CR 12 & Rd O. Called in to county dispatch at 10:40 for 11:00–16:00.
  - **Ortiz pasture burn:** 6 mi southwest near CR 8 & Rd G. Called in at 11:15 for 12:00–17:00.

## Weather (Tuesday, mid-March)
Red Flag Warning since 6:00 am. South wind 35 mph, gusts 55, humidity 11%, 78°F, no rain in 5 weeks. Wind from the south, so the **fire head runs north**.

## Fire (scenario)
- 1:50 pm: line falls, ignition.
- The head moves north at about 3 mph on average; the flanks widen.
- Head reaches CR 14 about **2:29 pm**, the Miller house about **2:49 pm**.
- The 60-min forecast from 2:05 is a north-pointing teardrop about 3 mi long and 1.2 mi wide.

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
