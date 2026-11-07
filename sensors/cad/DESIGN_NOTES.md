# FireWatch inspection model — first pass

Status: first-pass custom PCB concept; clean technical style, Blender exploded
inspection first, future browser viewer deferred by user preference. Both rich
and bare tiers share the assembly; rich-only parts form a separate collection.

All generated assets and source scripts belong under `sensors/cad/`.
Portable Blender lives under `sensors/tools/` and is excluded from Git.

## Baseline

The custom-board section of `sensors/README.md` is the electrical architecture
reference. This model is a mechanical and presentation concept, not an exported
KiCad layout or fabrication release. No routed PCB currently exists.

- Custom carrier: RAK4630 radio, BQ24074 power-path charger, 3.3 V buck-boost,
  battery monitoring, service/debug pads, keyed connectors.
- Environmental measurement: BME688 daughterboard in a separate shaded pod.
  Do not imply that an enclosed carrier-mounted gas sensor samples outside air.
- Rich option: RAK12039 adapter and PMSA003I in a separate ventilated chamber.
- Common outer dry-box envelope: 175 × 125 × 75 mm, from the repository BOM.
- Carrier outline, wall and gasket geometry, battery envelope, mounting holes,
  wiring paths and pod geometry are proposed design dimensions.

## Verified component envelopes

| Item | Envelope | Source |
| --- | --- | --- |
| RAK4630 | 15 × 23 × 3 mm | https://www.rakwireless.com/en-us/products/modules-for-lorawan |
| BME688 package | 3 × 3 × 0.93 mm | https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf |
| PMSA003I | 38 × 35 × 12 mm | `sensors/README.md`; vendor drawing required before physical fit release |
| RAK12039 adapter | 25 × 15 mm | https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/ |

## Inspection principles

- Use named Blender Collections that can be collapsed and hidden in the Outliner.
- Parent each mechanical layer to its own Empty; preserve installed transforms.
- Provide assembled and exploded timeline markers and smooth keyed transitions.
- Keep the bare/rich particulate option in one independently hideable collection.
- Name components with both part number and function; attach descriptive custom
  properties so selecting a part exposes its role and dimensional confidence.
- Separate labels and presentation helpers from physical geometry.
- Describe explosion as an inspection pose; wire geometry need not represent
  deployable harness lengths in that pose.
- Keep air passages, battery removal, RF clearance and service access visible
  as optional guides rather than implying that a render validates them.

## Open-source references

Reference research identified https://github.com/meshtastic/enclosures
(CC BY 4.0), https://github.com/adafruit/Adafruit_CAD_Parts (MIT),
https://github.com/radhoo/uradmonitor_smoggie (GPL-3.0), and
https://github.com/roepkefeller/air-quality-sensor (CERN-OHL-S-2.0 hardware).
No source geometry from these repositories has been downloaded or incorporated
at this preparation stage. Retain per-asset license and attribution if reused.
