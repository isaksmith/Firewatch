# First-pass concept QA

**Result: SHIP WITH NOTES for visual and interaction review only.**

Inspected the rendered rich exploded, rich assembled, bare exploded and PCB
detail views. Revised the explosion so the battery and backplate lift clear of
the dry-box walls. Corrected the studio clipping and gave the assembled pose
its own animated camera framing. Bare previews remove the PM adapter, sensor,
chamber, and particulate label together. The PM flex belongs to the rich-only
collection and is also absent in Bare's installed pose.

Saved-scene checks pass in Blender 5.2.3 LTS:

- Millimetre scene units and the proposed 88 × 72 × 1.6 mm carrier envelope.
- Frame 1 / frame 100 transforms: carrier rises 170 mm, backplate 85 mm,
  battery 120 mm, and lid 230 mm.
- Bare view layer excludes the rich-only collection.
- All 111 primitive mesh objects have closed base topology and positive scale.
- 164 scene objects, 47 unique meshes, 4,916 base triangles before modifiers.
  Repeated primitives share mesh data; use Object → Relations → Make Single
  User → Object & Data before editing one repeated part's mesh independently.

The numerical contact review deliberately does **not** certify mechanical fit:

| Frame-1 interface | Signed gap | First-pass limitation |
| --- | ---: | --- |
| RAK4630 underside → carrier top | +0.80 mm | Simplified module stand-off; solder interface not modeled |
| Battery underside → backplate | +0.75 mm | Isolation/retention support detail not modeled |
| Carrier underside → standoff top | −0.30 mm | Placeholder overlap; hole and fastener design unresolved |

These interfaces need anchor-derived correction in the mechanical design pass,
using actual footprints, fasteners and battery data. Ports, connector bodies,
RF clearance, weather sealing and PCB traces are schematic representations.
There are no drilled PCB holes, validated feedthroughs, released pad patterns,
traces/netlist, or certified airflow/IP properties. The model has not undergone
six-side mechanical-fit review or physical printing. Tiny assembly text is
intended to be read by zooming or selecting the named object.

The four source skills and Blender-Superskill were reviewed. This project uses
millimetres, technical product shading, shared repeat meshes and presentation
cameras rather than their game-art defaults. Superskill's contact-plane guidance
informed the numeric review. No add-on or orchestrator was executed.

See `scene_audit.json` for measurements from the saved `.blend` and
`scripts/audit_scene.py` to rerun the structural checks. A successful scene audit
does not establish electrical correctness or manufacturability.
