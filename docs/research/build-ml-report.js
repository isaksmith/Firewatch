// Builds docs/research/ml-models-report.txt and .docx from one source. Its package isn't a project dependency:
//   npm i --prefix /tmp/fwreport docx
//   NODE_PATH=/tmp/fwreport/node_modules node docs/research/build-ml-report.js
const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun, Header, Footer, AlignmentType,
  LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType, PageNumber, TabStopType, TabStopPosition,
} = require("docx");

const OUT = __dirname;
const FIG = path.join(OUT, "figures");
const DATE = "November 7, 2026";

// ---------- content ----------
// Blocks: h1, h2, p (inline **bold**), bullets, table {head, rows, widths (fractions)}, fig {file, caption}.

const B = [];
const h1 = (t) => B.push({ h1: t });
const h2 = (t) => B.push({ h2: t });
const p = (t) => B.push({ p: t });
const bullets = (...items) => B.push({ bullets: items });
const table = (head, rows, widths) => B.push({ table: { head, rows, widths } });
const fig = (file, caption) => B.push({ fig: { file, caption } });

h1("Summary");
p("Firewatch has four models and three supporting analyses behind the alerts it sends. This report covers what each one is trained on, how well it does, how the app uses it and where it can mislead. Every number comes from the research reports in docs/research and backend/ml, regenerated from real data.");
bullets(
  "**Satellite scorer (xgb-v1)** separates wildfires from prescribed burns for satellite-detected fires. ROC-AUC on the held-out years 2023–2025 is 0.837 against all burns and 0.720 against reported prescribed burns, the stricter test. Its biggest weakness is a labelling shortcut that teaches it \"Flint Hills in spring means a burn\". A v2 recipe that drops that shortcut scores 0.825 on the strict test.",
  "**Fire-day model (v1)** measures how fire danger changes how many wildfires start. Extreme days see 17.7× the Kansas wildfire starts per day of a High day, and Low-Moderate days 0.27×. The app uses it to set the starting chance that a power-line lockout is a fire.",
  "**Sensor smoke model (v1)** measures how much a mesh sensor's smoke reading should count. The PM2.5 rule the app already used is worth ×9.8 (95% CI 5.6–19.8), against the ×15 it had assumed. A bigger rise now counts for more, up to ×20. A gas-sensor drop adds a small, capped weight.",
  "**Spread forecast (v2)** is a physics-based 24-run ensemble, not a trained model. In a back-test on three real Plains fires, its range reached 77% of the places satellites later found fire, against 34% for the original single-run estimate.",
  "**Supporting analyses:**",
);
B.push({ bullets: [
  "Alert load: about 30 texts per spring across four stand-in districts.",
  "NOAA's experimental NGFS satellite product: it arrives about when a fire is reported, not clearly ahead of it, and misses 87% of fires under 10 acres.",
  "Satellite detection lead time: satellites see about a third of reported wildfires more than an hour before discovery.",
], level: 1 });
p("**How they fit together.** No single dataset links satellite detections, ground sensors, weather and fire outcomes. So each model answers one question, and the decision model combines them as likelihood ratios on the odds that an event is a fire. The rules engine decides alert levels from independent sources, and the models set the stated chance of fire and the expected-loss recommendation.");

h1("1. Model inventory");
table(
  ["Model", "Type", "Trained or tested on", "File", "What it drives"],
  [
    ["Satellite scorer xgb-v1", "XGBoost, 27 features, Platt-calibrated", "1,913 snapshots of 1,114 Kansas fire events, 2016–2025 (FIRMS + WFIGS)", "backend/data/model/xgb_v1.json, meta.json", "Score 0–100 per satellite event, alert level, likelihood ratio s/(100−s)"],
    ["Fire-day model v1", "Rate ratios with Poisson intervals", "538 WFIGS Kansas wildfires, 2016–2025, Open-Meteo daily weather", "backend/data/model/fire_day.json", "Danger multiplier on a line fault's base rate; large-fire share on the alert"],
    ["Sensor smoke model v1", "Two one-feature logistic curves", "2,795 Flint Hills PurpleAir sensor-days (2022); 98,571 BME688/690 readings from controlled burns", "backend/data/model/smoke_sensor.json", "Weight of a mesh sensor's smoke signal in P(fire)"],
    ["Spread forecast v2", "Physics ensemble (24 runs), not trained", "Back-tested on Anderson Creek 2016, Starbuck 2017, Ranger Road 2026", "backend/app/sim/", "Acres burned before help arrives, in the expected loss; map outline"],
  ],
  [0.17, 0.17, 0.26, 0.2, 0.2],
);
p("Not covered: the language model that answers texted questions (OpenRouter, app/llm.py). It is a hosted general-purpose model, it isn't trained here, and it plays no part in scoring or alert levels.");

