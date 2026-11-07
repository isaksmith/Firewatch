# How Firewatch recommends actions

When an alert needs a decision ("Page now?", "Request mutual aid?"), Firewatch shows the three best options side by side, recommends one, and says why in numbers. This document explains how that recommendation is made, where every number comes from, and how far to trust it.

- Code: `backend/app/decision.py` (the model) and `backend/app/playbook.py` (the options, previews and receipts)
- Tests: `backend/tests/test_playbook.py`
- Data behind the fire-danger effect: [Fire-day model v1](research/fire-day-model-v1.md)

## The rule in one sentence

**Recommend the option with the lowest expected loss**, where

> expected loss = P(fire) × acres burned before enough help is on scene + (1 − P(fire)) × what a false alarm costs

Everything is measured in **acres** (false alarms in "acre-equivalents"), so every trade is in one unit the chief can judge: "a false page costs us about as much as 100 acres burned."

## Why this approach

Fire departments already use **run cards**: fixed tables such as "grass fire in zone 4 → Brush 1, Tanker 1". They're fast and predictable, but they can't weigh *how sure we are* against *how bad it would be*. On a red-flag day with a single unconfirmed signal, a run card either pages everyone (and cries wolf) or waits (and loses the cheapest minutes).

We considered three designs:

| Design | Why not / why |
|---|---|
| Fixed table (risk level × evidence level → action) | Our first version. Easy to read, but the jumps between cells are arbitrary, and the numbers shown on each option didn't drive the choice. |
| Trained classifier ("page / don't page") | Needs labeled dispatch decisions and outcomes, which don't exist publicly. It would also be a black box to the chief. |
| **Expected loss** (chosen) | The standard way to decide under uncertainty. Every input is visible and has a source, it changes smoothly as evidence arrives, the chief tunes it in plain terms, and it can say *what would change its mind* (the break-even probability). |

## Step 1: How likely is it a real fire? (P(fire))

Start from a **base rate** set by the earliest signal, then multiply the **odds** by a **likelihood ratio (LR)** for each piece of evidence. An LR of 20 means "this evidence is 20 times more likely if there is a fire than if there isn't".

### Base rates

| First signal | Base rate | Source |
|---|---|---|
| Power line lockout | 3% × danger multiplier | PG&E: reportable ignitions were 2.2–3.6% of fire-season outages (CPUC 2021). The danger multiplier comes from the [fire-day model](research/fire-day-model-v1.md) (below). |
| Satellite detection | 15% | Assumption. Michael's training set had 224 wildfires vs 490 burns (31%), but most burns are never recorded, so the real share is lower. |
| Text report or camera | 5% | Assumption |

**Danger multiplier.** It's fitted from 538 Kansas wildfires (WFIGS, 2016–2025) against daily fire danger on a statewide grid. Fire starts per day relative to a High day are: Low-Mod 0.27, Very High 2.6, Severe 6.0, Extreme 17.7.

That's fires per *day*, and on windy days line *faults* rise too. So the per-fault multiplier is the per-day ratio to the power 0.5 (`danger_exponent`). That gives Low-Mod ×0.52, High ×1, Very High ×1.6, Severe ×2.4, **Extreme ×4.2**.

A lockout on an Extreme day therefore starts at 3% × 4.2 ≈ **13%**.

### Likelihood ratios

| Evidence | LR | Why this size |
|---|---|---|
| Satellite score `s` (scorer v1) | s / (100 − s) | Michael's scores are calibrated to an even wildfire/burn prior, so this conversion is exact for the model's calibration. A score of 99 gives ×99; 50 gives ×1, no information; 30 gives ×0.43. |
| Registered neighbor nearby: "sees smoke" | ×20 | Assumption: neighbors are asked only within 3 mi; false "yes" answers are rare but happen (dust, a distant burn) |
| Neighbor: "no smoke" | ×0.4 | Assumption: weak, because terrain and haze can hide smoke |
| Neighbor: "it's my burn" | ×0.1 | Assumption |
| Text report, registered number | ×10 | Assumption |
| Text report, unknown number | ×2 | Assumption |
| Line lockout next to an already-detected fire | ×10 | Assumption |
| Camera smoke | ×8 | Assumption |
| Inside a registered burn that hasn't escaped | ×0.05 | Assumption. Michael's rules decide "escaped" (heat outside the radius, Severe+ danger, or a report from someone else). |

