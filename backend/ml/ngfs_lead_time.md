# NGFS first-detection lead time vs WFIGS discovery (KS and OK, 2026)

Script: `backend/ml/ngfs_lead_time.py` (cached, paced at 1 request per second). Lead = first NGFS `acq_date_time` within the radius, window 3 h before to 6 h after discovery, minus WFIGS `FireDiscoveryDateTime`, in minutes. Negative means NGFS saw it first. "Before discovery" counts lead < 0; "0-15 min after" counts 0 <= lead <= 15.

## Headline (10 km radius)

- Kansas alone: 56 wildfires since 2026-02-01, 37 matched, 19 unmatched (34%). Median lead -10 min, 62% detected before discovery, 8% within 15 min after. Sample is small (37); treat as indicative.
- Kansas plus Oklahoma: 1,399 fires, 497 matched, 902 unmatched (64%). Median lead -19 min, 62% before discovery, 10% within 15 min after.
- The unmatched share is the main story: 64% of KS+OK fires (and 87% of the 821 fires under 10 acres) have no NGFS detection near them in the window. NGFS does not see most small grass fires. Lead times below apply only to the fires it does see, which skew large.
- NGFS history: earliest item in both CONUS collections is 2025-04-29T19:01:17Z, so no fire from 2026-02-01 onward was excluded for lack of history. (The brief assumed 2026-02-17; the archive goes back further.)

## Kansas + Oklahoma by size (10 km)

| Size | Fires | Matched | Median lead (min) | Before discovery | 0-15 min after |
|---|---|---|---|---|---|
| under 10 ac | 821 | 103 (13%) | -34 | 56% | 8% |
| 10 to 100 ac | 280 | 149 (53%) | -9 | 60% | 11% |
| 100 to 1,000 ac | 227 | 178 (78%) | -34 | 69% | 8% |
| over 1,000 ac | 59 | 56 (95%) | -25 | 57% | 9% |
| size unknown | 12 | 11 | 0 | 45% | 45% |

## Kansas alone by size (10 km)

| Size | Fires | Matched | Median lead (min) | Before discovery | 0-15 min after |
|---|---|---|---|---|---|
| under 10 ac | 17 | 4 | -51 | 50% | 25% |
| 10 to 100 ac | 14 | 11 | -74 | 73% | 0% |
| 100 to 1,000 ac | 12 | 12 | -10 | 75% | 0% |
| over 1,000 ac | 12 | 10 | +4 | 40% | 20% |

Band cells have 4 to 12 fires: do not quote them individually.

## Sensitivity: 5 km radius

- Kansas: 33 of 56 matched (41% unmatched), median -10 min, 64% before discovery.
- KS+OK: 436 of 1,399 matched (69% unmatched), median -14 min, 61% before discovery, 11% within 15 min after.
- Tighter radius loses matches (mostly small fires) and leaves the median in the same range, so the result is not very radius-sensitive.

## Independence check

WFIGS points may come from satellite detections. Fires whose WFIGS point is within 0.002 degrees (lat and lon) of the first NGFS pixel centroid:

- 10 km: Kansas 1 of 37; KS+OK 12 of 497.
- KS+OK median lead: 485 fires without them -19 min (61% before); the 12 with them -15 min (75% before). Kansas without the one: -10 min, 61%.
- 5 km: 14 coincident of 436; excluding them median -15 min.

Removing them barely moves the result, so point coincidence is not driving it. This does not prove WFIGS times are independent of satellites: a time could still be derived from a detection without the point matching.

## Unrelated-burn risk

Rows with a detection before discovery that could be a different burn at that spot (10 km): Kansas 23 of 37; KS+OK 307 of 497. Of those, detections more than 60 minutes early: 13 (KS) and 176 (KS+OK). A detection hours early is more likely a prior burn, a prescribed burn, or a false positive. Detections within an hour before are more plausible as the same fire, but the data cannot tell them apart. The "62% before discovery" figure is an upper bound on true early detections. No confidence filter was applied to NGFS pixels.

## Comparison with the earlier polar orbiter result

Earlier: 209 matched Kansas wildfires, 2016 to 2025, median 8 minutes after discovery, 47.4% before. This is not like for like: different satellites (polar orbiter vs GOES geostationary NGFS), different fire sets (Kansas only, 209 vs 37 matched), and different years (2016 to 2025 vs February to November 2026). Directionally NGFS median is earlier, but the sample is small and the sets differ.

## Limitations

1. WFIGS discovery times are often rounded, estimated, or entered late. A negative lead may just mean a late-entered record. This is not evidence that NGFS beats a 911 call or a human report.
2. Most fires (64% KS+OK, 87% of under-10-acre fires) are not detected at all. The lead stats are survivorship-biased toward larger fires.
3. Possible circularity with WFIGS points and times (see above), unproven either way.
4. Early detections may be unrelated burns (see above). No same-fire verification.
5. Kansas sample is only 56 fires and 37 matches; one season; Oklahoma adds volume but a different region.
6. Lead is measured at scan time (`acq_date_time`) at roughly 5 to 10 minute scan cadence, so resolution is coarse.
7. Matching uses detection centroid distance only, with no size or growth check.

## Read this first: sensitivity check added after review

The medians above include detections up to 3 hours before discovery, and many of those may be an earlier, unrelated burn at the same spot. Dropping detections more than 60 minutes before discovery flips the sign:

| Group | Fires | Seen | Median, all matches | Median, early matches dropped | Before discovery | 0 to 30 min after | Later |
|---|---|---|---|---|---|---|---|
| Kansas | 56 | 37 (66%) | -9.7 | +9.8 (n 24) | 42% | 17% | 42% |
| KS + OK | 1,399 | 497 (36%) | -18.7 | +6.3 (n 321) | 41% | 25% | 35% |
| Under 10 ac | 821 | 103 (13%) | -33.7 | +26.3 (n 63) | 29% | 22% | 49% |
| 10 to 100 ac | 280 | 149 (53%) | -8.7 | +1.3 (n 110) | 46% | 26% | 27% |
| 100 to 1,000 ac | 227 | 178 (78%) | -33.7 | +1.3 (n 106) | 47% | 23% | 30% |
| Over 1,000 ac | 59 | 56 (95%) | -24.7 | +36.3 (n 33) | 27% | 21% | 52% |

Quote the dropped-early column. Fair summary: NGFS arrives about when a fire is reported, not clearly ahead of it, and it misses most fires under 10 acres (87% unseen). The 60 minute cutoff is a judgment call, and it may also drop some real early detections, so the true figure lies between the two columns. Discovery times here are mostly fires near people. The scenario's fire has nobody within four miles, which this data does not measure.