h1("2. How the models combine");
p("For each event, the decision model (app/decision.py) works out P(fire). It starts from a base rate set by the earliest signal and multiplies the odds by a likelihood ratio for each independent piece of evidence:");
table(
  ["Step", "Value", "Source"],
  [
    ["Base rate: power-line lockout", "3% × danger multiplier (0.52 to 4.21)", "PG&E outage-to-ignition rate × fire-day model"],
    ["Base rate: satellite detection", "15%", "Assumption: most Kansas hotspots are planned burns"],
    ["Base rate: anything else first", "5%", "Assumption"],
    ["Satellite score s", "× s/(100−s)", "Satellite scorer (calibrated to an even wildfire/burn prior)"],
    ["Smoke sensor, PM2.5", "× 8.8 at the trigger, up to × 20", "Sensor smoke model"],
    ["Gas sensor", "up to × 3 (× 1.7 on top of PM2.5)", "Sensor smoke model, capped by assumption"],
    ["Neighbor sees smoke / no smoke / my burn", "× 20 / × 0.4 / × 0.1", "Assumptions"],
    ["Text report, registered / unknown", "× 10 / × 2", "Assumptions"],
    ["Camera smoke; line fault next to a fire; inside a registered burn", "× 8; × 10; × 0.05", "Assumptions"],
  ],
  [0.36, 0.3, 0.34],
);
p("The spread forecast then gives the acres a fire would burn before enough help arrives under each response option. The option with the lowest expected loss, P(fire) × acres plus (1 − P(fire)) × the false-alarm cost, is recommended. Alert levels come from the confirmation rules (app/confirm.py): one independent source reaches Investigate, two reach Escalate. The model can raise a level when the stakes call for it, but never lowers one.");
p("**What is fitted and what is assumed.** Three inputs are now fitted: the satellite likelihood ratio, the danger multiplier and the sensor weights. The people-signal ratios and the false-alarm costs are still planning assumptions. They can only be fitted once Firewatch logs outcomes.");

