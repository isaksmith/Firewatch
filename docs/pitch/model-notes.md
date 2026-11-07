# Presenter note: the trained model

Short version for the review. Full detail: `docs/research/scorer-v1-training-run.md` and `backend/ml/report.md`.

## Talk track (about 60 seconds)

> When a satellite sees heat in Kansas, the first question is: is this a wildfire, or one of the thousands of burns
> ranchers set on purpose every spring? We trained a model to answer that.
>
> It learned from ten years of real Kansas data, 2016 to 2025. NASA's FIRMS satellite fire detections, run through
> our own clustering, gave us fire events we labeled against the national incident record (NIFC WFIGS):
> 224 reported wildfires, 90 reported prescribed burns, and 400 unreported Flint Hills spring fires that are almost
> all ranch burns. Another 400 refinery and plant heat sources were held back to test against. For each event the model sees 27 things: how hot and big the fire looks from orbit, the wind,
> gusts and humidity at the time, terrain, distance to towns and power lines, and time of year.
>
> We trained on 2016 to 2022 and tested on 2023 to 2025, fires it had never seen. It keeps 99% of refinery and plant
> heat quiet and 82% of unreported spring pasture burns quiet, while 76% of real wildfires reach the duty officer.
> And no single score pages anyone: it takes a second independent source.

## Key facts

| | |
|---|---|
| Question | Is this satellite-detected fire a wildfire (1) or a burn (0)? Score 0–100; Investigate at 40, Escalate at 70 |
| Fire data | NASA FIRMS, VIIRS (Suomi NPP, NOAA-20) and MODIS, Kansas, 2016–2025 |
| Labels | NIFC WFIGS incidents within 3 km and −12 h/+48 h: 224 wildfire events, 90 prescribed burns |
| Weak labels | 400 unreported Flint Hills fires in March–April, counted as burns, down-weighted to equal the 90 reported burns |
| Never trained on | 400 events at refineries and plants (used only to test the heat-source guardrail) |
| Weather | Open-Meteo historical archive at each fire's time and place |
| Rows | 1,913 snapshots: each fire scored at its first, second and last satellite pass in 24 h, the way it's scored live |
| Model | XGBoost, depth 3, 300 rounds, calibrated (Platt); refit on all years for the app |
| Test | Trained 2016–2022, tested 2023–2025 (61 wildfires, 41 reported burns) |

## Results on the held-out years

- Ranking quality (ROC-AUC): **0.84** wildfire vs all burns (95% interval 0.77–0.90); **0.72** vs reported burns only, the stricter test.
- Beats the hand-written rules we started with by **+0.12** on the strict test.
- **76%** of wildfire snapshots reach Investigate or higher (87% of wildfire events within 24 h); **99%** of industrial heat stays at Monitor.
- Satellite sees **47%** of reported wildfires before the recorded discovery time, **31%** more than an hour before.
- Expected texts: about **1–9 a month** per district in spring; the Flint Hills worst case is about 18 a spring.

## If a judge asks

**What drives the score?** Wind gusts, wind, humidity, distance to town, time of year. On its own, the satellite signal barely tells a wildfire from a burn (0.53); the weather at the time does most of the work.

**What's the weakness?** The 400 weak labels are all Flint Hills springtime fires, so the model learned "Flint Hills means burn." Its five worst misses are April 2023 Flint Hills wildfires. Retraining without those labels lifts the strict score from 0.72 to about 0.82. That's our v2. Registered burns (`BURN` texts) take over the job of quieting ranch burns.

**Why trust a small dataset?** We don't lean on one number. We report confidence intervals, a year-by-year check, and the strict test against reported burns. The model also never acts alone: a page needs a second source (a neighbor's reply, a power-line fault, a sensor, a 911 call).

**Is the score a probability?** No. It's calibrated to an even wildfire/burn mix, and real wildfires are much rarer than that. We use it to rank fires and set thresholds.

**Any other model?** A small fire-day model: ten years of reported Kansas wildfires against the daily fire danger at each place (computed from historical weather). It tells the decision step how much more likely a fire start is on a Very High day than on a High one.

## Don't say

- "99% accurate" or "the model predicts wildfires." It ranks detections; the 99% is heat sources kept quiet.
- That it found fires nobody reported. Unreported fires aren't in the labels, so we can't measure that.
