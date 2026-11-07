# Revision 2 review

**Verdict: SHIP WITH NOTES for concept and interaction review.**

Reviewed rich exploded, front/rear band deployment, rich/bare stake deployment,
carrier detail and gas-head detail renders. Corrected the hinge passing through
the PV face, rear pivot-brace seating, upright pod upper caps, grade-disc
coplanarity and inspection-scene clutter. The default exploded scene keeps solar
and mounting alternatives excluded; deployment scenes show them explicitly.

Saved-scene validation checks all four tier/mount configurations, the visible
BATTERY PACK label, correct tier-specific panel envelopes, PM presence/absence,
two bands per band scene, stake-only parts in stake scenes, and −300 mm tip depth.
The audit evaluates each scene before measuring its world transforms.

Numerical anchors:

- Rear spacer-to-enclosure plane: 0 mm gap.
- Rear pivot brace-to-panel back: 0 mm gap for each tier.
- Hinge cylinder-to-panel back: 0.553 mm Rich / 1.203 mm Bare minimum at the
  displayed angle; this is not a swept tilt-range clearance check.
- Band inner radius: 64 mm; reference pole radius: 63.5 mm.
- Displayed enclosure center: 700 mm above grade; stake tip: 300 mm below grade.

No load rating, soil retention test, adjustable-band mechanism, exact vendor
mounting-hole pattern, solar yield, ingress rating or field sensing-height claim
is established by this model. Existing first-pass electrical/PCB limitations
remain. Added pads, leads, hole indications and grilles describe components
visually; they are not released footprint or fabrication geometry.

The original first-pass file is retained. Reproduction and scene controls are
documented in `REVISION2.md`; measurements are in `revision2_audit.json`.