h1("3. Satellite scorer (xgb-v1)");
h2("What it does");
p("For each fire event built from NASA FIRMS satellite detections (VIIRS and MODIS), it scores 0–100 how much the event looks like a wildfire rather than a burn. Score 40 or more reaches Investigate, and 70 or more counts as a strong detection that reaches Escalate on its own. Guardrails cap events at known industrial heat sources at Monitor and raise events near towns. Each alert shows the features that pushed the score up or down.");
h2("Training data");
table(
  ["Kind", "Events", "Rows", "Role"],
  [
    ["Reported wildfires (WFIGS)", "224", "455", "Positive"],
    ["Reported prescribed burns (WFIGS)", "90", "181", "Negative"],
    ["Unreported Flint Hills fires, March–April", "400", "702", "Weak negative, down-weighted"],
    ["Industrial heat sources", "400", "575", "Evaluation only"],
  ],
  [0.46, 0.14, 0.14, 0.26],
);
p("Each event contributes up to 3 snapshots: first pass, second pass and last pass within 24 h. The 27 features cover:");
bullets(
  "satellite: fire power, detections, passes, growth;",
  "weather: wind, gusts, humidity, rain, the McArthur fire danger index;",
  "terrain;",
  "distance to towns and power lines;",
  "time of year;",
  "an in_flint_hills flag.",
);
p("Training covers 2016–2022 and testing 2023–2025. The deployed model was refit on all years.");
h2("Results");
table(
  ["Scorer", "vs all burns (test)", "95% CI", "vs reported burns (test)", "95% CI"],
  [
    ["xgboost (shipped)", "0.837", "0.77–0.90", "0.720", "0.62–0.82"],
    ["logistic regression", "0.872", "0.81–0.92", "0.784", "0.69–0.86"],
    ["rules-v0 (fallback)", "0.787", "0.72–0.85", "0.603", "0.50–0.70"],
  ],
  [0.28, 0.18, 0.18, 0.18, 0.18],
);
bullets(
  "XGBoost and logistic regression are within noise: logistic leads on the test years, while XGBoost leads in leave-one-year-out cross-validation over 2016–2022 (0.846 vs 0.793). XGBoost beats the rules scorer against reported burns by +0.12 (95% CI +0.01 to +0.23).",
  "**At the deployed thresholds:** 87% of test wildfires reach Investigate or higher within 24 h and 61% reach Escalate. On the other side, 59% of reported prescribed burns also reach Investigate or higher, and 20% reach Escalate.",
  "**The heat-source guardrail is essential:** without it, 44% of industrial heat-source snapshots would reach Investigate or higher.",
  "**Calibration on test snapshots:** Brier score 0.180 and expected calibration error 0.05, at the even prior the score is calibrated to. The score is not a real-world probability, which is why the decision model starts satellite events at 15%.",
  "**Robustness:** hyperparameters move leave-one-year-out AUC by at most 0.04. Ten random seeds move test AUC by under 0.01.",
  "**What carries the signal:** satellite features alone barely separate wildfires from burns (0.53 against reported burns). Wind, gusts and humidity carry most of the legitimate signal.",
);
fig("scorer-v1/bootstrap_auc.png", "Satellite scorer: ROC-AUC on the held-out years with 95% bootstrap intervals.");
h2("Main weakness: the Flint Hills labels");
p("All 400 weak negatives lie in the Flint Hills in March–April by construction, so in_flint_hills became the strongest feature, worth about ±1 log-odds. Real Flint Hills wildfires score low: the five worst-scored test wildfires are all April 2023 Flint Hills fires. Reported burns just outside the region score high: all eight top false alarms. Retraining under five label designs shows the problem is the labels:");
table(
  ["Label design", "vs reported burns (cross-validation)", "vs reported burns (test)", "vs unreported Flint Hills fires (test)"],
  [
    ["v1: weak negatives, reduced weight", "0.775", "0.720", "0.889"],
    ["Weak negatives, full weight", "0.736", "0.632", "0.910"],
    ["No weak negatives", "0.818", "0.813", "0.675"],
    ["No weak negatives, no in_flint_hills (v2 candidate)", "0.822", "0.825", "0.684"],
  ],
  [0.4, 0.2, 0.2, 0.2],
);
p("The v2 candidate is better on the strict metric on both views. Its cost is that it can no longer quiet unreported Flint Hills spring burns, a job burn notices and the likely-prescribed suppression rule may do better. Before adopting v2, replay a March–April season to measure the extra alert volume.");
fig("scorer-v1/label_design.png", "Satellite scorer: effect of the negative-label design.");
h2("Limits");
bullets(
  "Labels reflect reporting. WFIGS holds the fires someone reported, so distance to town partly measures who reports fires.",
  "The test set is small: 61 wildfires and 41 reported burns, about 40% of them from 2023. One unusual season moves results by about 0.1.",
  "The heat-source layer was built from all ten years, so heat-source results are optimistic.",
  "The last-pass snapshot is weaker (AUC 0.72), and the app rescores events as passes arrive.",
);

