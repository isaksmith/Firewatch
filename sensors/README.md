# FireWatch sensor nodes

The interactive hardware viewer is in [`viewer/`](viewer/README.md), separate
from the main FireWatch application. Run `python sensors/viewer/serve.py` from
the repository root and open http://127.0.0.1:5174. Blender models, generation
scripts and deployment renders are in [`cad/`](cad/README.md); see
[`cad/REVISION2.md`](cad/REVISION2.md) for the latest design and mount variants.

Sensor architecture, prototype build guide, and custom-board inspection model for Kansas deployments

**Documentation revision 0.2 · November 7, 2026 · CAD revision 2**

FireWatch's proposed sensor network uses two types of ground node on the same US915 Meshtastic network. The **Bare node** is designed to measure gas resistance, temperature, humidity, and pressure. The **Rich node** adds optical particulate sensing. Local pre-warning firmware and holistic sensor-stream ML are planned capabilities, not validated features of the current custom-board design. The backend already accepts selected Meshtastic telemetry and can raise a particulate-based smoke signal for its event-confirmation workflow.

The same radio, enclosure, and sensing architecture supports both builds. The rich node adds one distinct measurement rather than several experimental sensors. This is a module-based prototype design with a path to a custom PCB. Firmware integration, power autonomy, enclosure performance, and fire detection distance still require bench and field validation.

## FireWatch sensor network pitch