**Independence.** Multiplying LRs assumes the pieces of evidence are independent. Michael's confirmation rules already count each source once (one satellite, one line, each contact once), and the model only multiplies those.

## Step 2: If it is a fire, how many acres burn before enough help is there?

For each option, from the **median of the 24-run spread forecast**, which uses this fire's hourly wind, fuel map and terrain ([Design §6](DESIGN.md)):

1. **When the district is paged under this option:**
   - now, for "Page"
   - when a second source is expected: neighbors answer ~8 min after being asked
   - the next satellite look: ~30 min
   - today's 911 call: T+31, per the packet
2. **First truck on scene** = page + turnout (11 min) + drive (18 min), from the district settings.
3. **Can two trucks hold it?** Yes only if the fire stays under the district's capacity (`capacity_ha_60min`, ~371 ac) for 30 min after they arrive. A fire that is small on arrival but running at 8 mph is not "holdable".
4. **If not, mutual aid:**
   - it's requested 5 min after the page (Michael's flow drafts it at the page, and the chief approves)
   - it arrives 35 min later (packet: 30–40), or **25 min if the downwind stations got a heads-up**, because they're staffed and ready
5. **Acres** = the median-forecast burned area at that moment.

**Why the median and not the worst case?** Expected loss already accounts for uncertainty about *whether* there's a fire; using the worst case for *size* as well would double-count caution. The worst case is still shown on the map and drives the heads-up station list.

## Step 3: If it isn't a fire, what did the false alarm cost?

In acres the district would accept burning to avoid it. These are **the chief's numbers**, so ask: *"How many acres would you trade to avoid one false page?"*

| False alarm | Default | Note |
|---|---|---|
| Paging the district | 100 ac | 18 volunteers leave work; the district's budget is 2 false pages a month |
| A mutual-aid request | 250 ac | It pulls a neighbor's crew on what is a red-flag day for them too |
| A heads-up text to a station | 3 ac | No one rolls |
| A "see smoke?" text to a neighbor | 1 ac | Annoyance and opt-out risk |

## Step 4: Choose and explain

- **"How should we respond?"** (not yet paged) considers:
  - page now (it also sends the nearly free downwind heads-up)
  - ask the neighbors, or wait for their answers
  - heads-up downwind + ask
  - heads-up downwind + recheck on the next satellite pass
  - watch
  
  Once two independent sources agree, the "wait to confirm" options drop out and "heads-up only" replaces them.
- **"Do we need mutual aid?"** (after the page) considers request now, wait for Brush 1's size-up, or don't request.
- The three lowest expected losses are shown, and the lowest is recommended.
- **Break-even.** The card says at what P(fire) the runner-up would win: "That flips if P(fire) falls below 33%." This is the most useful sentence on the card. It tells the dispatcher how much the recommendation depends on the evidence being right.
- A person chooses. Every choice runs through the real paths (paging, texts, mutual aid), is logged with who chose it and whether it followed the recommendation, and can't be repeated by accident.

## Worked example: Cottonwood Creek (the packet scenario)

Red-flag Tuesday, south wind 35 mph gusting 55+, RH 11%, Extreme fire danger. A line locks out at 1:50.

**Minute 0: lockout only. P(fire) = 13%** (3% × 4.2)