h1("4. Fire-day model (v1)");
h2("What it does");
p("It answers two questions about the day, not the individual fire. First, on a day at a given fire-danger level, how many more wildfires start than on a High day? Second, of the fires that started at that level, what share grew past 300 and 1,000 acres?");
h2("Data and method");
p("The data is 538 NIFC WFIGS Kansas wildfires, 2016–2025. Weather is Open-Meteo archive daily maximum temperature, minimum humidity and maximum wind on a 1° grid (21 points). The danger index is the app's McArthur grassland index with a seasonal curing table, banded as the app bands it. Every grid point on every day is one point-day of exposure. The rate ratio (RR) compares fires per point-day with High days, with log-normal Poisson intervals.");
h2("Results");
table(
  ["Danger band", "Share of point-days", "Fires", "Rate ratio (95% CI)", "Per-fault multiplier", "Lockout starting P(fire)", "Fires ≥ 1,000 ac"],
  [
    ["Low-Moderate", "89.3%", "327", "0.27 (0.22–0.34)", "0.52", "1.6%", "9%"],
    ["High", "8.4%", "112", "1.0 (reference)", "1.00", "3.0%", "32%"],
    ["Very High", "1.9%", "66", "2.63 (1.94–3.57)", "1.62", "4.9%", "33%"],
    ["Severe", "0.3%", "25", "5.95 (3.86–9.19)", "2.44", "7.3%", "60%"],
    ["Extreme", "<0.1%", "8", "17.74 (8.66–36.34)", "4.21", "12.6%", "50%"],
  ],
  [0.15, 0.13, 0.08, 0.2, 0.14, 0.15, 0.15],
);
p("The rate ratio counts fire starts per day. A line fault's chance of igniting is only part of that: on windy, dry days both faults and ignitions per fault rise. Public data can't split the two, so the app gives each half the increase in log terms (per-fault multiplier = RR^0.5, a district setting). On the Cottonwood Creek scenario, the recommendation is the same at exponents 0, 0.5 and 1. Only the stated confidence changes.");
fig("fire-day/ignition_rate_by_band.png", "Fire-day model: wildfire starts per day by danger band, relative to High.");
h2("Limits");
bullets(
  "Reporting bias: bigger fires are likelier to be reported, so the rate ratio at high danger is probably overstated.",
  "It isn't specific to power lines: almost all causes are \"Human\" or blank.",
  "Coarse weather (1°, daily extremes) and a seasonal curing table instead of observed greenness.",
  "Small counts at the extreme end (8 fires on Extreme days): see the intervals.",
);

h1("5. Sensor smoke model (v1)");
h2("What it does");
p("The tower smoke rule decides whether a mesh sensor reading is smoke. It needs a PM2.5 rise of 50 µg/m³ or more over the node's 3-hour baseline, a fine-particle ratio that isn't dust, and other towers not rising too (regional haze). This model sets how much a reading that passes should count toward P(fire). It also adds a second, weaker weight from the BME680/688 gas sensor on bare nodes.");
h2("Particulate");
p("The data is the Colorado State University Flint Hills 2022 campaign: 36 PurpleAir sensors (the Plantower family our PMSA003I belongs to), hourly from March to May. The labels are the study's expert daily designations, which separate smoke from a nearby fire from transported regional haze. There are 2,795 labelled sensor-days, 704 of them local smoke. The feature is the PM2.5 rise at the hour with the day's largest rise, computed exactly as the app computes it live.");
table(
  ["Rise threshold (µg/m³)", "Local-smoke days caught", "Other days flagged", "Likelihood ratio (95% CI)"],
  [
    ["≥ 20", "50.0%", "9.8%", "5.1 (3.7–7.1)"],
    ["≥ 30", "32.7%", "4.8%", "6.8 (4.6–10.1)"],
    ["≥ 50 (the app's rule)", "15.1%", "1.5%", "9.8 (5.6–19.8)"],
    ["≥ 100", "4.5%", "0.2%", "19.0 (5.6–91.1)"],
  ],
  [0.3, 0.24, 0.2, 0.26],
);
bullets(
  "The rule's measured ×9.8 replaces the assumed ×15 for any sensor signal without a model weight.",
  "A logistic curve in ln(1 + rise) fits the banded likelihood ratios (AUC 0.823, 95% CI 0.784–0.856). It gives ×2.3 at 20 µg/m³, ×8.8 at 50 µg/m³ and reaches the ×20 cap at about 90 µg/m³. The cap is there because the curve runs ahead of the data above 50 µg/m³, and live single readings spike higher than hourly means.",
  "Extra features did not add skill in leave-one-week-out cross-validation: absolute PM level, the previous hour, and sensors 15–60 km away. Humidity helped, but mostly because burn days are dry. The decision model already weighs fire weather, so humidity is left out.",
);
fig("sensor-smoke/pm_likelihood_ratio.png", "Sensor smoke model: likelihood ratio of local smoke by PM2.5 rise, observed bands and fitted curve.");
h2("Gas");
p("The data is the University of Cagliari smoke detection dataset: 5 BME688/690 nodes 100 m from controlled vegetation burns, 2 sessions, 52 hours of recordings. The feature is gas resistance over the node's own clean-air baseline (R/R0). Our telemetry reports one heater step whose temperature isn't known, so only the ratio transfers. Leave-one-node-out AUC is 0.902. The app's trigger, R/R0 ≤ 0.5 on two readings in a row, catches 70.6% of smoke readings and flags 3.6% of clean ones in the experiment.");
p("The clean air in that experiment is only about 37 minutes per session, so the field false-alarm rate is unknown. Until a supervised burn trial measures it:");
bullets(
  "gas is capped at ×3;",
  "on a node with a PM sensor it adds at most ×1.7;",
  "on its own it only adds weight to an event already open within 8 km;",
  "it never opens an event or counts as a source.",
);
h2("Limits");
bullets(
  "One season and one place, mostly prescribed-burn smoke; wildfire smoke on a windy winter day may look different.",
  "Daily labels against one hourly feature, and hourly means in training against single live readings.",
  "Gas: two sessions, Mediterranean vegetation, a dev-kit heater profile rather than Meshtastic's.",
);

