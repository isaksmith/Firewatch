# FireWatch Node Explorer

Standalone local app. The main FireWatch frontend and backend are not required.
All runtime assets, including the pinned Three.js 0.181.1 modules and MIT license,
are local. No package installation, account, remote API or build step is required.

From the repository root, with Python 3 installed:

```powershell
python sensors/viewer/serve.py
```

Or use the PowerShell launcher (which can use the local portable Blender Python):

```powershell
& '.\sensors\viewer\start.ps1'
```

On the original development computer, from any PowerShell directory:

```powershell
& 'C:\Users\prest\Firewatch\sensors\viewer\start.ps1'
```

Open http://127.0.0.1:5174. The server binds to loopback only. Stop with Ctrl+C.
Use `-Port 5175` to run another local instance. If script policy prevents the
launcher, run the bundled Python directly without changing system policy:

```powershell
& 'C:\Users\prest\Firewatch\sensors\tools\blender-5.2.3-windows-x64\5.2\python\bin\python.exe' 'C:\Users\prest\Firewatch\sensors\viewer\serve.py'
```

## Interaction

- Select Rich/Bare and the deployment mount; the matching panel and PM hardware
  follow the selection.
- Drag the explode slider, toggle layers, orbit, zoom or reset the view.
  Separation uses the original compact Blender offsets without lateral fan-out.
  The node-only pose is unchanged. Mounted configurations rotate the separation
  paths with the node, so layers exit outward through the lid opening instead of
  being redirected into world-up movement. Each board/head stays
  together; the solar bracket and mounting structure remain anchored in mounted
  configurations to avoid sweeping the bracket through the enclosure.
  Node-only path endpoints are checked against the Blender metadata in the GLB.
- Click a model part or component-list button to read its overview.
- **Focus on this component** frames the selected assembly with the camera;
  it does not change layer visibility or the explode setting.
- **Show all** shows all parts applicable to the variant.
- Drag the divider on the left edge of the information panel to widen it, or
  use **Expand / Collapse**. Arrow keys resize the focused divider; Home/End
  choose its minimum/maximum width. Double-click resets its width. The 3D view
  retains a minimum width; narrow screens keep the stacked responsive layout.
- **Overview / Specs & Limits** keeps the short introduction separate from
  composition, technical specifications, limitations and primary-source links.
  Arrow keys, Home and End operate the information tabs.

## Data and verification

`specs.js` distinguishes manufacturer data from CAD revision 2 proposals and
includes source links. Radio memory values are chip totals, not free application
memory. LoRa frequency coverage distinguishes the SX1262 chip, regional module
and FireWatch US band. Kilometer-scale communication and exceptional range-test
examples are not a guaranteed FireWatch link distance or fire-detection radius.

The GLB comes from `../cad/firewatch_revision2.blend` via
`../cad/scripts/export_viewer.py`. Studio, reference pole and ground are excluded.
`assets/model-manifest.json` records the export. Re-export after changing CAD.
`explosion-paths.json` records the restored Blender offsets in millimetres.
`../cad/scripts/audit_explosion.py` checks inter-assembly triangle intersections
along the configured paths and records results in `assets/explosion-audit.json`.
It distinguishes pre-existing assembled contacts from new/increased intersections.
Temporary preview renders and logs are excluded from Git. This inspection layout
is not a validated physical disassembly or manufacturing-fit simulation.

With Node.js available, `node sensors/viewer/verify.mjs` checks visibility,
camera-only focus, panel resizing, tier/mount combinations and specification data
against the actual GLB metadata. It does not substitute for browser visual QA.

The prior browser-check attempt was blocked by Windows browser URL-policy support.
The user confirmed the initial viewer appearance; later interaction changes have
non-visual checks and should be reviewed after a page refresh.