[![FireWatch field sensor intro video](https://img.youtube.com/vi/OYTUxd2nSDk/hqdefault.jpg)](https://youtu.be/OYTUxd2nSDk)

**[Watch the 2-minute sensor intro on YouTube](https://youtu.be/OYTUxd2nSDk)**: every part in the exploded view, the node installed in a Kansas field, how it fits FireWatch, and what it costs. The video file is also in [`video/`](video/firewatch-sensor-intro.mp4).

Rural fire districts can have large areas to watch and few places with reliable cell service. FireWatch uses risk modeling to identify priority wildfire hotspots, then surveys those sites to decide where a small ground network can add useful observations. A county can start with one hotspot and expand to additional sites as the network demonstrates value.

**Detect → confirm → respond.** Bare nodes measure gas resistance, temperature, humidity, and pressure. Rich nodes add optical particulate measurements and are intended to generate a local pre-warning when readings warrant a closer look. FireWatch’s planned confirmation workflow combines those readings with independent evidence such as utility line-fault reports, public reports, satellite detections, and NOAA weather and Red Flag forecasts. The app gives the duty officer the evidence behind a warning and supports coordination with county dispatch. See the [FireWatch system overview](../README.md).

**The sensors also help carry the data.** Solar-powered field nodes use a shared US915 Meshtastic LoRa mesh. When configured to relay and awake, a sensor can forward nearby nodes’ packets as well as send its own. That can reduce the need for dedicated repeaters and lets field nodes communicate without cell service. A station bridge connects the mesh to FireWatch through an existing station computer and internet connection where available. The planner budgets **$45 for the bridge radio** and **$105 per dedicated relay**. A radio survey determines which sites need elevated relays or additional backhaul. [Meshtastic device roles](https://meshtastic.org/docs/configuration/radio/device/) · [FireWatch planner assumptions](../backend/app/planner.py)

### Cost per priority hotspot

The example puts seven Bare nodes and two Rich nodes on a 15-acre priority plot. Both tiers use the same radio, and the two Rich nodes add particulate sensing at selected positions. The low-end bulk estimates are **$136.44 per Bare node** and **$203.60 per Rich node**, including electronics, battery, solar panel, and enclosure. [Custom PCB parts and pricing](#preliminary-costed-bom-at-approximately-100-units)

| Example deployment | Estimated hardware cost |
| --- | ---: |
| One 15-acre hotspot, seven Bare and two Rich nodes at bulk pricing | **$1,362** in node hardware, about **$91 per acre of the example plot** |
| One-off pilot with stocked modules, a station bridge, and zero or one dedicated relay | **$1,727–$1,832** |
| Ten selected county hotspots, 70 Bare and 20 Rich nodes at bulk pricing, five relays, and one station bridge | **$14,193** |

The mixed layout saves **about $470 per hotspot, or 26% in node hardware**, compared with placing Rich nodes at all nine positions. These are planning estimates. Bulk prices assume a run of about 100 units and depend on part availability, order mix, and assembly quotes. The estimates exclude mounts, survey and installation labor, shipping, and ongoing service. The 15-acre layout illustrates the budget for one selected plot. Detection depends on where the plume travels, when the sensors sample, and whether the mesh can deliver the readings. The county example prices ten selected hotspots within a county.

### What the county pays for

The website, apps, and model are free to use. A county, fire district, or utility partner pays for the site assessment, placement plan, hardware, installation, and commissioning. The deployment quote also identifies who monitors outages, handles maintenance, and replaces failed hardware. A first project can use the stocked modules and document warning lead time, missed events, nuisance alerts, and packet delivery before the county commits to more sites. See [bring-up and site acceptance](#bring-up-and-site-acceptance).

FireWatch’s cost case comes from concentrating hardware on priority sites, sharing the radio network across both tiers, and reusing station infrastructure where possible. Comparing it with Dryad or another provider requires quotes for the same sites, detection objectives, and service scope. The custom board and the contribution of its readings to early warning still need field validation.

## Current designs and implementation status

Two hardware implementations are documented here. They share the two-tier idea but use different environmental sensors and power paths:

| Block | Module-based prototype | Custom-board concept shown in CAD/viewer |
|---|---|---|
| Radio/carrier | RAK4631 on RAK19007 | RAK4630 on a proposed FireWatch carrier |
| Environmental head, both tiers | RAK1906 with **BME680**, on an extension | Replaceable external **BME688** daughterboard |
| Rich-only particulate | RAK12039 adapter and PMSA003I | Retains RAK12039 and PMSA003I for the first custom spin |
| Power | Separate BQ24074 charger and 5 V boost, feeding WisBlock USB-C | Proposed BQ24074 power path and regulated 3.3 V buck-boost carrier rail |
| Current artifacts | Parts list and assembly instructions | Editable Blender assembly, renders, browser GLB and standalone viewer |

The CAD is a **mechanical/presentation concept**, generated with Blender Python. It is not an export of a routed PCB. There is no released KiCad schematic, board layout or manufacturing package in this folder. Exact footprints, connector selections, battery fit, RF clearance, seals, load ratings and outdoor performance remain open.

The current backend stores temperature, relative humidity, PM2.5 and PM10 with **gateway receipt time**. Gas resistance, pressure, sample timestamps, validity/sequence metadata and external pack-voltage telemetry still need ingestion support. Its smoke rule checks a PM2.5 rise over baseline, applies a fine-particle ratio check when PM10 is nonzero, and checks for regional rises when enough distant observations exist. It needs a known node position to raise a signal. All smoke nodes collectively count as **one independent evidence source**, so two nodes observing a plume do not alone satisfy the two-source escalation rule. See [`backend/app/sensors.py`](../backend/app/sensors.py), [`mesh.py`](../backend/app/mesh.py) and [`confirm.py`](../backend/app/confirm.py).

The trained scorer's evaluation uses historical satellite/context data, not collected FireWatch gas/particulate streams. See the [ML report](../backend/ml/report.md). A sensor pre-warning, a working mesh link and confirmed wildfire detection are separate things that require end-to-end testing.

## Standalone 3D Node Explorer

The hardware viewer runs independently of the main React dashboard and FastAPI backend. From the repository root:

```powershell
python sensors/viewer/serve.py
```

Open **http://127.0.0.1:5174**. Stop the server with Ctrl+C. To choose another port:

```powershell
python sensors/viewer/serve.py --port 5175
```

### Requirements

| Task | Requirements |
|---|---|
| Run the hardware viewer | Python 3 for the local server; a modern browser with WebGL |
| Python packages for the viewer | **None.** `serve.py` uses Python's standard library; no viewer `requirements.txt` or pip install is needed |
| JavaScript packages for the viewer | **No npm install or build step.** Three.js 0.181.1 and its MIT license are bundled locally |
| Edit/regenerate CAD or export GLB | Blender; the saved design and scripts were verified with **Blender 5.2.3 LTS** |
| Run optional viewer checks | Node.js, then `node sensors/viewer/verify.mjs`; no npm dependencies |
| Run the main FireWatch application | Separate setup: `backend/requirements.txt`, optional `backend/requirements-ml.txt`, and `frontend/package.json`; see the [root README](../README.md#getting-started) |

No account, API key, CDN connection or Blender installation is needed just to view the exported model. The server binds to this computer's loopback address. The optional [`viewer/start.ps1`](viewer/start.ps1) launcher can use a local portable Blender Python or a Python installation. Portable Blender and downloaded skill caches under `sensors/tools/` are **not committed**; a fresh clone can run the viewer with its own Python installation.

### Viewer controls and design files

- **Tier selector:** Bare/Rich; switches the particulate assembly and panel size.
- **Mount selector:** node only, adjustable tree/pole bands, or ground stake.
- **Explode slider:** compact separation with no added fan-out. Mounted configurations separate outward with the node's orientation; solar and mounting hardware remain anchored. Node-only keeps the original Blender separation offsets.
- **Layer controls:** independently show/hide enclosure, backplate, battery, PCB, environmental head, particulate assembly, solar, mounts and harnesses.
- **Component information:** click a part or list entry for Overview and **Specs & Limits**, including composition, technical ratings, design limitations and source links.
- **Focus on this component:** adjusts the camera; it does not isolate the component or change layer visibility.
- **Resizable information panel:** drag its left divider or use Expand/Collapse. The divider supports arrow keys and Home/End; double-click resets its width.
- **Camera controls:** orbit, zoom, Front/Rear/Top and Reset view.

| Artifact | Purpose |
|---|---|
| [`cad/firewatch_revision2.blend`](cad/firewatch_revision2.blend) | Current editable model; shared internals plus Rich/Bare band and stake deployment scenes |
| [`cad/firewatch_first_pass.blend`](cad/firewatch_first_pass.blend) | Retained original assembly and input to the revision-2 generator |
| [`cad/renders/`](cad/renders/) | Assembled/exploded views, mount variants and component close-ups |
| [`cad/scripts/`](cad/scripts/) | Scene generation, GLB export and validation scripts |
| [`viewer/assets/firewatch.glb`](viewer/assets/firewatch.glb) | Browser-ready geometry, named components and assembly metadata |
| [`cad/REVISION2.md`](cad/REVISION2.md) | Blender scene navigation, source dimensions and rebuild instructions |
| [`viewer/README.md`](viewer/README.md) | Standalone viewer setup, controls and verification |

In Blender's inspection scene, frame **1** is assembled and frame **100** is exploded. The Scene dropdown selects layer inspection or an upright Rich/Bare band/stake deployment scene. Deployment scenes are static snapshots; the exploded animation belongs to the inspection scene. Named collections can be collapsed and hidden in the Outliner. Blender and browser presentation poses differ for mounted views.

## Hardware specifications and dimensions

### Radio and processor

The proposed custom carrier uses a **RAK4630** module containing a **Nordic nRF52840 MCU** and a **Semtech SX1262 LoRa transceiver**, connected over SPI. The MCU handles processing and Bluetooth; the SX1262 handles the sub-GHz link.

| Specification | Value / design implication |
|---|---|
| CPU | 64 MHz Arm Cortex-M4 with floating-point unit |
| Internal flash | **1 MB total**, shared by firmware and persistent application data |
| RAM | **256 KB total**, volatile working memory |
| Local connectivity | 2.4 GHz Bluetooth LE; the RAK module documents BLE 5.0 |
| LoRa configuration | Intended **US915**, Meshtastic region **US**, operating within **902–928 MHz** |
| Radio output capability | Up to **+22 dBm**, approximately 160 mW; actual configured output depends on firmware, region and hardware |
| Module envelope | **15 × 23 × 3 mm** |
| External logging storage | Not specified in the current custom design |

Flash and RAM values are chip totals, not free application memory after firmware, bootloader and reserved areas. Select the correct regional module suffix and antenna; the SX1262 chip's wider tuning range does not mean one assembled module supports every band. Meshtastic mesh firmware is different from stock RAK LoRaWAN firmware, and custom-board compatibility still requires bring-up.

Manufacturer references: [RAK4630 datasheet](https://docs.rakwireless.com/product-categories/wisduo/rak4630-module/datasheet/), [Nordic nRF52840](https://www.nordicsemi.com/Products/nRF52840), [Semtech SX1262](https://www.semtech.com/products/wireless-rf/lora-connect/sx1262), and [Meshtastic radio settings](https://meshtastic.org/docs/configuration/radio/lora/).

**Communication range is not established for FireWatch.** Kilometer-scale LoRa links are possible, but antenna height, terrain, vegetation, interference and modem settings determine the installed result. Long-distance records are not a ground-node guarantee. Radio reach also does not establish the distance at which gas or smoke will reach an inlet. Survey radio links and measure plume encounters separately.

### Shared and tier-specific hardware

| Item | Bare | Rich |
|---|---|---|
| Custom environmental head | BME688: gas resistance, temperature, RH and pressure | Same |
| Particulate | Not fitted | PMSA003I via RAK12039; PM1.0 / PM2.5 / PM10 |
| Protected 1S battery | 3.7 V nominal, **4,400 mAh**, about **16.3 Wh** | 3.7 V nominal, **6,600 mAh**, about **24.4 Wh** |
| Solar panel | Voltaic **P126**, sold as nominal 6 V / 2 W | Voltaic **P105**, sold as nominal 5 V / 5 W |
| Panel envelope | **112 × 136 × 2.7 mm**; **4.41 × 5.35 × 0.11 in** | **137 × 222 × 4 mm**; **5.39 × 8.74 × 0.16 in** |
| Enclosure envelope, both tiers | **175 × 125 × 75 mm**; upright **6.89 in high × 4.92 in wide × 2.95 in deep** | Same |
| Proposed carrier, both tiers | **88 × 72 × 1.6 mm** | Same |

The enclosure dimensions are the nominal outer box, excluding side pods, bracket, panel and mount. The carrier outline is proposed, not a finalized PCB. The visible battery is labeled **BATTERY PACK** and uses a common placeholder envelope; the actual two pack sizes still need fit verification.

The **BME688 package is 3 × 3 × 0.93 mm**. Its heated gas element does not by itself identify a gas species or provide calibrated CO concentration. Keep the head in shaded outside air, away from the charger and battery. The prototype BOM below instead uses BME680 on the stocked RAK1906 module. [Bosch BME688 specifications](https://www.bosch-sensortec.com/en/products/environmental-sensors/gas-sensors/bme688)

The **PMSA003I body is 38 × 35 × 12 mm** and the **RAK12039 adapter is 25 × 15 mm**. The sensor uses a nominal 5 V supply and 3.3 V I²C signaling. Its effective PM2.5 range is 0–500 µg/m³, with 1 µg/m³ output resolution; operating temperature is −10 to +60 °C. Resolution is not a validated field detection threshold. Dust and fog can also raise readings. See the [RAK12039 datasheet](https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/) and [Plantower manual](https://cdn-shop.adafruit.com/product-files/4632/4505_PMSA003I_series_data_manual_English_V2.6.pdf).

The panel dimensions above follow the [P126](https://www.adafruit.com/product/5366) and [P105](https://www.adafruit.com/product/5367) vendor listings. Nominal panel watts and nominal pack Wh are not daily harvested energy or guaranteed runtime. The PM sensor alone can consume up to 12 Wh/day continuously; see the energy discussion below.

### External mount concepts

Both tiers use a shared rear spine and load spreaders, with the solar panel on a separate bracket rather than attached to the service lid.

- **Tree/pole option:** two adjustable-band concepts, buckle/tail details and cushioned saddles. The displayed example has a 128 mm (5.04 in) band inside diameter around a 127 mm reference pole. Adjustment is illustrative, not a rigged mechanism or validated diameter range.
- **Ground-stake option:** square-section shaft, retention collars, foot bar, depth collar, anti-rotation fin and pointed tip. The model places the enclosure center **700 mm (27.6 in) above grade** and the point **300 mm (11.8 in) below grade**. These are concept dimensions, not validated installation depth or sensor inlet height.

Mount load capacity, soil stability, tree/pole fit, corrosion, weather sealing and RF performance have not been established. Sampled browser-path checks distinguish existing CAD contacts from newly introduced intersections; they do not certify real-world fit or structural strength.

## Parts and budget

Quantities are **per node**, in USD. Prices below are the original prototype design's cost snapshot, not freshly verified checkout quotes. The mechanical allowances cover consumables and fabricated pieces that are priced by the build. Confirm prices and availability before ordering. Tools, assembly labor, shared relays, and the station bridge are separate. The stocked-module BOM is distinct from the custom-board concept shown in the viewer.

| Part | Exact module and vendor | Unit price | Bare | Rich |
|---|---|---:|---:|---:|
| Radio and base | [Rokland US915 WisBlock kit, SKU 116016](https://store.rokland.com/products/rak-wireless-wisblock-meshtastic-starter-kit), RAK4631 and RAK19007 with LoRa and BLE antennas and USB cable | $34.97 | 1 | 1 |
| Environmental module | [Rokland RAK1906, SKU 100008](https://store.rokland.com/collections/rakwireless-products), Bosch BME680 | $19.97 | 1 | 1 |
| Environmental module extension | [Rokland RAK19005, SKU 100025](https://store.rokland.com/collections/battery-solar-cable) | $10.97 | 1 | 1 |
| Particulate module | [Rokland RAK12039, SKU 110098](https://store.rokland.com/collections/sensors), PMSA003I and supplied flex cable | $37.97 | — | 1 |
| Solar charger with load sharing | [Adafruit 4755, BQ24074](https://www.adafruit.com/product/4755) | $14.95 | 1 | 1 |
| Battery temperature probe | [Adafruit 372, 10 kΩ NTC](https://www.adafruit.com/product/372) | $4.00 | 1 | 1 |
| 5 V converter | [Pololu 4941, U3V16F5](https://www.pololu.com/product/4941) | $7.95 | 1 | 1 |
| Bare battery | [Adafruit 354, protected 1S 3.7 V, 4,400 mAh](https://www.adafruit.com/product/354) | $19.95 | 1 | — |
| Rich battery | [Adafruit 353, protected 1S 3.7 V, 6,600 mAh](https://www.adafruit.com/product/353) | $24.50 | — | 1 |
| Bare solar panel | [Adafruit 5366, Voltaic P126, nominal 6 V / 2 W](https://www.adafruit.com/product/5366) | $20.95 | 1 | — |
| Rich solar panel | [Adafruit 5367, Voltaic P105, nominal 5 V / 5 W](https://www.adafruit.com/product/5367) | $34.95 | — | 1 |
| Panel-to-charger adapter | [Adafruit 4287, 3.5 × 1.1 mm to 5.5 × 2.1 mm](https://www.adafruit.com/product/4287) | $1.50 | 1 | 1 |
| Dry electronics enclosure | [Adafruit 905, gasketed 175 × 125 × 75 mm enclosure](https://www.adafruit.com/product/905) | $19.95 | 1 | 1 |
| Panel lead gland | [Adafruit 761, PG9, 4–6.4 mm cable OD](https://www.adafruit.com/product/761). Check the jacket diameter and assemble on the cable before terminating if necessary. | $1.95 | 1 | 1 |
| Wiring and mechanical allowance | One removable backplate, insulating standoffs and M4 enclosure screws, battery strap, USB-A female power pigtail, 33 µF / 16 V electrolytic, insulated wire, heat shrink, fuse and holder, outdoor mounting straps, and opaque weather hood with a protected flex feedthrough. Rich allowance includes a separate PM chamber and its mount. | $15 bare / $25 rich | 1 | 1 |
| **Total** | Listed modules and allowance | | **$172.11** | **$238.63** |

For an order estimate, round to **$175 per bare node and $240 per rich node**. The figures supersede the earlier rough estimates for this particular solar-powered, single-unit prototype. The extra cost comes from specifying separate power electronics, protected batteries, module extensions, and the housing. At the earlier seven-bare/two-rich mix, node hardware is about **$1,682** for one 15-acre planning plot, before a bridge. Seventy bare and twenty rich nodes total about **$16,820** before county relay infrastructure, shipping, spares, and labor. Those counts are illustrative layouts and depend on site assessment.

The RAK1906 uses a **BME680**. We selected it for its stocked plug-in form factor and shared telemetry support. The BME688 discussed earlier remains a candidate for a custom board if controlled trials justify its programmable gas-heater profiles. Either device needs its own calibration and validation. See [RAK1906 specifications](https://docs.rakwireless.com/product-categories/wisblock/rak1906/datasheet/) and the [Bosch BME688 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf).

## PCB and wiring layout

The RAK19007 is the carrier PCB for this build. Assembly requires module screws and a small soldered power harness. Build and test the harness on the bench before installing the battery and panels outdoors.

| Connection | Assembly |
|---|---|
| RAK4631 → RAK19007 | Seat and screw the RAK4631 into the **Core** connector. Connect the kit’s US915 LoRa and BLE antennas to their respective RF sockets before powering the radio. |
| RAK1906 → RAK19007 | Use sensor **slot A** and the RAK19005 extension. Mount the RAK1906 in the shaded sensor pod near the box. Keep the extension short and verify I²C enumeration after installation. |
| RAK12039 → RAK19007, rich only | Screw the RAK12039 adapter into the **IO** slot and connect the PMSA003I with the supplied flex. The adapter provides the sensor’s 5 V boost and uses 3.3 V I²C. Place the sensor body in the air chamber. |
| Panel → charger | Adapt the panel plug to the charger’s DC input and verify the adapter polarity with a meter. The RAK solar connector remains unused in this build. |
| Battery → charger | Plug the protected pack into **BATT** on the Adafruit charger after checking polarity. Use the charger’s **500 mA** setting for both prototypes, subject to the battery label. Configure **THERM** as documented by Adafruit and secure the 10 kΩ probe to the pack body without piercing or compressing the pack. Confirm charging stops at the battery supplier’s temperature limits. |
| Charger → boost → WisBlock | Route charger **LOAD OUT/GND** to regulator **VIN/GND** through the fused harness. Install the capacitor close to regulator VIN, observing polarity. Route **5 V OUT/GND** to the USB-A female power pigtail, then use the kit cable to feed RAK USB-C. Insulate all splices. For PC flashing, unplug the field power cable and use a single USB supply. The RAK battery connector remains unused. |

The external charger provides load sharing and a battery temperature input. The charger’s load output tops out at 4.4 V, so it feeds a 5 V boost rather than the RAK USB input directly. The rich panel has a nominal 5 V rating and less voltage headroom than the bare panel. Confirm net charging and recovery under realistic light, panel temperature, and load. Verify output voltage and peak current while the radio transmits and the PM fan starts. [RAK19007 carrier](https://docs.rakwireless.com/product-categories/wisblock/rak19007/) · [RAK12039 wiring](https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/) · [Charger pinout](https://learn.adafruit.com/adafruit-bq24074-universal-usb-dc-solar-charger-breakout/pinouts) · [Pololu regulator](https://www.pololu.com/product/4941).

## Enclosure layout

Use the same basic layout for both tiers. Model the enclosure and module outlines in Blender from the vendor drawings and confirm fit against physical parts before drilling. The rich pod must fit the **38 × 35 × 12 mm** particle sensor plus the flex bend, fasteners, and air passages.

| Location | Placement |
|---|---|
| Upper end of dry box | Fix the LoRa antenna vertically to the plastic wall with the kit adhesive. Keep it clear of the battery, metal backplate hardware, panel, cable loops, and pole. Place the BLE antenna on a different wall per the kit guidance. Verify RF performance in the assembled unit. |
| Center of dry box | Fix the WisBlock to an insulating removable backplate. Leave access to USB-C, reset, module screws, and connectors. Anchor flex cables so service loads cannot pull on their sockets. |
| Lower part of dry box | Strap the protected pack to the backplate and keep it away from the charger and boost converter. Fit a light-colored opaque sun shield over the clear lid. Place the solar cable entry on the bottom with a drip loop. |
| Shaded exterior pod | Put the BME680 in ventilated shade, isolated from battery and converter heat. Use a downward-facing hood with a drainage path. Leave the sensor opening exposed to air and keep coatings, adhesives, and sealant away from it. |
| Separate rich-node air chamber | Mount the PMSA003I by its mounting points. Give intake and exhaust separate, downward-protected openings so exhaust cannot recirculate. Keep openings at least as large as the sensor’s inlet and outlet. Use a removable coarse insect screen and check for restriction. A fine filter can remove the particles the device is intended to measure. |

Use a gasketed flat-flex feedthrough for the pod cables. A round cable gland around a flat flex does not form a reliable seal. Route the flex under the hood, observe its bend radius, and test the assembled feedthrough with the electronics removed before outdoor use. The enclosure vendor’s rating applies to its unmodified box. Keep the solar panel on a separate mounting bracket so sun exposure can be optimized without heating the sensor head. [Enclosure drawing](https://www.adafruit.com/product/905) · [Plantower installation requirements](https://cdn-shop.adafruit.com/product-files/4632/4505_PMSA003I_series_data_manual_English_V2.6.pdf).

## Power, sensing, and operating limits

| Topic | Design implication |
|---|---|
| **Bare-node gas response** | The BME680 reports gas resistance and local conditions. It can flag a change in the air reaching the pod. Its output cannot identify a gas species or give calibrated CO concentration. Humidity, exhaust, agricultural emissions, sensor aging, and recent power cycles can all affect the baseline. |
| **Rich-node particulate** | Plantower specifies approximately 0.3–10 µm particle sizes and an effective PM2.5 range of 0–500 µg/m³. The 1 µg/m³ reporting resolution does not establish a field detection threshold. Dust and fog can raise the reading. The sensor is rated −10 to 60 °C in operation and needs outdoor protection from rain, snow, and dust. |
| **Particulate warm-up** | The fan needs at least 30 seconds after wake before Plantower expects stable data. A proposed 45-second active window every 3 minutes gives a 25% duty cycle, with only the final 15 seconds available for valid samples. A short plume can pass during the gap. Confirm that firmware controls the sensor’s own sleep or a dedicated power switch without interrupting gas measurements. The first powered-site trial can run the fan continuously to establish a baseline. |
| **Energy budget** | The rich PM module can draw up to 0.5 W at its 5 V sensor rail, equivalent to 12 Wh/day continuously or 3 Wh/day at 25% duty before conversion loss. Add measured idle, radio, gas-heater, charger, and boost consumption. The bare pack stores about 16.3 Wh nominal and the rich pack about 24.4 Wh. Usable energy is lower. A 5 W panel with 2 equivalent sun-hours and an assumed 60% net yield gives 6 Wh/day. That scenario cannot support continuous worst-case PM draw. Measure charge recovery and several cloudy days before selecting a permanent panel or sample interval. |
| **Battery health telemetry** | Power enters through USB-C, so the WisBlock battery reading may be unavailable or meaningless. Report battery telemetry as unavailable until a dedicated measurement of the external pack is wired and calibrated. Never send an invented battery percentage. |
| **Sensor range** | Gas and particle ranges describe what reaches an inlet. The nodes do not have a proven fire-detection radius. Use Dryad’s 100 m high-activity spacing as a planning reference and establish FireWatch spacing with measured plume encounters in local grass and terrain. |
| **Coverage and cold weather** | A node may stay connected while the inlet is wet, blocked, or outside its temperature range. Record sensor health separately from radio health. Elevated relays can solve radio dead spots. Sample air at heights chosen for the expected plume rather than automatically placing sensors at relay-antenna height. |

References for [BME680 module limits](https://docs.rakwireless.com/product-categories/wisblock/rak1906/datasheet/), [PMSA003I limits](https://cdn-shop.adafruit.com/product-files/4632/4505_PMSA003I_series_data_manual_English_V2.6.pdf), [controlled-burn observations](https://people.eecs.berkeley.edu/~prabal/pubs/papers/chwalek23downwind.pdf), and [Dryad site planning](https://docs.dryad.app/dryad-documentation/site-planning/planning-guidelines/deployment-stages).

### Firmware and mesh

- Flash the RAK4631 Meshtastic build, select US915 and the district channel, and enable environment telemetry. Enable air quality telemetry on rich nodes and confirm the gateway receives both sensors’ data. Pin the tested firmware version in the build record.
- Use stock Meshtastic telemetry for initial bring-up. Its documented environment and air-quality intervals default to 30 minutes. The rich-node pre-warning and local sampling schedule are FireWatch firmware work. Measure samples locally, send periodic summaries, and send compact event packets promptly when a local rule finds a sustained anomaly. Send recent valid raw measurements or summaries with a timestamp and trigger reason so the backend can evaluate the evidence.
- Record node ID, surveyed location, inlet height, firmware version, sample time, sequence number, gas resistance, air temperature, RH, pressure, PM readings where fitted, sensor validity, and power status where measured. Separate sample time from gateway receipt time and detect gaps and stale readings. The model should treat a pre-warning and the measurements behind it as related evidence.
- Field nodes should prioritize sampling and power. Use separately powered repeaters where needed. One internet-connected station bridge feeds FireWatch. Check end-to-end latency and loss with all deployed nodes and simultaneous alerts, then choose telemetry intervals that fit mesh capacity. [Meshtastic telemetry](https://meshtastic.org/docs/configuration/module/telemetry/) · [Meshtastic MQTT](https://meshtastic.org/docs/configuration/module/mqtt/).

## Tradeoffs

**Bare node.** One small environmental module, no fan, lower energy demand, and common spares. It can collect many local observations for a district. Gas resistance has several plausible causes and a cheap node can miss a plume entirely.

**Rich node.** A particle spike adds evidence distinct from gas resistance and can help explain a pre-warning. The fan, boost circuitry, air chamber, and larger power system add maintenance and cost. A thermal array or soil probe belongs in a separate experiment. A thermal array needs a defined view of a target. Soil moisture describes site conditions and has little value as an immediate fire trigger.

## Custom-board build

Use a common **FireWatch carrier PCB** and a small replaceable **BME688 sensor board** in the shaded pod. The bare variant uses those two boards. The rich variant adds the stocked RAK12039 adapter and PMSA003I sensor. Keeping the adapter and supplied flex for the first spin avoids having to redesign the fan supply and sensor connector while also bringing up the new carrier. The module-based BOM above remains the baseline for the first field units. This section defines a design for CAD and costing. It does not contain a released schematic or fabrication files.

| Block | First custom build |
|---|---|
| Radio | Use a **US915 RAK4630** module and the manufacturer’s reference circuit. Pick the exact module suffix and approved antenna before assigning the footprint. Place the module near the carrier edge, keep the documented RF clearances, and provide SWDIO, SWCLK, reset, ground, and target-voltage test pads. Start firmware bring-up over SWD and verify the board pin mapping and bootloader. The shared radio chipset does not guarantee stock WisBlock firmware will run unchanged. |
| Solar and battery | Design around the **TI BQ24074** power-path charger and the same protected 1S packs. Follow the manufacturer’s reference schematic for input protection, thermal copper, charge-current setting, and battery-temperature sensing. Feed the carrier from the charger system output through a regulated **3.3 V buck-boost rail** sized for radio transmission and rich-module startup. Add a low-battery cutoff strategy and a calibrated divider for pack voltage. Verify charge inhibit with the selected pack and thermistor curve. |
| Gas head | Use a **Bosch BME688** on a small 3.3 V I²C daughterboard with local decoupling and the vendor-recommended address strap. Use a keyed cable carrying 3.3 V, ground, SDA, and SCL. Keep it short, review the combined bus pull-ups, and verify signal levels at the longest intended cable length. Place the head at the air boundary away from converter heat. |
| Rich PM interface | Provide the **RAK12039-compatible IO footprint** using RAK’s pinout and mechanical drawing. Route 3.3 V logic, ground, I²C, and the adapter’s documented supply and control pins. Confirm the carrier rail and load switch can handle startup. The adapter already boosts the PMSA003I supply to 5 V. Keep its switched power independent of the gas head and verify sleep and wake behavior. Leave the PM connector and switch parts unpopulated on the bare build where practical. |
| Service and test | Give the panel, battery, gas head, and PM adapter keyed or clearly marked connectors. Label rail and bus test points. Put the converter and charger together near the power inputs and away from the antenna and sensing head. Keep the pack removable and the debug pads accessible with the lid off. |

Use the RAK schematic and footprint data to map pin numbers before routing. Confirm the exact BME688 settings and telemetry fields against the deployed firmware. [RAK4630 documentation](https://docs.rakwireless.com/product-categories/wisduo/rak4630-module/overview/) · [TI BQ24074](https://www.ti.com/product/BQ24074) · [RAK12039 adapter](https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/) · [Bosch BME688](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf).

### Preliminary costed BOM at approximately 100 units

Price check: November 7, 2026. Costs are USD per node and use the low end of the planning allowances for a run of approximately 100 nodes. Use published 100-piece prices where available. Quantity breaks apply to each SKU, so a mixed bare/rich batch may pay more for tier-specific parts. The carrier and gas head still need a routed design, and fabrication, assembly, and programming are budgeting allowances.

| Custom electronics item | Candidate part or scope | Quantity per bare / rich | Cost per bare node | Cost per rich node |
|---|---|---:|---:|---:|
| US915 radio and MCU | [DigiKey RAK4630-9-SM-I](https://www.digikey.com/en/products/detail/rakwireless-technology-limited/RAK4630-9-SM-I/17138014), US915 MHF variant, quantity-100 price | 1 / 1 | $25.99 | $25.99 |
| Gas and environment IC | [Bosch BME688](https://www.digikey.com/en/products/detail/bosch-sensortec/BME688/13681261), mounted on the replaceable gas head. Quantity-100 Digi-Reel price includes the prorated reeling fee. | 1 / 1 | $7.70 | $7.70 |
| Solar charger IC | [TI BQ24074RGTR](https://www.lcsc.com/product-detail/C54313.html), 1S charger with power path | 1 / 1 | $1.78 | $1.78 |
| 3.3 V converter IC | [TI TPS63031DSKR](https://www.digikey.com/en/products/detail/texas-instruments/TPS63031DSKR/2048021), candidate pending rich-node startup and low-battery load verification | 1 / 1 | $1.46 | $1.46 |
| LoRa antenna | [RAK MHF-1 PCB antenna, 902–928 MHz option](https://store.rakwireless.com/products/pcb-antenna-for-lora-mhf-1) | 1 / 1 | $3.00 | $3.00 |
| BLE antenna | [RAK MHF-1 PCB antenna, SKU 920091](https://store.rakwireless.com/products/2-4ghz-wifi-ble-pcb-antenna-mhf-1) | 1 / 1 | $3.00 | $3.00 |
| Gas-head board sockets | [JST SM04B-SRSS-TB](https://www.digikey.com/en/products/detail/jst-sales-america-inc/SM04B-SRSS-TB/926710), one at each end | 2 / 2 | $0.74 | $0.74 |
| Gas-head cable | [Adafruit 4210, 100 mm JST-SH cable](https://www.adafruit.com/product/4210), listed at $0.76 at 100 but out of stock at price check. Budget uses the $0.95 retail price as an allowance. Verify fit and pin order. | 1 / 1 | $0.95 | $0.95 |
| Converter passives | Inductor and input/output capacitors, allowance | 1 set / 1 set | $1.00 | $1.00 |
| Charger, sensing and protection passives | Charger set resistors, decoupling, pack voltage divider, I²C pull-ups, and input protection, allowance | 1 set / 1 set | $1.00 | $1.00 |
| Other board connectors | Panel input, battery, and thermistor connectors, allowance. SWD uses test pads. | 1 set / 1 set | $1.00 | $1.00 |
| PM load switch | [TI TPS22918DBVR](https://www.digikey.com/en/products/detail/texas-instruments/TPS22918DBVR/5994601), candidate with controlled turn-on. Listing showed backorder at the price check. | 0 / 1 | — | $0.30 |
| PM adapter socket | [RAK FBB04004-F40S1003K6M](https://store.rakwireless.com/products/wisconnector), 40-pin female. Allowance pending confirmation of the 40-pin variant price. | 0 / 1 | — | $0.75 |
| PM switch support | Ramp and decoupling parts plus adapter fasteners, allowance | 0 / 1 set | — | $0.50 |
| PCB fabrication | Carrier and gas-head boards, allowance | 2 / 2 | $4.00 | $4.00 |
| SMT assembly | Placement on both boards, including allocated stencil, setup and feeder fees, allowance | 1 set / 1 set | $5.00 | $5.00 |
| Board programming and functional check | Flash and bench-check the rails, radio and sensor interfaces, allowance | 1 / 1 | $2.00 | $2.00 |
| **Custom PCB assembly subtotal** | Includes both boards, antennas, programming, and bench checks. Rich includes the PM socket and switch. | | **$58.62** | **$60.17** |

DigiKey is the radio source for this budget. Verify the 3.3 V converter under low-battery conditions with the rich node’s PM adapter boosting to 5 V while the radio transmits. The charger, switch, and connectors remain candidate parts until schematic review. [TI converter specifications](https://www.ti.com/product/TPS63031) · [RAK12039 supply and pinout](https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/) · [JLCPCB assembly fee schedule](https://jlcpcb.com/help/article/pcb-assembly-price).

The table below covers the remaining electronics and enclosure for [CAD Revision 2](cad/REVISION2.md). The RAK12039 includes the PMSA003I and its flex cable. The protected 4,400 mAh bare pack measures 69 × 37 × 18 mm and the protected 6,600 mAh rich pack measures 69 × 54 × 18 mm. Both are priced as specified. Update the shared 68 × 45 × 20 mm CAD placeholder to check the two pack envelopes, retention, and lead clearance.

| Electronics and enclosure item | Part | Bare | Rich |
|---|---|---:|---:|
| Battery temperature probe | [Adafruit 372](https://www.adafruit.com/product/372), quantity 100+ | $3.20 | $3.20 |
| Protected battery | [Adafruit 354](https://www.adafruit.com/product/354), 4,400 mAh / [Adafruit 353](https://www.adafruit.com/product/353), 6,600 mAh, quantity 100+ per SKU | $15.96 | $19.60 |
| Solar panel | [Adafruit 5366](https://www.adafruit.com/product/5366), 2 W / [Adafruit 5367](https://www.adafruit.com/product/5367), 5 W, listed unit prices | $20.95 | $34.95 |
| Panel adapter | [Adafruit 4287](https://www.adafruit.com/product/4287), quantity 100+ | $1.20 | $1.20 |
| Electronics box | [Adafruit 905 via DigiKey](https://www.digikey.com/en/products/detail/adafruit-industries-llc/905/10669794), 175 × 125 × 75 mm, listed unit price | $19.95 | $19.95 |
| Cable gland | [Adafruit 761](https://www.adafruit.com/product/761), quantity 100+ | $1.56 | $1.56 |
| Internal wiring and enclosure parts | Allowance for wiring, backplate, standoffs, pack restraint, sensor hood and seals. Rich also includes the PM chamber. | $15.00 | $25.00 |
| Particulate assembly | [Rokland RAK12039, SKU 110098](https://store.rokland.com/collections/rakwireless-products/products/particle-matter-sensor-plantower-pmsa003i-rak12039) | — | $37.97 |
| **Remaining electronics and enclosure subtotal** | | **$77.82** | **$143.43** |

| Per-node budget at approximately 100 units | Bare | Rich |
|---|---:|---:|
| Custom PCB assembly | $58.62 | $60.17 |
| Remaining electronics and enclosure | $77.82 | $143.43 |
| **Total** | **$136.44** | **$203.60** |

These are low-end planning budgets. The DigiKey BME688 and enclosure listings and the Rokland RAK12039 listing showed fewer than 100 on hand at review. The $19.95 enclosure budget uses DigiKey’s listed price. Adafruit’s lower $15.96 bulk tier depends on restock. Totals cover the node electronics, solar panel, and enclosure, excluding deployment mounts, shipping, taxes, duty, final enclosure assembly labor, engineering, and validation. Confirm part availability and get a fabrication and assembly quote using the routed files before ordering.

### Planned KiCad-to-Blender engineering workflow

The existing Blender revision is generated from proposed geometry; it was not imported from KiCad. The steps below describe the next engineering workflow once the schematic and routed board exist.

1. **KiCad schematic.** Capture the carrier and sensor-head circuits and assign exact footprints from vendor drawings. Check the module pin map, I²C pull-ups, power sequencing, antenna requirements, and test pads against the reference designs. Run the electrical rules check before laying out the boards.
2. **KiCad board layout.** Agree on the enclosure’s usable interior, standoff pattern, and connector exits before fixing the carrier outline. Route power and RF to the reference layout, run the board design rules check, and inspect the 3D view. Maintain separate bare and rich assembly BOMs for the same carrier.
3. **Blender fit model.** Export the board from KiCad as GLB and import it into Blender. Verify the imported dimensions against the KiCad outline. Model the backplate, lid clearance, battery strap, cable bends, air-pod opening, flex feedthrough, and antenna clearance. Include keepout bodies where a component has no vendor 3D model. Export STL for the printed fit-check pieces. Use the dimensioned board and enclosure drawings when checking the physical print. [KiCad GLB export](https://docs.kicad.org/10.0/en/cli/cli.html) · [Blender STL documentation](https://docs.blender.org/manual/en/5.0/files/import_export/stl.html).
4. **Release gate.** Review the schematic, layout, and mechanical fit before ordering a small board spin. Verify the rails, charging, gas head, PM startup, and RF delivery on assembled units before scaling. An electrical rules check or an enclosure render cannot establish field readiness.

## Bring-up and site acceptance

1. **Bench assembly.** Inspect polarity and flex orientation. Confirm 5 V under load and check that no connector or regulator overheats. Bring up the radio with its antenna attached, then enumerate each sensor. Cycle battery and panel inputs and confirm the firmware recovers cleanly.
2. **Weather and power trial.** Check charge inhibit at the battery limits, wake-to-valid PM timing, discharge overnight, and recovery after shade or a low battery. Test the empty enclosure for spray ingress. Compare shaded temperatures with an independent reference and inspect the particle inlet after exposure to dust.
3. **Radio survey.** Place temporary nodes at the actual candidate heights and verify delivery to the bridge, with and without relays. Measure packet loss and end-to-end event delay. Log the serial number, surveyed location, baseline readings, radio settings, and maintenance owner for each installation.
4. **Detection trial.** Work with the local fire authority on supervised grass-fuel burns. Compare bare and rich readings at downwind and crosswind locations, at several distances and inlet heights. Include nuisance observations such as dust, exhaust, and humid mornings. Compare the central model using free feeds alone against the same timeline with sensor data. Report missed events, false alerts per node-day, and time to pre-warning and central assessment.
5. **Service.** Make the air pod, battery, and backplate replaceable from ground level where practical. Flag stale and invalid data in the app. Use the first field season to set inspection and replacement intervals for the PM inlet, fan, seals, and battery.

The free FireWatch website, apps, and model use the resulting data. The paid county work is the site assessment, placement design, deployment, and commissioning. Quote that work separately from node hardware and use the verified field results to decide where each tier is worth installing.

The FireWatch region planner (`/planner` in the app, [DESIGN.md section 5.9](../docs/DESIGN.md#59-region-planner)) drafts the desk part of that placement design for any district or Kansas county. It places plots of this mixed layout, lays out each plot's nodes downwind of the local fire-weather winds, and routes relays to the station bridge. It also checks the solar budget against local sun and prices the result. The radio survey and detection trial above then confirm or move each site.