h1("6. Spread forecast (v2, back-tested)");
p("The forecast is a physics-based grass-fire spread model. It is a 24-run ensemble using hourly wind, the NLCD/USDA cropland fuel map and terrain, with ±15% wind speed and ±15° direction spread standing in for forecast error. It isn't trained on data, but it was back-tested from the first satellite look of real Plains fires against every later detection within 16 hours. Weather is the archive's actual hourly weather, so this tests the fire model, not a weather forecast.");
table(
  ["Detections scored", "v2 median forecast", "v2 worst case", "v1 (single run, constant wind, all grass)"],
  [
    ["6,027 polar-orbiter pixels (VIIRS, MODIS)", "59%", "77%", "34%"],
    ["832 GOES pixels (every 30 min)", "41%", "66%", "37%"],
  ],
  [0.34, 0.2, 0.18, 0.28],
);
p("\"Reached\" means the share of later detected fire pixels where the forecast already had fire.");
bullets(
  "**Extreme-wind days ran 2–4× faster than the base formula.** Starbuck 2017 and Ranger Road 2026 ran at about 20% of their 80–90 km/h gusts. 6 of the 24 runs now spread at 20% of gust speed on dry, gusty days. Ranger Road's worst case at +12–14 h now reaches 53–57 km against the 49–51 km seen.",
  "**On a moist night (Anderson Creek 2016) the forecast runs long:** 41 km median against 24 km seen at 15 h.",
  "**Ranger Road's first hour is under-called:** 1,306 acres median against a reported 15,000.",
  "**Limits:** only three fires, no suppression in the model, and hindcast weather. \"Reached\" rewards over-prediction, so the full report puts it next to how far the fire actually ran.",
);
fig("spread-backtest/starbuck-2017.png", "Spread back-test: Starbuck fire, March 2017.");

