# Revision 2 — details, solar and deployment mounts

Open `firewatch_revision2.blend`. The original `firewatch_first_pass.blend` is
retained. Everything is stored under `sensors/cad`; portable Blender and skill
references remain under the ignored `sensors/tools` directory.

## Scenes and controls

Use Blender's **Scene dropdown at the upper right** to choose:

| Scene | Contents |
| --- | --- |
| 01 — Layer inspection | Animated common carrier and internals; Rich/Bare view-layer switch |
| 02 — Rich band mount | Upright rich node, larger solar panel, two bands on a reference pole |
| 03 — Bare band mount | Upright bare node, smaller solar panel, same band interface |
| 04 — Rich ground stake | Upright rich node on the stake with larger panel |
| 05 — Bare ground stake | Upright bare node on the same stake with smaller panel |

In scene 01, use frame **1** for assembled or **100** for exploded. The existing
View Layer dropdown selects Rich/Bare. Solar and mount collections are excluded
from both inspection view layers by default to keep the internal layers readable;
they are present and visible in the deployment scenes. Enable their collection
checkboxes in the Outliner if you want them in the inspection scene as well.

Each deployment scene has separate collapsible collections for the core node,
solar hardware, common mount interface, mount option and studio/reference objects.
Use collection eyes to inspect parts. The reference pole is demonstration context,
not node hardware. Hide it to inspect the saddle. In the ground-stake scenes,
hide `Ground plane` and `Grade reference disc` to see the underground tip and fin.
The stake's embedded portion is intentionally hidden by the ground in its preview.

Deployment scenes are **static assembled snapshots**. Their mesh geometry is
shared with the inspection model, while object transforms and visibility are
independent. The exploded animation belongs to scene 01 only. The Rich band scene
also has a rear camera; select it and press Ctrl + Numpad 0 to inspect the bands.

## Changes

- Visible battery label is now **BATTERY PACK**. Actual pack-envelope uncertainty
  remains in object properties and design notes, not on the product label.
- Added gas-board passives, connector mouth and contacts, package base and pin-one
  detail, pad/hole indications, and additional silkscreen.
- Added PM case seams, grille ribs, case screws, flex-socket contacts and label
  detail; adapter passives, fixing details, power-inductor marking and pads.
- Added carrier connector contacts, power-IC lead indications and test vias.
- Added upper weather caps for the upright gas and particulate housings.
- Added tier-specific solar panels on a common rear-mounted adjustable bracket,
  with rear pivot brace, hinge axle/locks, junction box, lead and drip-loop concept.
- Added a common rear spine with spaced load spreaders; enclosure, panel and mount
  use that structure instead of fastening the solar panel directly to the lid.
- Added two adjustable wraparound bands with buckles/tails and cushioned saddles.
  The displayed loop fits a nominal 127 mm pole; resizing is manual, not rigged.
- Added a square-section stake, retaining collars, foot bar, depth collar,
  anti-rotation fin and pointed tip.

## Source dimensions and proposed geometry

The [P126 Bare panel](https://www.adafruit.com/product/5366) uses its vendor-listed
112 × 136 × 2.7 mm envelope. The [P105 Rich panel](https://www.adafruit.com/product/5367)
uses 137 × 222 × 4 mm. Cell patterns, mounting eyelets and bracket details are
illustrative. The displayed angle is a proposed 35° tilt from vertical (55° above
horizontal) in the upright deployment scenes, not a site-specific solar setting.

[RAK's RAK12039 documentation](https://docs.rakwireless.com/product-categories/wisblock/rak12039/datasheet/)
gives the 25 × 15 mm adapter and 38 × 35 × 12 mm PM sensor envelopes. The
[BME688 datasheet](https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme688-ds000.pdf)
gives the 3 × 3 × 0.93 mm package. Added terminals, grilles and pad patterns are
visual descriptions, not manufacturer CAD or a released PCB footprint.

The stake concept places the enclosure center 700 mm above grade with the point
300 mm below grade. These values describe this model, not validated installation
depth or sensing height. Stake dimensions, foot bar, fin, brackets, bands, cushions,
fasteners, cable paths and mounting holes are proposed geometry. This pass does
not establish wind/soil stability, tree fit, outdoor sealing, airflow or RF
clearance. Detailed PCB routing and accurate connector/battery models remain open.

## Rebuild and verify

From the repository root:

```powershell
& '.\sensors\tools\blender-5.2.3-windows-x64\blender.exe' --background --python '.\sensors\cad\scripts\build_revision2.py'
& '.\sensors\tools\blender-5.2.3-windows-x64\blender.exe' --background --python '.\sensors\cad\scripts\audit_revision2.py'
```

Rebuilding uses the retained first-pass file, replaces revision 2 and its renders,
and discards manual edits to revision 2. Save manual work under a different name.
`revision2_audit.json` records tier choices, panel envelopes, intended rear-mount
contacts, panel-brace seating, hinge clearance and stake depth.

Preview files in `renders/` are prefixed `v2_`: rich exploded, rich band, band rear,
rich stake, bare stake, carrier detail and gas-head detail.
