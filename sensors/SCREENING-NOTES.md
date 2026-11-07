# FireWatch sensor screening notes

## 30-second pitch

FireWatch helps rural fire districts decide where to watch for early signs of wildfire. We use local fire history and risk modeling to identify priority hotspots, then survey those sites for sensor placement and radio connectivity. Solar-powered bare nodes measure local changes in air chemistry and weather. Rich nodes also measure fine particles that may indicate smoke. The nodes can relay data over LoRa to an existing fire station, where FireWatch combines sensor readings with other evidence for the duty officer. The website, apps, and model are free to use. Districts pay for the site assessment, hardware, installation, and commissioning.

## What the hardware measures

| Part | What it does | What to say if asked |
| --- | --- | --- |
| Bosch environmental sensor, both tiers | Measures gas resistance, temperature, relative humidity, and pressure. The stocked prototype uses the **BME680** on the RAK1906. The custom-board concept uses the **BME688**. | Smoke gases can change the electrical resistance of a heated sensing surface inside the chip. Many reducing gases make resistance **drop**. Exhaust and humidity can also affect the reading. Temperature and humidity describe local drying conditions, and pressure adds general weather context. |
| Plantower PMSA003I, rich only | A fan pulls air through a laser beam. An optical detector measures the scattered light, and the sensor estimates particle size and concentration, including **PM2.5**. The RAK12039 adapter connects it to the controller and provides its 5 V supply. | A rise in fine particles above the local baseline is consistent with smoke. Dust, exhaust, and fog can also affect the reading. The rich node uses a larger panel and battery to support the added load. |
| Radio and controller, both tiers | The **RAK4631** prototype core and **RAK4630** custom-board module combine a Nordic nRF52840 microcontroller with a Semtech SX1262 LoRa transceiver. | The microcontroller runs the firmware. The LoRa radio carries short packets. WisBlock is RAK’s plug-in hardware system, and Meshtastic is the firmware and mesh networking system. |

Both tiers sample the air that reaches them. A small fire can release gases and particles before someone notices it. A node may pick up those changes early if the plume reaches its inlet while it is sampling. Wind, terrain, and the rich node’s sampling schedule all affect that opportunity. A quiet node means its latest sample showed no unusual signal at that location.

## One scenario from detection to response

1. **Detect.** A line faults on a dry, windy afternoon. A downwind rich node reports a fine-particle spike above its baseline. The proposed node firmware can raise a pre-warning for the station to investigate.
2. **Confirm.** FireWatch weighs the sensor data alongside the line fault, public reports, satellite fire detections from NASA FIRMS, and weather and Red Flag information from NOAA and the National Weather Service. The wind direction helps judge whether the line fault and particle spike could be related. A truck on a gravel road could also explain a spike. Multiple nodes sampling the same plume contribute to the sensor evidence category.
3. **Respond.** The duty officer sees why the event was flagged and can escalate through county dispatch. The goal is an earlier usable warning. The sensor design still needs a field trial to measure time gained relative to existing feeds and reports.

**What works today?** The backend ingests selected temperature, humidity, and particulate telemetry and can raise a particulate-based smoke signal. Gas-resistance ingestion, full sensor fusion, and custom-node pre-warning firmware are planned. The Blender model shows how the proposed custom assembly fits together. A routed PCB and field validation are still pending.

## Mesh, outages, and maintenance

- **Normal path.** Node → US915 Meshtastic LoRa mesh → station bridge radio → FireWatch backend. A field node can relay packets when configured and awake. A radio survey determines where dedicated elevated relays are needed. The planner budgets **$45 for the bridge radio** assuming an existing station computer and internet connection, plus **$105 per dedicated relay**.
- **Station internet outage.** The mesh can still carry local packets and the station radio can receive them. A remote backend and cloud notifications depend on the station’s backhaul. People on the district mesh can send reports using a compatible LoRa radio. A phone needs a radio connection to participate.
- **Stale readings.** If fresh heartbeats arrive but the sample timestamp or sequence stops advancing, investigate the sensor or sampling software. If everything stops, show **offline, cause unknown**. Check power, the radio path, and shared relays. The dashboard should show the last valid reading and its age, and the model should treat stale samples as missing evidence.

## Numbers worth memorizing

| Budget item | Estimate |
| --- | ---: |
| Bare / rich custom node, at about 100 units | **$136.44 / $203.60** |
| Bare / rich stocked prototype node | **$172.11 / $238.63** |
| Example 15-acre hotspot, seven bare and two rich at bulk pricing | **$1,362** in node hardware, about **$91 per acre of this example plot** |
| Same nine placements versus nine rich nodes | **$470 saved, or 26% lower node hardware cost** |
| One-off 15-acre pilot with stocked modules, a bridge, and zero or one relay | **$1,727–$1,832** in hardware |
| Ten selected county hotspots, 90 bulk-priced nodes, five relays, and one bridge | **$14,193** in hardware |

The bulk node prices include electronics, battery, solar panel, and enclosure. The deployment examples exclude survey and installation labor, mounts, shipping, and ongoing service. The 15-acre layout illustrates a planning cost. Actual coverage depends on the site, and bulk pricing depends on order quantities and supplier quotes.

## Judge questions and short answers

- **Why mix node types?** Keep environmental sampling at nine locations while putting the costlier particulate sensors at two selected positions. Both tiers have the same radio. The hardware savings are quantifiable. Detection performance depends on where smoke travels.
- **What does the county buy if the app is free?** A surveyed hotspot plan, hardware, installation, and commissioning. The deployment agreement assigns responsibility for alerts, repairs, battery replacement, and monitoring outages.
- **Are you cheaper than Dryad?** The cost case is a targeted deployment that shares radios and can reuse station backhaul. One U.S. Dryad quote listed **$195 for an out-of-warranty replacement sensor**. Our **$136 bare** and **$204 rich** figures are build estimates. An equivalent deployment comparison needs the same sites, detection goals, and service scope. [Dryad public quote](https://mediterracdd.net/_assets/documents/fy-2026/2025-11-19-MCDD-agenda.pdf)
- **How would you prove it works?** Work with the fire authority on supervised burns and observe nuisance events such as dust or exhaust. Compare FireWatch with and without node readings on the same events. Record warning lead time, missed fires, nuisance alerts, packet delivery, and outages.
- **What if a power line faults and the nearby rich node sees no PM increase?** Keep investigating. Check wind direction, sensor health, and whether the node was sampling when the plume could have passed. A fresh, flat reading tells you what the node sampled at that spot.

For deeper reference, see the [sensor README](README.md), [system overview](../README.md), and [controlled-burn sensor study](https://people.eecs.berkeley.edu/~prabal/pubs/papers/chwalek23downwind.pdf).