h1("7. Supporting analyses");
h2("Alert load (the cry-wolf number)");
p("The real scorer, guardrails and level rules were replayed on every satellite event in March–April, 2016–2025, inside 12-mile circles around four stand-in districts (863 events). On the held-out springs 2023–2025, the four together get 30.3 texts per spring (15.2 a month), including 13.3 \"Reply PAGE\" escalations.");
table(
  ["District", "Texts per month (spring)", "Escalate per spring", "Worst 7 days"],
  [
    ["Comanche", "1.2", "1.3", "4 texts"],
    ["Clark", "0.5", "0.3", "2 texts"],
    ["Barber", "4.3", "7.0", "7 texts (6 Escalate)"],
    ["Chase (Flint Hills)", "9.2", "4.7", "12 texts"],
  ],
  [0.3, 0.24, 0.22, 0.24],
);
p("98–99% of alerted events match no reported incident. That is not a false-alarm rate: WFIGS has almost no Kansas incidents near these circles. The figure is satellite-only, with no burn registry or replies, so it probably overstates load where registered burns would be suppressed.");
h2("NGFS (NOAA's experimental geostationary fire product)");
bullets(
  "**Lead time:** of 56 Kansas wildfires since February 2026, 37 matched an NGFS detection. Across Kansas and Oklahoma, 497 of 1,399 fires matched. Counting matches up to 3 hours early, the median detection comes before discovery: 10 minutes in Kansas, 19 across both states. Many of those early hits are probably an earlier burn at the same spot. Dropping detections more than an hour early moves the Kansas and Oklahoma median to about 6 minutes after discovery. The fair summary is that NGFS arrives about when a fire is reported.",
  "**Coverage gap:** 64% of Kansas and Oklahoma fires, and 87% of fires under 10 acres, have no NGFS detection nearby. It sees mostly larger fires.",
  "**Extra load, spring 2026:** up to 149 extra Investigate texts across the four circles. 127 of them were in the Flint Hills, mostly April burn season, an upper bound since burn suppression can't be replayed. NGFS alone never pages.",
);
h2("Satellite detection lead time (polar orbiters)");
p("For 209 matched wildfires, the first FIRMS detection came a median 8 minutes after the reported discovery. 47% were seen first by satellite and 31% more than an hour first. Small fires (under 100 acres) are seen a median 59 minutes before their report. WFIGS discovery times are often entered after the fact, so treat this as indicative.");

h1("8. Cross-cutting limits and next steps");
h2("Limits shared by all models");
bullets(
  "**Labels come from what gets reported.** WFIGS is the only source of fire outcomes for the scorer and the fire-day model, and most rural Kansas fires never reach it.",
  "**Small samples everywhere:**",
);
B.push({ bullets: [
  "41 reported burns in the scorer's test years;",
  "8 fires on Extreme days;",
  "one season of sensor data;",
  "three back-tested fires.",
], level: 1 });
bullets(
  "**Independence is assumed:** P(fire) multiplies likelihood ratios. The confirmation rules count each source once, and all sensors count once, but residual correlation is not measured.",
  "**No outcomes logged yet.** None of the people-signal ratios or false-alarm costs is fitted.",
);
h2("Recommended next steps");
B.push({ numbers: [
  "Train the v2 satellite scorer (no weak negatives, no in_flint_hills), and replay a March–April season for its alert volume before adopting it.",
  "Make \"wildfire vs reported prescribed burns\" the primary scorer metric, with bootstrap intervals.",
  "Get more reported burns: Kansas burn permits, Oklahoma and Nebraska WFIGS, Firewatch's own burn notices.",
  "Log every alert's outcome (fire, burn, nothing) so the likelihood ratios and costs can be refitted on the district's own data.",
  "Calibrate the spread formula on GOES 5-minute data from more fires, instead of only widening the worst case.",
  "Run a supervised burn trial with the field nodes to measure gas and PM false alarms, then refit the sensor curves.",
  "Get co-op outage records to split the fire-day rate ratio into fault frequency and ignition per fault.",
] });

h1("Appendix: files and rebuilding");
table(
  ["Model", "Code", "Full report", "Rebuild (from backend/)"],
  [
    ["Satellite scorer", "ml/train.py, ml/analyze.py, app/scoring/", "docs/research/scorer-v1-training-run.md; backend/ml/report.md", "python -m ml.download; ml.build_dataset; ml.train; ml.analyze"],
    ["Fire-day model", "ml/fire_day.py", "docs/research/fire-day-model-v1.md", "python -m ml.fire_day"],
    ["Sensor smoke model", "ml/smoke_sensor.py, app/sensor_model.py", "docs/research/sensor-smoke-model-v1.md", "python -m ml.smoke_sensor (Dryad files by hand)"],
    ["Spread back-test", "ml/backtest.py, app/sim/", "docs/research/spread-backtest-v1.md", "python -m ml.backtest"],
    ["Alert load, NGFS", "ml/alert_load.py, ml/ngfs_alert_load.py, ml/ngfs_lead_time.py", "backend/ml/*.md", "python -m ml.<name>"],
  ],
  [0.17, 0.27, 0.3, 0.26],
);
p("This report: docs/research/build-ml-report.js writes ml-models-report.txt and ml-models-report.docx from the same content.");

// ---------- text ----------