| Option | If it's a fire | If it's not | Expected loss |
|---|---|---|---|
| **Heads-up downwind + wait for neighbors ✓** | ~358 ac when mutual aid arrives (2:28; heads-up given) | 1 text (3 ac-eq) | **~48** |
| Wait for the neighbors' answers | ~602 ac (2:38) | nothing | ~76 |
| Heads-up downwind + recheck on the next pass | ~960 ac (2:50) | 1 text | ~124 |

*Why:* paging on one signal costs 100+ ac-equivalent 87% of the time. A heads-up to Mullinville FD, which the fire could reach in ~42 min, costs almost nothing and saves ~10 min on mutual aid if it is real.

**Minute 8: Wes Kittle texts "1, sees smoke". P(fire) = 74%** (×20)

| Option | If it's a fire | If it's not | Expected loss |
|---|---|---|---|
| **Page the district now ✓** | ~358 ac (2:28) | 18 volunteers + a neighbor's crew (~353 ac-eq) | **~357** |
| Heads-up downwind only; don't page yet | ~1,073 ac (2:53) | 1 text | ~798 |
| Watch; don't page yet | ~1,459 ac (3:03) | nothing | ~1,084 |

*That flips if P(fire) falls below 33%.* In the replay, the duty officer pages at minute 9.

**Minute 9: paged. "Do we need mutual aid?"**

| Option | If it's a fire | If it's not | Expected loss |
|---|---|---|---|
| **Request mutual aid now ✓** | ~470 ac (2:34) | a neighbor's crew drives out (250 ac-eq) | **~413** |
| Wait for Brush 1's size-up | ~1,656 ac (3:08) | nothing | ~1,230 |
| Don't request | ~10,000 ac | nothing | ~7,495 |

**Minute 40:** a satellite pass scores the fire 99 (×99), so P(fire) > 99%. Nothing is waiting; the receipts list what was done and by whom.

## How sensitive is it?

The two judgment calls most likely to be challenged:

| Setting | Values tried | Minute 0 | Minute 8 | Minute 9 |
|---|---|---|---|---|
| `danger_exponent` (how much fire danger raises the per-fault odds) | 0 / **0.5** / 1 | Heads-up + wait at all three (P = 3% / 13% / 53%) | Page at all three | Mutual aid now at all three |
| `cost_false_page_acres` | 25 / **100** / 400 | Heads-up + wait at all three | Page at all three (flips below 28% / 33% / 48%) | Mutual aid now at all three |

On this scenario the recommendations don't depend on these assumptions. What changes is the stated confidence and how close the call is.

## Tuning for a district

Any weight can be overridden in `backend/data/districts/<district>/settings.json`:

```json
{
  "decision": {
    "cost_false_page_acres": 200,
    "danger_exponent": 0.7,
    "second_source_min": 12
  }
}
```

The app's "How this is decided" panel lists every active weight and its source, and marks overridden ones as "District setting".

## Limits, and how this gets better

- **Most likelihood ratios are assumptions.** They are sized to be reasonable, not measured. Every recommendation and its outcome (fire / no fire / size) is logged, so after a season the ratios can be re-fitted from the district's own alerts. That's the single biggest improvement available.
- **The 3% line-fault base rate is Californian.** A Kansas co-op's outage log matched to fires would replace it.
- **The danger multiplier comes from reported fires only** (WFIGS), which probably overstates the effect at high danger. See the [fire-day model's limits](research/fire-day-model-v1.md#limits-read-before-quoting-a-number).
- **"Acres" stands in for harm.** Homes, livestock and people in the path matter more than grass, and the spread forecast already lists them. A future version could weight acres by what's on them.
- **Timing assumptions** (8 min for a neighbor's answer, 30 min to the next pass, 35 min for mutual aid) come from the scenario and the packet, and should be replaced with the district's own numbers.
- **Our fire-danger index is the Australian McArthur GFDI,** not the NWS Kansas Grassland Fire Danger Index, so the band names match but the scales don't.

The model decides nothing by itself. It ranks options and shows its arithmetic, and a person chooses.
