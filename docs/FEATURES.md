# FireWatch features by product

| | Free | Paid |
|---|:---:|:---:|
| **FireWatchOS**: the system | ✓ | ✓ |
| **FireCast**: recommendations, fire forecasting, ML reasoning | ✓ | |
| **FireCast Plus**: FireCast with an LLM on top | | ✓ |
| **FireWatch Mobile**: the phone app | ✓ | ✓ |
| **FireNode**: FireSense sensors on the FireMesh network | | ✓ |

The console's top bar switches between three views: **Free**, **Paid**, and **Offline** (the paid tier with the station's internet down). The switch changes only what the console shows; the server runs everything either way.

Items marked *(planned)* or *(not field-tested)* are not finished. Everything else runs in the current build.

## FireWatchOS

The duty officer's console, and the server behind it.

1. **One screen for every early sign of fire.** 15 free public feeds come together on one map: NASA FIRMS satellite detections, NOAA NGFS and GOES, NWS alerts and Red Flag warnings, SPC outlooks, storm reports, METAR and RTMA weather, Landsat, and active-incident perimeters.
2. **Two independent sources before anyone is paged.** Satellites, utility line faults, public reports, neighbours' replies and sensors are grouped into one alert. An alert escalates only on a strong satellite score or two independent kinds of evidence. Several satellite passes count as one source.
3. **It knows what isn't a wildfire.** Refineries and other persistent heat sources, Flint Hills prescribed-burn season, and burns that people registered by text are all suppressed or downgraded, with the reason shown.
4. **Texting built in.** Alerts page the response ladder and warn people downwind. They ask nearby neighbours "do you see smoke?" and take replies such as `PAGE`, `NO` or `FIRE` by text. Every message is logged against the alert.
5. **Burn registration by text.** A rancher texts `BURN` and their burn is logged for the day, so their smoke doesn't page the district.
6. **Community board.** Residents post what they see. The dispatcher can attach a post to an alert, and posts can be pinned on the map.
7. **Works on a bad connection.** Low-data mode drops map tiles and slows updates. A lite page serves the most basic phones.
8. **Scenario replays.** Scripted incidents run through the real decision code on their own clock, compared with how long today's process takes. Used for training and demos.

## FireCast (free)

The engine that decides what an alert means and what to do about it. It runs on the station computer.

1. **ML fire score.** A model trained on Kansas FIRMS detections from 2016–2025, matched to reported wildfires and prescribed burns, scores each detection 0–100. It shows the factors behind the score, such as season, Flint Hills location, wind, humidity and distance to town.
2. **Expected-loss recommendation.** For each option (page now, ask a neighbour, wait), it weighs the chance it's a real fire, the acres burned before help arrives and the cost of a false alarm. It shows its working, step by step.
3. **Fire spread forecast.** An ensemble spread model draws where the fire could be over the next hour on the map, with a time slider. It gives worst-case ("up to", "soonest") arrival times for towns, roads and homes.
4. **3D spread preview.** The same forecast on terrain, with adjustable wind.
5. **Fire danger.** It computes the Grassland Fire Danger Index from live or local weather and grass curing.
6. **FireNode region planner.** For any district or Kansas county, it drafts where FireSense plots and FireMesh relays should go: plots on the riskiest ground and downwind of local fire-weather winds, relays sited by line of sight. It includes a solar check and a priced bill of materials.

## FireCast Plus (paid)

FireCast, plus an LLM.

1. **Answers to questions people text or radio in.** "Where's the fire? Is it coming our way?" gets a one-text answer drawn from the nearest open fires: their distance, spread direction, forecast size and worst-case arrival at the sender.
2. **Situation updates on the FireMesh channel.** These go out when crews are paged, when mutual aid is called and when the fire is stood down. They follow every 15 minutes, or sooner on a wind shift or the fire doubling.
3. **It can't invent facts.** An answer that uses a number not in the fire's facts is thrown out. On any failure a plain template goes out with the same facts, so the LLM changes only the wording, never whether a text is sent.
4. **Alerts never depend on it.** Pages and warnings stay fixed templates, because the reply parser relies on their exact words.
5. **Free or paid models via OpenRouter.** It defaults to OpenRouter's free model router. A paid model such as Claude Haiku costs about a tenth of a cent per answer.

*(planned)* An LLM explanation on the alert itself, reasoning over the ML score and expected-loss figures. Today the LLM works on texts and channel updates only.

## FireWatch Mobile (free)

The phone app for firefighters, chiefs and residents.

1. **Fire updates in a 40-character code.** FW1 codes arrive by text with one bar of signal and no data. The phone works out the rest offline: the nearest road, homes in the path, and worst-case arrival.
2. **Offline region packs.** Each county's map, roads, homes and stations is downloaded once at the station over Wi-Fi.
3. **Signed alerts.** Codes and packs carry Ed25519 signatures, so a forged alert is rejected.
4. **Meshtastic radio over Bluetooth.** The app receives alerts and sends reports with no cell service at all.
5. **Community board and offline posting** *(server-tested only)*. Posts queue offline, with a compass for marking where the smoke is.

## FireNode (paid): FireSense + FireMesh

### FireSense: the sensor network

1. **Two node tiers on one design.** Bare nodes measure gas resistance, temperature, humidity and pressure. Rich nodes add a PMSA003I particle sensor. A 15-acre plot of 7 bare and 2 rich nodes costs about $1,362 in hardware at bulk pricing.
2. **A smoke rule that knows dust from smoke.** A smoke signal needs PM2.5 well above that node's own baseline, a fine-particle mix that looks like smoke rather than wind-blown dust, and no matching rise at sensors far away, which would be regional smoke.
3. **Sensors are one source, used carefully.** All smoke nodes together count as one independent source: enough to investigate, and a second source on top of a satellite pass or a line fault.
4. **Health monitoring from telemetry alone.** It estimates battery capacity from overnight discharge, compares solar output with the rest of the network, and catches gas-sensor drift since install, a blocked PM inlet and fan wear. Each problem comes with what to do: clean, recalibrate or replace.
5. **Stale-sensor detection.** If the node's radio keeps reporting but the firmware's sample counter stops advancing, the sensor is flagged stale. Its old values are ignored, and it can't trigger a smoke alert.
6. **Solar-powered, no cell service needed.**

*(planned)* Local pre-warning firmware on rich nodes, gas-resistance smoke rules, and field validation of detection range.

### FireMesh: the network

1. **A LoRa mesh with no cell towers or internet.** It runs on US915 Meshtastic. Every FireSense node can relay its neighbours' packets, so fewer dedicated relays are needed.
2. **One station bridge, $45.** An existing station computer and radio connect the mesh to FireWatchOS. A dedicated relay is budgeted at $105.
3. **Alerts reach crews by radio.** Pages go out as acknowledged direct messages alongside SMS, and replies come back through the same parser as texts.
4. **Crew positions on the map.** Radios' GPS fixes put responders on the map, even where the roster has no address.
5. **Link health.** No heartbeat from a node shows "Radio link down, cause unknown". This is tracked separately from sensor health, so a dead link and a dead sensor are never confused.
6. **Keeps working when the station's internet is down.** FireSense readings, crew reports and the FireCast model on the station computer all still work. The **Offline** view shows exactly this.