const WIDTH = 100;
const plain = (s) => s.replace(/\*\*/g, "");

function wrap(text, width, indent = "", first = indent) {
  const room = width - indent.length;
  const hard = (s) => s.match(new RegExp(`.{1,${room}}`, "g"));
  const split = (w) => {
    const chunks = [];
    for (const part of w.split(/(?<=[/-])/).flatMap((s) => (s.length <= room ? [s] : hard(s)))) {
      if (chunks.length && (chunks[chunks.length - 1] + part).length <= room) chunks[chunks.length - 1] += part;
      else chunks.push(part);
    }
    return chunks;
  };
  const words = text.split(/\s+/).filter(Boolean).flatMap((w) => (w.length <= room ? [w] : split(w)));
  const lines = [];
  let line = first, fresh = true;
  for (const w of words) {
    const cur = fresh ? line + w : line + " " + w;
    if (cur.length > width && !fresh) {
      lines.push(line);
      line = indent + w;
    } else line = cur;
    fresh = false;
  }
  if (!fresh) lines.push(line);
  return lines;
}

function textTable({ head, rows, widths }) {
  const usable = WIDTH - 3 * head.length - 1;
  const max = head.map((_, i) => Math.max(...[head, ...rows].map((r) => plain(r[i]).length)));
  let w = widths.map((f, i) => Math.min(max[i], Math.max(6, Math.floor(f * usable))));
  let spare = usable - w.reduce((a, b) => a + b, 0);
  while (spare > 0 && w.some((x, i) => x < max[i])) {
    for (let i = 0; i < w.length && spare > 0; i++) if (w[i] < max[i]) { w[i]++; spare--; }
  }
  const sep = "+" + w.map((x) => "-".repeat(x + 2)).join("+") + "+";
  const row = (cells) => {
    const wrapped = cells.map((c, i) => wrap(plain(c), w[i]));
    const n = Math.max(...wrapped.map((x) => x.length || 1));
    const out = [];
    for (let k = 0; k < n; k++) out.push("| " + wrapped.map((x, i) => (x[k] || "").padEnd(w[i])).join(" | ") + " |");
    return out;
  };
  return [sep, ...row(head), sep.replace(/-/g, "="), ...rows.flatMap((r) => [...row(r), sep])];
}

function toText() {
  const out = ["FIREWATCH MACHINE-LEARNING MODELS REPORT", DATE, "=".repeat(WIDTH), ""];
  B.forEach((b, i) => {
    if (b.h1) out.push("", b.h1.toUpperCase(), "=".repeat(b.h1.length), "");
    else if (b.h2) out.push(b.h2, "-".repeat(b.h2.length));
    else if (b.p) out.push(...wrap(plain(b.p), WIDTH), "");
    else if (b.bullets) {
      const pad = "  ".repeat(b.level || 0);
      for (const t of b.bullets) out.push(...wrap(plain(t), WIDTH, pad + "    ", pad + "  - "));
      const nested = B[i + 1] && B[i + 1].bullets && (B[i + 1].level || 0) > (b.level || 0);
      if (!nested) out.push("");
    } else if (b.numbers) {
      b.numbers.forEach((t, i) => out.push(...wrap(plain(t), WIDTH, "     ", `  ${i + 1}. `)));
      out.push("");
    } else if (b.table) out.push(...textTable(b.table), "");
    else if (b.fig) out.push(...wrap(`[Figure: ${b.fig.caption} See docs/research/figures/${b.fig.file}]`, WIDTH), "");
  });
  return out.join("\n").replace(/\n{3,}/g, "\n\n") + "\n";
}

// ---------- docx ----------

const CONTENT = 9360; // US Letter, 1" margins
const FONT = "Arial";

function runs(text, extra = {}) {
  return text.split(/(\*\*[^*]+\*\*)/).filter(Boolean).map((s) =>
    s.startsWith("**") ? new TextRun({ text: s.slice(2, -2), bold: true, ...extra }) : new TextRun({ text: s, ...extra }));
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };

