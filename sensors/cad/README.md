# FireWatch — first-pass inspection model

**Latest revision:** see [REVISION2.md](REVISION2.md) and open
`firewatch_revision2.blend` for added component detail, solar panels and both
external mount options. The instructions below describe the retained first pass.

Open **`firewatch_first_pass.blend`** with the portable Blender at
`../tools/blender-5.2.3-windows-x64/blender.exe`.

This is a clean technical concept of the **custom carrier PCB and enclosure**.
The file opens exploded, with editable components and non-destructive bevels.
It is not a routed PCB, print-ready enclosure, or validated weatherproof assembly.

## Inspect the model

1. **Assembled / exploded:** In the bottom Timeline, enter frame **1** for the
   installed pose or **100** for the exploded pose. Scrub between them or press
   Space with the pointer over the Timeline to play. Markers identify both poses.
2. **Collapse groups:** In the Outliner at upper right, use each collection's
   disclosure arrow to collapse or expand its parts. This changes the tree only.
3. **Hide layers:** Click the eye beside a collection to hide it in the viewport.
   Hide `01 | ENCLOSURE` to reveal the interior. The camera icon controls renders
   separately. Expand a collection to hide an individual layer Empty and its
   children, or individual components.
4. **Choose tier:** Use the View Layer dropdown at the top right: `RICH | complete
   assembly` or `BARE | no particulate assembly`. Bare excludes the entire
   rich-only collection. In the Rich view you can also toggle collection `06`.
   Bare is an inspection view layer, disabled for batch rendering by default;
   use the provided bare preview or enable that layer for rendering explicitly.
5. **Read parts:** Select a component in the Outliner and open Object Properties
   → Custom Properties. Important parts record their role and dimensional status.
6. **Orbit and zoom:** Middle mouse orbits, Shift + middle mouse pans, and the
   scroll wheel zooms. Numpad 0 enters/leaves the assembly camera. Select a part
   and press Numpad decimal to frame it. Home frames visible objects; hide the
   studio collection first to avoid framing the very large studio floor.
7. **PCB close-up:** At frame 1, hide enclosure, backplate, power, gas and harness
   collections. Select `PCB inspection camera` and press Ctrl + Numpad 0 to make
   it active. To restore, select `Inspection camera` and Ctrl + Numpad 0.

No add-on, script execution permission, or internet connection is needed to view
the saved geometry, collection controls or animation.

## What the tiers share

Both use the proposed 88 × 72 mm carrier, RAK4630 radio, charger/regulator blocks,
battery connection and external BME688 daughterboard. **BME688 stays outside the
dry box** in its ventilated shaded head. It represents gas resistance, temperature,
relative humidity and pressure; there are not four separate sensor packages.

Rich adds the RAK12039 adapter and PMSA003I particulate sensor/chamber. Its
adapter is a retained module on the proposed custom carrier, not a completed
custom PM circuit. The adapter lifts separately in the exploded pose.

The battery is a **common provisional envelope** marked `PACK SIZE TBD`.
The design guide calls for 4,400 mAh bare and 6,600 mAh rich; actual pack fit is
not established here. Solar panel and deployment bracket geometry are deferred.
The box envelope is 125 mm X × 175 mm Y × 75 mm Z. Proposed interiors, mounts,
connectors and ports need physical drawings and design review before fabrication.

## Files

- `firewatch_first_pass.blend` — editable assembly, two tier view layers,
  exploded animation, cameras, materials and optional symbolic clearance guides.
- `renders/rich_exploded.png` — all inspection layers.
- `renders/rich_assembled.png` — closed rich node.
- `renders/bare_exploded.png` — common hardware without PM assembly.
- `renders/custom_pcb_detail.png` — carrier and optional PM adapter detail.
- `scripts/build_firewatch.py` — reproducible scene generator.
- `DESIGN_NOTES.md` — source dimensions, assumptions and reference repositories.
- `QA.md` / `scene_audit.json` — visual notes and saved-scene checks.

## Rebuild

From the repository root in PowerShell:

```powershell
& '.\sensors\tools\blender-5.2.3-windows-x64\blender.exe' --background --python '.\sensors\cad\scripts\build_firewatch.py'
```

This replaces the generated `.blend` and preview renders. Preserve manual edits
in a separately named file before rebuilding. Blender may create `.blend1`
backups; they are ignored in Git. Labels, harnesses and clearance guides are
presentation/reference geometry rather than fabrication geometry. Harnesses
disappear as explosion starts because their lengths represent the installed pose.

## Skill references

A focused MIT-licensed subset from https://github.com/arjun988/blender-skills
is cached under `../tools/blender-skills/`: modeler, hard-surface, scene-assembly
and QA. See its `README-FIREWATCH.md` for review findings and upstream provenance.
It is a project-local reference cache; it is not globally registered with Codex.
No third-party CAD meshes have been incorporated into this first-pass model.

The second reviewed reference, https://github.com/powerhouse90/Blender-Superskill,
is cached as text under `../tools/blender-superskill/`, with its MIT license,
provenance and applicability notes. Its numerical contact review is reflected
in `QA.md`; its optional orchestration scripts were not installed or run.

## Next pass

Review the visual hierarchy and inspection controls first. Then settle actual
battery/connector models, carrier outline, gasket and screw design, pod inlet
geometry, feedthroughs, solar mounting and RF/service clearances. Export a browser
format after the assembly hierarchy and interaction are approved.
