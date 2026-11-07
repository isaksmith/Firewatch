# Firewatch scorer v1: evaluation report

Generated 2026-11-06T23:59:03Z by `ml/train.py`. Numbers are from real Kansas data; small samples, read accordingly.

## Data

- FIRMS Kansas archive, VIIRS (Suomi NPP, NOAA-20) and MODIS, 2016–2025, replayed through the app's own clustering.
- Positives: **224 wildfire events** matched to NIFC WFIGS wildfire incidents.
- Negatives: **90 prescribed burns** matched to WFIGS, plus **400 unreported Flint Hills fires in March–April** (weak label: ranchers burn about 2 million acres there each spring and almost none of it is reported; anything within 10 km and 3 days of a reported wildfire is excluded). They're weighted so that in total they count the same as the reported prescribed burns; at full weight they drowned out the reported burns, which are mostly outside the Flint Hills.
- Evaluation only: **400 events at persistent industrial heat sources** (refineries, plants). The model never trains on these; the app caps them at Monitor with a guardrail.
- Other unreported fires are left out, because most Kansas rural fires never reach WFIGS and we can't tell what they were.
- Each event contributes up to 3 rows: its features as of the first pass, the second pass, and the last pass within 24 h (1913 rows total). This matches how live scoring sees a fire.
- Temporal split: train ≤ 2022, test ≥ 2023. Test rows: {'static': 240, 'rx_weak': 184, 'wf': 130, 'rx': 82}.

## Ranking quality on the held-out years (ROC-AUC)

| Scorer | Wildfire vs all burns | PR-AUC | First pass only | Wildfire vs reported prescribed burns | Flint Hills, March–April |
|---|---|---|---|---|---|
| xgboost | 0.837 | 0.76 | 0.851 | 0.72 | 0.797 |
| logistic | 0.872 | 0.821 | 0.883 | 0.784 | 0.862 |
| rules-v0 | 0.787 | 0.681 | 0.791 | 0.603 | 0.792 |

Second look, leave-one-year-out across the training years (2016–2022, each year held out in turn):

| Scorer | Wildfire vs all burns | Wildfire vs reported prescribed burns |
|---|---|---|
| xgboost | 0.846 | 0.775 |
| logistic | 0.793 | 0.71 |

With about 100 events per year the two views can disagree on which model is ahead; both are reported rather than picking the flattering one.

## What a dispatcher would see (after guardrails; Escalate ≥ 70, Investigate ≥ 40)

| Scorer | Wildfires escalated | Wildfires at Investigate+ | Reported prescribed burns at Monitor | Unreported Flint Hills spring fires at Monitor | Industrial heat sources at Monitor |
|---|---|---|---|---|---|
| xgboost | 52% | 76% | 46% | 82% | 99% |
| logistic | 55% | 79% | 56% | 86% | 99% |
| rules-v0 | 15% | 55% | 59% | 90% | 100% |

## What drives the score (deployed model, mean |contribution| in log-odds)

| Feature | Mean abs. contribution |
|---|---|
| `in_flint_hills` | 0.9955 |
| `gust_kmh` | 0.4311 |
| `dist_town_km` | 0.3525 |
| `wind_kmh` | 0.3115 |
| `doy_cos` | 0.3025 |
| `rh_pct` | 0.2964 |
| `slope_deg` | 0.2672 |
| `elevation_m` | 0.2668 |
| `frp_max` | 0.2356 |
| `doy_sin` | 0.2202 |
| `nearby_events_24h` | 0.2124 |
| `precip_72h_mm` | 0.2047 |

## Satellite detection vs reported discovery (matched wildfires)

- Matched wildfires: 209
- Median first detection minus WFIGS discovery: **8 min** (negative = satellite first)
- Detected before the reported discovery: 47%; within 1 h after: 22%

WFIGS discovery times are often entered after the fact, so treat this as indicative.

## Caveats

- Reported wildfires skew toward fires near people (that's who reports them), so distance-to-town partly measures reporting, not risk.
- The Flint Hills weak labels are mostly right but not all: an unreported escaped burn would be labeled prescribed. The column for reported prescribed burns is the strict test.
- Elevation and time of year partly encode region and burn season (Flint Hills prescribed burns cluster in March–April at 300–500 m), so they act as proxies, not causes.
- The persistent-heat-source layer is derived from all years, including the test years.
- Scores are calibrated to an even wildfire/burn prior, not to the real share of wildfires among all detections, which is far lower. Use them to rank and to pick thresholds, not as literal probabilities.

Deployed model: refit on all 1338 training rows; Platt calibration a=0.822, b=0.070.