function docTable({ head, rows, widths }) {
  const cols = widths.map((f) => Math.floor(f * CONTENT));
  cols[cols.length - 1] += CONTENT - cols.reduce((a, b) => a + b, 0);
  const cell = (text, i, header, keepNext) => new TableCell({
    borders, width: { size: cols[i], type: WidthType.DXA },
    shading: header ? { fill: "F2E3DC", type: ShadingType.CLEAR } : undefined,
    margins: { top: 60, bottom: 60, left: 100, right: 100 },
    children: [new Paragraph({ keepNext, children: runs(text, { size: 17, bold: header || undefined }) })],
  });
  return new Table({
    width: { size: CONTENT, type: WidthType.DXA }, columnWidths: cols,
    rows: [
      new TableRow({ tableHeader: true, cantSplit: true, children: head.map((t, i) => cell(t, i, true, true)) }),
      ...rows.map((r, k) => new TableRow({ cantSplit: true, children: r.map((t, i) => cell(t, i, false, k < rows.length - 1)) })),
    ],
  });
}

function pngSize(file) {
  const buf = fs.readFileSync(file);
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20), buf };
}

function toDocx() {
  const children = [
    new Paragraph({ spacing: { before: 600, after: 200 }, children: [new TextRun({ text: "Firewatch", size: 56, bold: true, color: "B5452B" })] }),
    new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Machine-learning models report", size: 40, bold: true })] }),
    new Paragraph({ spacing: { after: 600 }, children: [new TextRun({ text: `Satellite scorer · Fire-day model · Sensor smoke model · Spread forecast — ${DATE}`, size: 22, color: "555555" })] }),
  ];
  for (const b of B) {
    if (b.h1) children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, keepNext: true, children: [new TextRun(b.h1)] }));
    else if (b.h2) children.push(new Paragraph({ heading: HeadingLevel.HEADING_2, keepNext: true, children: [new TextRun(b.h2)] }));
    else if (b.p) children.push(new Paragraph({ spacing: { after: 140 }, children: runs(b.p) }));
    else if (b.bullets) b.bullets.forEach((t) => children.push(new Paragraph({ numbering: { reference: "bullets", level: b.level || 0 }, spacing: { after: 80 }, children: runs(t) })));
    else if (b.numbers) b.numbers.forEach((t) => children.push(new Paragraph({ numbering: { reference: "numbers", level: 0 }, spacing: { after: 80 }, children: runs(t) })));
    else if (b.table) children.push(docTable(b.table), new Paragraph({ spacing: { after: 120 }, children: [] }));
    else if (b.fig) {
      const { w, h, buf } = pngSize(path.join(FIG, b.fig.file));
      const width = 520, height = Math.round((520 * h) / w);
      children.push(
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 120 }, children: [new ImageRun({
          type: "png", data: buf, transformation: { width, height },
          altText: { title: b.fig.caption, description: b.fig.caption, name: path.basename(b.fig.file) } })] }),
        new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [new TextRun({ text: b.fig.caption, italics: true, size: 18, color: "555555" })] }),
      );
    }
  }
  return new Document({
    creator: "Firewatch", title: "Firewatch machine-learning models report",
    styles: {
      default: { document: { run: { font: FONT, size: 21 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 32, bold: true, font: FONT, color: "B5452B" }, paragraph: { spacing: { before: 360, after: 160 }, outlineLevel: 0 } },
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 25, bold: true, font: FONT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      ],
    },
    numbering: { config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 1440, hanging: 360 } } } },
      ] },
      { reference: "numbers", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 720, hanging: 360 } } } },
      ] },
    ] },
    sections: [{
      properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
      headers: { default: new Header({ children: [new Paragraph({ children: [new TextRun({ text: "Firewatch · ML models report", size: 16, color: "888888" })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({
        tabStops: [{ type: TabStopType.RIGHT, position: TabStopPosition.MAX }],
        children: [new TextRun({ text: DATE, size: 16, color: "888888" }), new TextRun({ children: ["\tPage ", PageNumber.CURRENT], size: 16, color: "888888" })],
      })] }) },
      children,
    }],
  });
}

fs.writeFileSync(path.join(OUT, "ml-models-report.txt"), toText());
Packer.toBuffer(toDocx()).then((buf) => {
  fs.writeFileSync(path.join(OUT, "ml-models-report.docx"), buf);
  console.log("wrote ml-models-report.txt and ml-models-report.docx");
});
