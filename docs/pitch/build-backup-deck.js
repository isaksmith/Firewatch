// Builds docs/pitch/Firewatch-Backup.pptx: backup slides for questions (contingency plans and what's next),
// kept separate from the main pitch. Same look as build-deck.js and the same packages:
//   NODE_PATH=/tmp/fwdeck/node_modules node docs/pitch/build-backup-deck.js      (OUT=<pptx> to write elsewhere)
// Facts checked 2026-11-08; sources are on each slide. Our own estimates say "(our estimate)".
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fa = require("react-icons/fa");

const REPO = require("path").resolve(__dirname, "../..");
const SLIDES = 7;
const C = {
  void: "050607", bg: "08090B", panel: "0C0E11", panel2: "121519", raised: "181C21",
  line: "1D2127", line2: "2A3038", text: "E6E8EB", muted: "8B939D", dim: "565E68",
  ember: "FF4B2B", amber: "FFB21A", ok: "3DDC97", sky: "5CC8FF", violet: "B18CFF",
};
const F = { head: "Arial", body: "Arial", mono: "Courier New" };
const W = 10, H = 5.625;

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: `#${color}`, size: String(size) }));
  return "image/png;base64," + (await sharp(Buffer.from(svg)).png().toBuffer()).toString("base64");
}
async function photo(path, width = 900) {
  return "image/jpeg;base64," + (await sharp(path).resize({ width }).jpeg({ quality: 86 }).toBuffer()).toString("base64");
}
function brackets(s, pres, color = C.line2) {
  const m = 0.22, l = 0.22;
  const add = (x, y, w, h) => s.addShape(pres.shapes.LINE, { x, y, w, h, line: { color, width: 1 } });
  add(m, m, l, 0); add(m, m, 0, l); add(W - m - l, m, l, 0); add(W - m, m, 0, l);
  add(m, H - m, l, 0); add(m, H - m - l, 0, l); add(W - m - l, H - m, l, 0); add(W - m, H - m - l, 0, l);
}
const kicker = (s, t, color = C.muted) => s.addText(t, { x: 0.6, y: 0.42, w: 8.8, h: 0.3, fontFace: F.body, bold: true, fontSize: 10, color, charSpacing: 3, margin: 0 });
const title = (s, t, size = 26) => s.addText(t, { x: 0.6, y: 0.72, w: 8.8, h: 0.6, fontFace: F.head, bold: true, fontSize: size, color: C.text, margin: 0, valign: "top" });
function footer(s, n) {
  s.addText(`B${n} / ${SLIDES}`, { x: W - 1.3, y: H - 0.42, w: 0.8, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, align: "right", margin: 0 });
  s.addText("FIREWATCH  ·  BACKUP", { x: 0.6, y: H - 0.42, w: 3, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 3, margin: 0 });
}
const source = (s, t, y = 4.9) => s.addText(t, { x: 0.6, y, w: 8.8, h: 0.25, fontFace: F.body, fontSize: 7.5, italic: true, color: C.dim, margin: 0, valign: "top" });
function card(s, pres, x, y, w, h, color) {
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color }, line: { type: "none" } });
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "Firewatch team";
  pres.title = "Firewatch: contingency plans and what's next";
  const ic = {
    wrench: await icon(fa.FaTools, C.void), plane: await icon(fa.FaPlane, C.void), wind: await icon(fa.FaWind, C.void),
    users: await icon(fa.FaUsers, C.void), gavel: await icon(fa.FaBalanceScale, C.void),
  };

  // B1. Title
  {
    const s = pres.addSlide();
    s.background = { color: C.void };
    brackets(s, pres, C.muted);
    s.addText("BACKUP SLIDES  ·  FOR QUESTIONS", { x: 0.6, y: 0.5, w: 8.8, h: 0.3, fontFace: F.body, bold: true, fontSize: 9, color: C.muted, charSpacing: 2, margin: 0 });
    s.addText("When things break,\nand what we'd add next", { x: 0.6, y: 1.5, w: 8.8, h: 1.5, fontFace: F.head, bold: true, fontSize: 38, color: C.text, margin: 0, valign: "top" });
    s.addText("Sensor failures and fallbacks  ·  why no drones yet, and which ones later  ·  protecting the sensor mounts from fire", {
      x: 0.6, y: 3.25, w: 8.4, h: 0.6, fontFace: F.body, fontSize: 14, color: C.ember, bold: true, margin: 0, valign: "top" });
    s.addText("The rule behind all of it: if any part of Firewatch fails, the district is back to today, never worse. 911 stays the main path.", {
      x: 0.6, y: 4.2, w: 8.4, h: 0.5, fontFace: F.body, fontSize: 12, color: C.muted, margin: 0, valign: "top" });
    s.addNotes("Backup slides for the question period. The one rule to say out loud: if any part of Firewatch fails, the district is back to how it works today, never worse, and 911 stays the main path.");
  }

  // B2. When a sensor fails
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "CONTINGENCY  ·  FIRENODE SENSORS", C.amber);
    title(s, "A broken sensor goes quiet. It never pages.");
    const rows = [
      ["Radio link", "No check-in for 30 min: Watch. For 2 hours: \"Radio link down, cause unknown\"."],
      ["Stuck sensor", "Check-ins arrive but a reading repeats 3 times: \"stale, may need replacement\". Its readings can't raise smoke."],
      ["Battery", "Under 80% of its capacity: Watch. Under 70%: Replace."],
      ["Solar panel", "Under 45% of the network's output: clean or re-aim. No output in daylight: Replace."],
      ["Smoke inlet", "Reads zero while other nodes see smoke: blocked inlet or stopped fan."],
    ];
    const x = 0.6, y0 = 1.5, rh = 0.5, w1 = 1.55, w2 = 4.1;
    rows.forEach(([a, b], i) => {
      const y = y0 + i * rh;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: w1 + w2, h: rh - 0.06, fill: { color: i % 2 ? C.panel : C.panel2 }, line: { type: "none" } });
      s.addText(a, { x: x + 0.15, y, w: w1 - 0.2, h: rh - 0.06, fontFace: F.head, bold: true, fontSize: 11, color: C.amber, valign: "middle", margin: 0 });
      s.addText(b, { x: x + w1, y, w: w2 - 0.15, h: rh - 0.06, fontFace: F.body, fontSize: 9.5, color: C.text, valign: "middle", margin: 0 });
    });
    const px = 6.55, pw = 2.85;
    const facts = [
      { big: "Never pages", text: "Sensors alone never page anyone. All sensors together count as one source.", color: C.ok },
      { big: "Others keep working", text: "Satellites, co-op line faults and texted reports don't depend on the sensors.", color: C.sky },
      { big: "Fix on the next visit", text: "The console names the node and the part: battery, panel, inlet or radio.", color: C.amber },
    ];
    facts.forEach((f, i) => {
      const y = 1.5 + i * 0.98;
      card(s, pres, px, y, pw, 0.88, f.color);
      s.addText(f.big, { x: px + 0.2, y: y + 0.08, w: pw - 0.3, h: 0.3, fontFace: F.head, bold: true, fontSize: 13, color: f.color, margin: 0 });
      s.addText(f.text, { x: px + 0.2, y: y + 0.38, w: pw - 0.3, h: 0.46, fontFace: F.body, fontSize: 9, color: C.muted, margin: 0, valign: "top" });
    });
    source(s, "Built: backend/app/sensor_health.py (DESIGN.md 5.12). The thresholds are placeholders until a first field season sets real ones. The sensors themselves are a design, not yet field-tested.", 4.62);
    footer(s, 2);
    s.addNotes("If a sensor breaks, it goes quiet; it never raises an alarm. Every node is checked from its own reports: radio, stuck readings, battery, solar and the smoke inlet, and the console tells the volunteer which part to fix on the next visit. Sensors alone can never page anyone, and the satellites, the co-op's line faults and texted reports don't depend on them. These thresholds are placeholders until a field season.");
  }

  // B3. Fallback table
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "CONTINGENCY  ·  EVERY LAYER", C.ember);
    title(s, "Every part has a fallback; the floor is 911");
    const rows = [
      ["Duty officer doesn't answer", "After 3 minutes the chief gets the text, then county dispatch", "Built"],
      ["Volunteers don't answer", "A mutual-aid request is drafted; one reply sends it", "Built"],
      ["FireMesh radio is down", "Texts carry on as normal; the console shows MESH down", "Built"],
      ["A data feed is late or down", "The top bar says DOWN or NO DATA, never \"no fire\"", "Built"],
      ["A sensor node dies", "It drops to offline; the other sources keep working", "Built"],
      ["The scorer is wrong", "A person decides every page; overrides are logged", "Built"],
      ["Firewatch's server is down", "An outside monitor texts the chief: \"Firewatch offline, 911 is your only detection\"", "Planned"],
    ];
    const x = 0.6, y0 = 1.42, rh = 0.43, w = [2.6, 5.15, 1.05];
    s.addText([{ text: "IF THIS FAILS" }], { x: x + 0.15, y: y0 - 0.02, w: w[0], h: 0.25, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 2, margin: 0 });
    s.addText("WHAT HAPPENS", { x: x + w[0], y: y0 - 0.02, w: w[1], h: 0.25, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 2, margin: 0 });
    s.addText("STATUS", { x: x + w[0] + w[1], y: y0 - 0.02, w: w[2], h: 0.25, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 2, margin: 0 });
    rows.forEach(([a, b, st], i) => {
      const y = y0 + 0.28 + i * rh;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: w[0] + w[1] + w[2], h: rh - 0.05, fill: { color: i % 2 ? C.panel : C.panel2 }, line: { type: "none" } });
      s.addText(a, { x: x + 0.15, y, w: w[0] - 0.2, h: rh - 0.05, fontFace: F.head, bold: true, fontSize: 10.5, color: C.text, valign: "middle", margin: 0 });
      s.addText(b, { x: x + w[0], y, w: w[1] - 0.15, h: rh - 0.05, fontFace: F.body, fontSize: 9.5, color: C.muted, valign: "middle", margin: 0 });
      const col = st === "Built" ? C.ok : C.amber;
      s.addText(st.toUpperCase(), { x: x + w[0] + w[1], y, w: w[2] - 0.1, h: rh - 0.05, fontFace: F.mono, bold: true, fontSize: 9, color: col, valign: "middle", margin: 0 });
    });
    source(s, "Failure table: docs/PLAN.md section 6. \"Built\" means it runs in the app today; \"Planned\" means designed but not built yet.", 4.85);
    footer(s, 3);
    s.addNotes("Every part has a fallback. If the duty officer doesn't answer, the chief gets it in three minutes, then dispatch. If crews don't answer, mutual aid is one reply away. Radio down, texts still go. A feed down says so, it never says no fire. The one we haven't built yet is the outside monitor that tells the chief when our server itself is down. And the floor under all of it is today: 911 still works.");
  }

  // B4. Why no drones
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "FUTURE  ·  DRONES", C.sky);
    title(s, "Why we didn't make drones the detector");
    const cols = [
      { icon: ic.gavel, color: C.sky, head: "The rules", lead: "A pilot must see it", text: "FAA Part 107 needs the drone in the pilot's sight. Flying beyond that needs a waiver. The rule that would allow it routinely (Part 108) went to White House review in July 2026 and isn't final." },
      { icon: ic.wind, color: C.amber, head: "The wind", lead: "Red-flag days ground them", text: "Red-flag days here run 30–40 mph. A DJI Matrice 4T is rated to 12 m/s (27 mph). A Trinity Pro fixed-wing: 11 m/s (25 mph) to take off and land, 14 m/s (31 mph) in flight." },
      { icon: ic.users, color: C.ember, head: "The people", lead: "Someone has to fly it", text: "A certified pilot has to launch it on site. Only 5 of the 18 volunteers can leave work on a weekday, and they're needed on the truck." },
    ];
    const cw = 2.75, gap = 0.28, cy = 1.5, ch = 2.95;
    cols.forEach((c, i) => {
      const cx = 0.6 + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.06, fill: { color: c.color }, line: { type: "none" } });
      s.addShape(pres.shapes.OVAL, { x: cx + 0.25, y: cy + 0.3, w: 0.55, h: 0.55, fill: { color: c.color }, line: { type: "none" } });
      s.addImage({ data: c.icon, x: cx + 0.39, y: cy + 0.44, w: 0.27, h: 0.27 });
      s.addText(c.head, { x: cx + 0.95, y: cy + 0.3, w: cw - 1.1, h: 0.32, fontFace: F.head, bold: true, fontSize: 16, color: C.text, margin: 0 });
      s.addText(c.lead, { x: cx + 0.95, y: cy + 0.62, w: cw - 1.1, h: 0.25, fontFace: F.body, fontSize: 9.5, color: c.color, margin: 0 });
      s.addText(c.text, { x: cx + 0.22, y: cy + 1.05, w: cw - 0.42, h: ch - 1.15, fontFace: F.body, fontSize: 10.5, color: C.text, margin: 0, valign: "top" });
    });
    s.addText("A drone is a good tool for the first volunteer on scene. It can't watch 450 square miles.", {
      x: 0.6, y: 4.6, w: 8.8, h: 0.3, fontFace: F.body, fontSize: 12, italic: true, bold: true, color: C.text, margin: 0 });
    source(s, "FAA 14 CFR 107.31; Part 108: UAV Coach, Airdata (Oct 2026). Wind: DJI dealer specs; Trinity Pro tech sheet (2024). Red-flag winds: RESEARCH.md. Volunteers: packet.", 4.93);
    footer(s, 4);
    s.addNotes("Why not drones as the detector? Three reasons. Rules: a drone has to stay in the pilot's sight; flying beyond that needs a waiver, and the FAA rule that would make it routine, Part 108, has been at the White House since July and isn't final. Wind: red-flag days here run 30 to 40 mph, and even good enterprise drones are rated to roughly 25 to 31. People: someone certified has to launch it, and only five of our eighteen volunteers can leave work on a weekday. So a drone helps the first volunteer on scene, but it can't watch 450 square miles.");
  }

  // B5. Drones later
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "FUTURE  ·  DRONES", C.sky);
    title(s, "Which drones could help later, and what they cost");
    const head = ["", "Quadcopter with thermal camera", "Fixed-wing VTOL"];
    const rows = [
      ["Example", "Skydio X10 (US-made, Blue UAS)", "Quantum Systems Trinity Pro"],
      ["Cost", "Quote only; the Army paid about $20k each in a 2,500-unit order", "Quote only; roughly $20–40k with a thermal camera (our estimate)"],
      ["Wind", "Gusts to about 28 mph", "25 mph to take off and land, 31 mph in flight"],
      ["Reach", "Kept within the pilot's sight", "5–7.5 km radio range, up to about 60 min a flight"],
      ["Crew", "1 pilot with a Part 107 card ($175 test)", "A pilot plus an observer; past line of sight needs a waiver or Part 108"],
      ["Best use", "First on scene: size-up, night hot spots, mop-up", "Shared by the county: scout long power lines, map the burn afterward"],
    ];
    const x = 0.6, y0 = 1.42, rh = 0.42, w = [1.25, 3.75, 3.8];
    head.forEach((h, j) => s.addText(h, { x: x + w.slice(0, j).reduce((a, b) => a + b, 0) + 0.12, y: y0, w: w[j] - 0.15, h: 0.3, fontFace: F.head, bold: true, fontSize: 12, color: j === 1 ? C.sky : C.ok, margin: 0 }));
    rows.forEach((r, i) => {
      const y = y0 + 0.36 + i * rh;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: w[0] + w[1] + w[2], h: rh - 0.05, fill: { color: i % 2 ? C.panel : C.panel2 }, line: { type: "none" } });
      r.forEach((t, j) => s.addText(t, {
        x: x + w.slice(0, j).reduce((a, b) => a + b, 0) + 0.12, y, w: w[j] - 0.18, h: rh - 0.05,
        fontFace: j ? F.body : F.mono, bold: !j, fontSize: j ? 9.5 : 8.5, color: j ? C.text : C.muted, valign: "middle", margin: 0,
      }));
    });
    s.addText("Buy US-made or Blue UAS: since December 2025 new foreign-made drones are on the FCC's Covered List, and federal grants can't buy them. Funding: Kansas Forest Service VFA grant or FEMA's Assistance to Firefighters.", {
      x: 0.6, y: 4.36, w: 8.8, h: 0.36, fontFace: F.body, fontSize: 9, color: C.amber, margin: 0, valign: "top" });
    source(s, "Skydio X10 specs and Army order: Skydio, DroneXL (2026). Trinity Pro: Quantum Systems tech sheet (2024). FCC Covered List: Morgan Lewis, DroneXL (2026). Part 107 fee: PSI test, $175. Prices are quote-only; get dealer quotes before budgeting.", 4.8);
    footer(s, 5);
    s.addNotes("If the district wants a drone later, there are two kinds. A quadcopter with a thermal camera, like the US-made Skydio X10, for the first volunteer on scene: size-up, night hot spots and mop-up, flown by one certified pilot. And a fixed-wing VTOL like the Trinity Pro, better shared at county level to scout long power lines and map a burn afterward; it needs a pilot and an observer and still can't fly beyond sight without a waiver. Neither has a public price; the Army paid about twenty thousand each for Skydios. And buy US-made: since December, federal grants can't buy new foreign-made drones.");
  }

  // B6. Protecting the mounts, cheaply
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "FUTURE  ·  PROTECTING THE SENSOR MOUNTS", C.ember);
    title(s, "Protecting each mount for a few dollars");
    const head = ["Option", "What it does", "Per node", "90 nodes", "Catch"];
    const rows = [
      ["Mowed or gravel 3 m circle", "Nothing to burn right next to the node", "Volunteer time", "Volunteer time", "Needs mowing each spring", C.ok],
      ["Long-term retardant on that circle", "Sprayed once a season; grass there won't carry flame", "About $2", "About $180 a season", "A quarter inch of rain washes it off", C.ok],
      ["Extinguisher ball, bought wholesale", "Bursts by itself when flame touches it", "$2–5", "$180–450", "Certification unchecked; one shot", C.amber],
      ["Aerosol unit inside the box", "Puts out a fire in the node itself (its battery)", "About $11–13", "About $1,000–1,200", "Doesn't help with the grass", C.sky],
      ["Retail extinguisher ball (last version)", "Same ball, store price", "$100–130", "$9,000–11,700", "Costs nearly as much as the network", C.dim],
    ];
    const x = 0.6, y0 = 1.4, rh = 0.48, w = [2.25, 2.55, 1.05, 1.35, 1.6];
    const X = (j) => x + w.slice(0, j).reduce((a, b) => a + b, 0);
    head.forEach((h, j) => s.addText(h.toUpperCase(), { x: X(j) + 0.12, y: y0, w: w[j] - 0.15, h: 0.25, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 1, margin: 0 }));
    rows.forEach((r, i) => {
      const y = y0 + 0.3 + i * rh, col = r[5], last = i === rows.length - 1;
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: w.reduce((a, b) => a + b, 0), h: rh - 0.05, fill: { color: i % 2 ? C.panel : C.panel2 }, line: { type: "none" } });
      s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.05, h: rh - 0.05, fill: { color: col }, line: { type: "none" } });
      r.slice(0, 5).forEach((t, j) => s.addText(t, {
        x: X(j) + 0.12, y, w: w[j] - 0.17, h: rh - 0.05, fontFace: F.body, bold: j === 0 || j === 2 || j === 3,
        fontSize: j === 0 ? 9.5 : 9, color: last ? C.dim : (j === 2 || j === 3 ? col : j === 0 ? C.text : C.muted), valign: "middle", margin: 0,
        strike: last && (j === 2 || j === 3) ? "sngStrike" : undefined,
      }));
    });
    card(s, pres, 0.6, 4.18, 8.8, 0.55, C.ok);
    s.addText([
      { text: "Our pick: ", options: { bold: true, color: C.ok } },
      { text: "a cleared circle and retardant at every node, plus wholesale balls on the 20 pole nodes. Under $300 a season for the whole network (our estimate). It saves the nodes, not the pasture.", options: { color: C.text } },
    ], { x: 0.8, y: 4.18, w: 8.5, h: 0.55, fontFace: F.body, fontSize: 10.5, valign: "middle", margin: 0 });
    source(s, "Retardant: Phos-Chek Wildfire Home Defense, $60.74 makes 5 gal, ~500 sq ft per gal (DoMyOwn); a 3 m circle is ~76 sq ft. Balls: Alibaba / Made-in-China listings, $2–5 at 100+. Aerosol: Live LFE10G, £8.50–10.20, 170 °C, up to 0.4 m³. Retail ball: Elide ELY6, Tractor Supply. Per-node math is our estimate.", 4.82);
    footer(s, 6);
    s.addNotes("The extinguisher ball at store price was too expensive, so here are the cheaper ways. The best protection is passive: keep a three-meter circle under each node mowed or graveled, and spray it with long-term retardant once a season, about two dollars a node. If we want something active, the same self-activating balls cost two to five dollars each bought wholesale, so we'd put them on the twenty pole nodes. And a ten-dollar aerosol unit inside the box puts out a fire in the node's own battery. Together that's under three hundred dollars a season for the whole network. It protects the nodes, not the pasture.");
  }

  // B7. What's next
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "FUTURE CONSIDERATIONS", C.ok);
    title(s, "What we'd add, in order");
    const cols = [
      { head: "THIS BURN SEASON", color: C.ok, items: ["Field burn trial: how far a node smells smoke", "Mow or gravel a circle under each node, and spray it with retardant", "Build the outside server monitor", "Pilot with one district and its co-op"] },
      { head: "NEXT YEAR", color: C.amber, items: ["Wholesale extinguisher balls on the 20 pole nodes, once a certified supplier is found", "A thermal drone for the first volunteer on scene (US-made, grant-funded)", "Test a safer battery chemistry for nodes in full sun"] },
      { head: "WHEN THE RULES ALLOW", color: C.sky, items: ["Once Part 108 is final: a county-shared fixed-wing to scout lines on red-flag days", "Cameras on grain elevators or water towers: about $1.5–4k per site (rough)"] },
    ];
    const cw = 2.75, gap = 0.28, cy = 1.45, ch = 3.25;
    cols.forEach((c, i) => {
      const cx = 0.6 + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.06, fill: { color: c.color }, line: { type: "none" } });
      s.addText(c.head, { x: cx + 0.2, y: cy + 0.22, w: cw - 0.4, h: 0.25, fontFace: F.mono, bold: true, fontSize: 9.5, color: c.color, charSpacing: 2, margin: 0 });
      s.addText(c.items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < c.items.length - 1 } })), {
        x: cx + 0.2, y: cy + 0.6, w: cw - 0.4, h: ch - 0.7, fontFace: F.body, fontSize: 10.5, color: C.text, valign: "top", paraSpaceAfter: 7, margin: 0 });
    });
    source(s, "Camera cost: docs/PLAN.md phase 3 (rough, before vendor quotes). Battery: nodes use a protected single-cell Li-ion pack with a temperature probe (sensors/README.md); a safer chemistry is our suggestion, not tested.", 4.85);
    footer(s, 7);
    s.addNotes("What we'd add, in order. This burn season: the field burn trial, a cleared, retardant-sprayed circle under each node, the outside server monitor, and a pilot with one district and its co-op. Next year: wholesale extinguisher balls on the pole nodes, a US-made thermal drone for the first volunteer on scene, and a safer battery for nodes in full sun. When the rules allow: a county-shared fixed-wing once Part 108 is final, and cameras on grain elevators or water towers.");
  }

  await pres.writeFile({ fileName: process.env.OUT || `${REPO}/docs/pitch/Firewatch-Backup.pptx` });
  console.log("written");
})();
