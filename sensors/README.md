# FireWatch sensor nodes

Prototype build guide for Kansas deployments

**Revision 0.1 · First design iteration · November 6, 2026 at 9:44 p.m. CST (America/Chicago)**

FireWatch uses two types of ground sensor on the same US915 Meshtastic network. The **bare node** reports local gas response, temperature, humidity, and pressure. The **rich node** measures the same signals and adds particulate sensing. Its firmware can issue a pre-warning and send the measurements behind it. The central FireWatch model assesses the event using those measurements alongside utility line events, NASA satellite detections, NOAA weather and wind, Red Flag information, and public reports.

The same radio, enclosure, and sensing architecture supports both builds. The rich node adds one distinct measurement rather than several experimental sensors. This is a module-based prototype design with a path to a custom PCB. Firmware integration, power autonomy, enclosure performance, and fire detection distance still require bench and field validation.

## Parts and budget

Quantities are **per node**, in USD. Linked prices are public single-unit listings checked for this design, before tax and shipping. The mechanical allowances cover consumables and fabricated pieces that are priced by the build. Confirm checkout prices and availability before ordering. Tools, assembly labor, shared relays, and the station bridge are separate.

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

### Cost at approximately 100 units

The custom assembly replaces **$88.81** in the existing BOM: the radio kit, environmental module and extension, charger, and boost converter. Plan for **$40–$55 per node** for the carrier, populated sensor head, antenna, and cable. About **$15** is the listed RAK4630 module price and **$7** is the listed BME688 price at 100 pieces. The remaining **$18–$33** is an allowance for power components, connectors, PCB fabrication, and assembly. The rich-node estimate assumes the cost of the retained particulate assembly stays the same. [RAK module pricing](https://store.rakwireless.com/products/rak4630-nrf52840-sx1262-lora-bluetooth-module-for-lorawan) · [DigiKey BME688 pricing](https://www.digikey.com/en/products/detail/bosch-sensortec/BME688/13681261) · [JLCPCB assembly fees](https://jlcpcb.com/help/article/pcb-assembly-price).

| Complete node | Stocked modules | Custom-board estimate | Parts savings |
|---|---:|---:|---:|
| Bare | $172.11 | **$123–$138** | **$34–$49** |
| Rich | $238.63 | **$190–$205** | **$34–$49** |

The custom figures retain the battery, solar panel, enclosure, mounting, and rich node’s PM module. They exclude design, board revisions, validation, and compliance work. At 90 nodes, the estimated hardware savings are approximately **$3,000–$4,400** before those expenses. At $40 savings per node, an illustrative $4,000 development cost breaks even at 100 units. Get assembly quotes from the actual BOM and placement files before using the savings in a county proposal.

### KiCad and Blender workflow

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
