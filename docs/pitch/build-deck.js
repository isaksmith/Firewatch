// Builds docs/pitch/Firewatch-Pitch.pptx. Its packages aren't project dependencies:
//   npm i --prefix /tmp/fwdeck pptxgenjs react react-dom react-icons sharp
//   NODE_PATH=/tmp/fwdeck/node_modules node docs/pitch/build-deck.js
const pptxgen = require("pptxgenjs");
const React = require("react");
const ReactDOMServer = require("react-dom/server");
const sharp = require("sharp");
const fs = require("fs");
const fa = require("react-icons/fa");

const REPO = require("path").resolve(__dirname, "../..");
const IMG = {
  console: `${REPO}/docs/images/console.png`,
  spread: `${REPO}/docs/images/spread-3d.jpg`,
  planner: `${REPO}/docs/images/planner.png`,
  phoneHome: `${REPO}/mobile/shots/08-home-radio-alert.png`,
  phoneAlert: `${REPO}/mobile/shots/09-alert-by-radio.png`,
  phoneBoard: `${REPO}/mobile/shots/10-board.png`,
  nodeExploded: `${REPO}/sensors/cad/renders/v2_rich_exploded.png`,
  nodeStake: `${REPO}/sensors/cad/renders/v2_bare_stake.png`,
  nodeBand: `${REPO}/sensors/cad/renders/v2_rich_band.png`,
};
const SLIDES = 11;

const C = {
  void: "050607", bg: "08090B", panel: "0C0E11", panel2: "121519", raised: "181C21",
  line: "1D2127", line2: "2A3038", text: "E6E8EB", muted: "8B939D", dim: "565E68",
  ember: "FF4B2B", amber: "FFB21A", ok: "3DDC97", sky: "5CC8FF",
};
const F = { head: "Arial", body: "Arial", mono: "Courier New" };
const W = 10, H = 5.625;

async function icon(Comp, color, size = 256) {
  const svg = ReactDOMServer.renderToStaticMarkup(React.createElement(Comp, { color: `#${color}`, size: String(size) }));
  const png = await sharp(Buffer.from(svg)).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

// The CAD renders are 2-3 MB PNGs; a slide only needs a ~1000 px JPEG.
async function photo(path, width = 1000) {
  const jpg = await sharp(path).resize({ width }).jpeg({ quality: 86 }).toBuffer();
  return "image/jpeg;base64," + jpg.toString("base64");
}

async function logo() {
  const svg = fs.readFileSync(`${REPO}/frontend/public/favicon.svg`);
  const png = await sharp(svg, { density: 600 }).resize(512, 512).png().toBuffer();
  return "image/png;base64," + png.toString("base64");
}

function brackets(slide, pres, color = C.line2) {
  const m = 0.22, l = 0.22, wt = 1;
  const add = (x, y, w, h) => slide.addShape(pres.shapes.LINE, { x, y, w, h, line: { color, width: wt } });
  add(m, m, l, 0); add(m, m, 0, l);
  add(W - m - l, m, l, 0); add(W - m, m, 0, l);
  add(m, H - m, l, 0); add(m, H - m - l, 0, l);
  add(W - m - l, H - m, l, 0); add(W - m, H - m - l, 0, l);
}

function kicker(slide, text, color = C.muted, y = 0.42) {
  slide.addText(text, { x: 0.6, y, w: 8.8, h: 0.3, fontFace: F.body, bold: true, fontSize: 10, color, charSpacing: 3, margin: 0 });
}

function title(slide, text, y = 0.72, size = 30) {
  slide.addText(text, { x: 0.6, y, w: 8.8, h: 0.7, fontFace: F.head, bold: true, fontSize: size, color: C.text, margin: 0, valign: "top" });
}

function footer(slide, n) {
  slide.addText(`${n} / ${SLIDES}`, { x: W - 1.3, y: H - 0.42, w: 0.8, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, align: "right", margin: 0 });
  slide.addText("FIREWATCH", { x: 0.6, y: H - 0.42, w: 2, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, charSpacing: 3, margin: 0 });
}

(async () => {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "Firewatch team";
  pres.title = "Firewatch: Detect, Confirm, Respond";

  const LOGO = await logo();
  const ic = {
    sat: await icon(fa.FaSatelliteDish, C.void),
    check: await icon(fa.FaCheckDouble, C.void),
    horn: await icon(fa.FaBullhorn, C.void),
    sms: await icon(fa.FaSms, C.void),
    tower: await icon(fa.FaBroadcastTower, C.void),
    phone: await icon(fa.FaMobileAlt, C.void),
    ok: await icon(fa.FaCheck, C.ok),
    next: await icon(fa.FaArrowRight, C.amber),
    burn: await icon(fa.FaFireAlt, C.ember),
  };

  // 1. Title
  {
    const s = pres.addSlide();
    s.background = { color: C.void };
    s.addImage({ path: IMG.spread, x: 0, y: 0, w: W, h: H, sizing: { type: "cover", w: W, h: H } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: H, fill: { color: C.void, transparency: 35 }, line: { type: "none" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 5.9, h: H, fill: { color: C.void, transparency: 4 }, line: { type: "none" } });
    brackets(s, pres, C.muted);
    s.addText("FIREWATCH 2026  ·  WSU INNOVATION WORKS × LOCKHEED MARTIN SKUNK WORKS", {
      x: 0.6, y: 0.5, w: 8.5, h: 0.3, fontFace: F.body, bold: true, fontSize: 9, color: C.muted, charSpacing: 2, margin: 0,
    });
    s.addImage({ data: LOGO, x: 0.6, y: 1.25, w: 0.75, h: 0.75 });
    s.addText("Firewatch", { x: 0.6, y: 2.15, w: 5.2, h: 0.9, fontFace: F.head, bold: true, fontSize: 50, color: C.text, margin: 0 });
    s.addText("Detect → Confirm → Respond", { x: 0.6, y: 3.05, w: 5.2, h: 0.5, fontFace: F.head, bold: true, fontSize: 20, color: C.ember, margin: 0 });
    s.addText("Early wildfire warning for rural Kansas volunteer fire districts, built to work on one bar of cell.", {
      x: 0.6, y: 3.65, w: 4.9, h: 0.75, fontFace: F.body, fontSize: 15, color: C.text, margin: 0, valign: "top",
    });
    s.addText("COTTONWOOD CREEK  ·  450 SQ MI  ·  18 VOLUNTEERS", {
      x: 0.6, y: 4.85, w: 5.2, h: 0.25, fontFace: F.body, bold: true, fontSize: 9, color: C.amber, charSpacing: 2, margin: 0,
    });
    s.addNotes("(15 s) We're Firewatch. We built an early-warning system for rural volunteer fire districts like Cottonwood Creek: 450 square miles, 18 volunteers, and often one bar of cell. Behind me is our forecast of the packet's fire, 60 minutes after the line came down.");
  }

  // 2. Problem
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "THE PROBLEM", C.ember);
    title(s, "A fire nobody sees for 31 minutes");

    const x0 = 0.8, x1 = 9.2, y = 2.45, T = 62;
    const X = (t) => x0 + (x1 - x0) * (t / T);
    s.addShape(pres.shapes.RECTANGLE, { x: x0, y: y - 0.04, w: x1 - x0, h: 0.08, fill: { color: C.line2 }, line: { type: "none" } });
    s.addShape(pres.shapes.RECTANGLE, { x: x0, y: y - 0.06, w: X(31) - x0, h: 0.12, fill: { color: C.ember }, line: { type: "none" } });
    s.addText("NOBODY KNOWS", { x: X(4), y: y - 0.36, w: 2.4, h: 0.25, fontFace: F.mono, fontSize: 9, bold: true, color: C.ember, charSpacing: 2, margin: 0 });
    const marks = [
      { t: 0, time: "1:50", label: "Line drops into dry grass", up: false, align: "left" },
      { t: 27, time: "2:17", label: "A rancher sees smoke", up: true, align: "center" },
      { t: 31, time: "2:21", label: "911 is called", up: false, align: "center" },
      { t: 44, time: "2:34", label: "Trucks roll", up: true, align: "center" },
      { t: 62, time: "2:52", label: "First truck: fire 2–3 mi long", up: false, align: "right" },
    ];
    for (const m of marks) {
      const cx = X(m.t);
      s.addShape(pres.shapes.OVAL, { x: cx - 0.09, y: y - 0.09, w: 0.18, h: 0.18, fill: { color: m.t <= 31 ? C.ember : C.text }, line: { color: C.bg, width: 1.5 } });
      const bw = 2.0;
      const bx = m.align === "left" ? cx - 0.09 : m.align === "right" ? cx + 0.09 - bw : cx - bw / 2;
      const by = m.up ? y - 1.0 : y + 0.22;
      s.addText([
        { text: m.time, options: { fontFace: F.mono, fontSize: 13, bold: true, color: C.text, breakLine: true } },
        { text: m.label, options: { fontFace: F.body, fontSize: 10.5, color: C.muted } },
      ], { x: bx, y: by, w: bw, h: 0.62, align: m.align, valign: m.up ? "bottom" : "top", margin: 0 });
    }

    const cards = [
      { big: "31 min", label: "from ignition to the first 911 call", color: C.ember },
      { big: "+8 min", label: "satellites see Kansas wildfires a median 8 minutes after someone reports them (2016–2025)", color: C.amber },
      { big: "2–3 mi", label: "of fire front when the first truck arrives at 2:52", color: C.text },
    ];
    const cw = 2.6, gap = 0.3, cy = 3.55, ch = 1.2;
    cards.forEach((c, i) => {
      const cx = 0.8 + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: 0.06, h: ch, fill: { color: c.color }, line: { type: "none" } });
      s.addText(c.big, { x: cx + 0.22, y: cy + 0.12, w: cw - 0.35, h: 0.45, fontFace: F.head, bold: true, fontSize: 22, color: c.color, margin: 0 });
      s.addText(c.label, { x: cx + 0.22, y: cy + 0.58, w: cw - 0.35, h: 0.55, fontFace: F.body, fontSize: 10, color: C.muted, margin: 0, valign: "top" });
    });
    s.addText("And a system that cries wolf over March pasture burns gets switched off by April.", {
      x: 0.8, y: 4.88, w: 8.4, h: 0.3, fontFace: F.body, fontSize: 12, italic: true, color: C.text, margin: 0,
    });
    footer(s, 2);
    s.addNotes("(35 s) Here's the packet's scenario. At 1:50 a line comes down into dry grass. For 27 minutes nobody sees it; 911 is called at 2:21, and the first truck arrives at 2:52 to a fire two to three miles long. Satellites don't save us: across ten years of Kansas wildfires they saw the fire a median eight minutes after a person reported it. And any system that alarms on every spring pasture burn gets ignored. Those first 31 minutes are where this fire is won or lost.");
  }

  // 3. How it works
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "HOW IT WORKS");
    title(s, "Detect → Confirm → Respond");
    const cols = [
      { name: "Detect", color: C.amber, icon: ic.sat, lead: "One event per fire", items: ["Co-op line faults on fire-weather days", "Satellite hotspots: VIIRS, MODIS, GOES, NGFS", "Texted reports and tower smoke sensors"] },
      { name: "Confirm", color: C.sky, icon: ic.check, lead: "No drive-out needed", items: ["ML score tells wildfires from burns and flares", "Two independent signals to escalate", "Nearest neighbors texted: \"See smoke? 1 yes, 2 no, 3 my burn\""] },
      { name: "Respond", color: C.ember, icon: ic.horn, lead: "Before the first engine", items: ["Duty officer replies PAGE by text", "Downwind ranchers get direction and arrival time", "Mutual aid drafted when crews are short"] },
    ];
    const cw = 2.75, gap = 0.28, cy = 1.55, ch = 2.95;
    cols.forEach((c, i) => {
      const cx = 0.6 + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: ch, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 0.06, fill: { color: c.color }, line: { type: "none" } });
      s.addShape(pres.shapes.OVAL, { x: cx + 0.25, y: cy + 0.3, w: 0.55, h: 0.55, fill: { color: c.color }, line: { type: "none" } });
      s.addImage({ data: c.icon, x: cx + 0.39, y: cy + 0.44, w: 0.27, h: 0.27 });
      s.addText(c.name, { x: cx + 0.95, y: cy + 0.3, w: cw - 1.1, h: 0.32, fontFace: F.head, bold: true, fontSize: 17, color: C.text, margin: 0 });
      s.addText(c.lead, { x: cx + 0.95, y: cy + 0.62, w: cw - 1.1, h: 0.25, fontFace: F.body, fontSize: 9.5, color: c.color, margin: 0 });
      s.addText(c.items.map((t, j) => ({ text: t, options: { bullet: true, breakLine: j < c.items.length - 1 } })), {
        x: cx + 0.2, y: cy + 1.05, w: cw - 0.4, h: ch - 1.2, fontFace: F.body, fontSize: 11, color: C.text, valign: "top", paraSpaceAfter: 6, margin: 0,
      });
    });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 4.68, w: 8.81, h: 0.42, fill: { color: C.raised }, line: { type: "none" } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 4.68, w: 0.06, h: 0.42, fill: { color: C.ember }, line: { type: "none" } });
    s.addText([
      { text: "Humans decide every page.", options: { bold: true, color: C.text } },
      { text: "  Every signal, text and decision is logged on the event.", options: { color: C.muted } },
    ], { x: 0.85, y: 4.68, w: 8.4, h: 0.42, fontFace: F.body, fontSize: 12, valign: "middle", margin: 0 });
    footer(s, 3);
    s.addNotes("(35 s) Firewatch works in three steps. Detect: we combine cheap signals into one event per fire: a co-op line fault on a fire-weather day, satellite hotspots, a texted report, a tower smoke sensor. Confirm: a machine-learning score separates wildfires from prescribed burns and refinery flares, it takes two independent signals to escalate, and we text the nearest neighbors to ask if they see smoke. Respond: the duty officer gets one text and replies PAGE; downwind ranchers get a warning with an arrival time. A person decides every page.");
  }

  // 4. Console
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "THE CONSOLE  ·  COTTONWOOD CREEK REPLAY");
    title(s, "Escalated in 8 minutes, paged in 9");
    const iw = 5.9, ih = iw / 1.6, ix = 0.6, iy = 1.42;
    s.addShape(pres.shapes.RECTANGLE, { x: ix - 0.03, y: iy - 0.03, w: iw + 0.06, h: ih + 0.06, fill: { color: C.line2 }, line: { type: "none" } });
    s.addImage({ path: IMG.console, x: ix, y: iy, w: iw, h: ih });
    const steps = [
      { t: "T+0", text: "Line fault on a red-flag day starts an event; neighbors are texted" },
      { t: "T+0", text: "Duty officer gets an FYI" },
      { t: "T+8", text: "Satellite confirms: score 99, Escalate" },
      { t: "T+9", text: "Duty officer replies PAGE; county dispatch pages the district" },
      { t: "T+12", text: "Mutual aid requested; downwind ranchers warned with arrival time" },
    ];
    const sx = 6.8, sy = 1.42, rh = 0.74;
    steps.forEach((st, i) => {
      const y = sy + i * rh;
      s.addShape(pres.shapes.RECTANGLE, { x: sx, y, w: 0.62, h: 0.3, fill: { color: i >= 2 ? C.ember : C.raised }, line: { type: "none" } });
      s.addText(st.t, { x: sx, y, w: 0.62, h: 0.3, fontFace: F.mono, fontSize: 10, bold: true, color: i >= 2 ? C.void : C.text, align: "center", valign: "middle", margin: 0 });
      s.addText(st.text, { x: sx + 0.75, y: y - 0.03, w: 9.4 - sx - 0.75, h: 0.66, fontFace: F.body, fontSize: 10.5, color: C.text, valign: "top", margin: 0 });
    });
    footer(s, 4);
    s.addNotes("(40 s) This is the console during the replay. At T+0 the co-op's line lockout on a red-flag day opens an event, the duty officer gets an FYI, and the three nearest neighbors are asked by text. At T+8 a satellite pass gives the second independent source: score 99, Escalate. At T+9 the duty officer replies PAGE from his phone and county dispatch pages the district. Mutual aid goes out at T+12, and downwind ranchers get the direction and an arrival estimate from our spread forecast. Every text is in the drawer on the right.");
  }

  // 5. Results
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "SAME FIRE, SAME CREW", C.ok);
    title(s, "First truck on scene 24 minutes sooner");
    const x0 = 1.95, x1 = 9.3, T = 62;
    const X = (t) => x0 + (x1 - x0) * (t / T);
    const rows = [
      { name: "Today", y: 1.6, segs: [[0, 31, C.ember, "Nobody knows"], [31, 44, "3A424C", "911 to roll"], [44, 62, "4A535E", "Driving"]], end: 62, endLabel: "~1,070 ac", endColor: C.ember },
      { name: "Firewatch", y: 2.25, segs: [[0, 9, C.ok, "Paged"], [9, 20, "3A424C", "Turnout"], [20, 38, "4A535E", "Driving"]], end: 38, endLabel: "~360 ac", endColor: C.ok },
    ];
    for (const r of rows) {
      s.addText(r.name, { x: 0.6, y: r.y, w: 1.25, h: 0.38, fontFace: F.head, bold: true, fontSize: 13, color: C.text, valign: "middle", margin: 0 });
      for (const [a, b, col, lab] of r.segs) {
        s.addShape(pres.shapes.RECTANGLE, { x: X(a), y: r.y, w: X(b) - X(a) - 0.02, h: 0.38, fill: { color: col }, line: { type: "none" } });
        const dark = col === C.ok || col === C.ember;
        s.addText(lab, { x: X(a) + 0.06, y: r.y, w: X(b) - X(a) - 0.1, h: 0.38, fontFace: F.mono, fontSize: 9, bold: true, color: dark ? C.void : C.text, valign: "middle", margin: 0, fit: "shrink" });
      }
      s.addShape(pres.shapes.DIAMOND, { x: X(r.end) + 0.04, y: r.y + 0.06, w: 0.26, h: 0.26, fill: { color: r.endColor }, line: { type: "none" } });
      if (r.end < 50) {
        s.addText(r.endLabel, { x: X(r.end) + 0.38, y: r.y, w: 1.4, h: 0.38, fontFace: F.mono, fontSize: 11, bold: true, color: r.endColor, valign: "middle", margin: 0 });
      }
    }
    s.addText("~1,070 ac", { x: X(62) - 1.45, y: 1.6 - 0.32, w: 1.6, h: 0.28, fontFace: F.mono, fontSize: 11, bold: true, color: C.ember, align: "right", margin: 0 });
    const ticks = [[0, "1:50"], [10, "2:00"], [20, "2:10"], [30, "2:20"], [40, "2:30"], [50, "2:40"], [60, "2:50"]];
    ticks.forEach(([t, lab]) => {
      s.addText(lab, { x: X(t) - 0.3, y: 2.72, w: 0.6, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.dim, align: "center", margin: 0 });
    });

    const stats = [
      { big: "T+9", label: "district paged", was: "today: 911 call at T+31" },
      { big: "T+38", label: "first truck on scene", was: "today: T+62" },
      { big: "~360 ac", label: "burned when it arrives", was: "today: ~1,070 acres" },
    ];
    const cw = 2.75, gap = 0.28, cy = 3.2;
    stats.forEach((st, i) => {
      const cx = 0.6 + i * (cw + gap);
      s.addShape(pres.shapes.RECTANGLE, { x: cx, y: cy, w: cw, h: 1.45, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addText(st.big, { x: cx + 0.25, y: cy + 0.15, w: cw - 0.4, h: 0.6, fontFace: F.head, bold: true, fontSize: 30, color: C.ok, margin: 0 });
      s.addText(st.label, { x: cx + 0.25, y: cy + 0.78, w: cw - 0.4, h: 0.26, fontFace: F.body, fontSize: 12, bold: true, color: C.text, margin: 0 });
      s.addText(st.was, { x: cx + 0.25, y: cy + 1.05, w: cw - 0.4, h: 0.24, fontFace: F.mono, bold: true, fontSize: 9.5, color: C.muted, margin: 0 });
    });
    s.addText("Fire sizes are our spread forecast's median for the packet's red-flag Tuesday, not field data. The forecast is back-tested on real Kansas fires (Anderson Creek 2016, Starbuck 2017).", {
      x: 0.6, y: 4.75, w: 8.8, h: 0.35, fontFace: F.body, fontSize: 8.5, italic: true, color: C.dim, margin: 0, valign: "top",
    });
    footer(s, 5);
    s.addNotes("(35 s) Same fire, same crew, same roads. Today the district hears about it at T+31 and the first truck arrives at T+62 to about 1,070 acres. With Firewatch the district is paged at T+9, the truck is on scene at T+38, and our forecast puts the fire at about 360 acres: a third of the size. Those sizes are our forecast's median, which we back-tested against real Kansas fires, not field measurements.");
  }

  // 6. False alarms
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "NO CRYING WOLF", C.amber);
    title(s, "Quiet on burns, loud on wildfires");
    const bars = [
      { label: "Refinery and plant heat kept quiet", v: 99, color: C.ok },
      { label: "Unreported Flint Hills spring burns kept quiet", v: 82, color: C.ok },
      { label: "Real wildfires sent to the duty officer", v: 76, color: C.ember },
    ];
    const bx = 0.6, bw = 5.0, by = 1.55;
    bars.forEach((b, i) => {
      const y = by + i * 0.98;
      s.addText(b.label, { x: bx, y, w: bw - 0.9, h: 0.28, fontFace: F.body, fontSize: 12, color: C.text, margin: 0 });
      s.addShape(pres.shapes.RECTANGLE, { x: bx, y: y + 0.36, w: bw - 0.9, h: 0.3, fill: { color: C.raised }, line: { type: "none" } });
      s.addShape(pres.shapes.RECTANGLE, { x: bx, y: y + 0.36, w: (bw - 0.9) * b.v / 100, h: 0.3, fill: { color: b.color }, line: { type: "none" } });
      s.addText(`${b.v}%`, { x: bx + bw - 0.8, y: y + 0.24, w: 0.85, h: 0.5, fontFace: F.head, bold: true, fontSize: 20, color: b.color, align: "right", margin: 0 });
    });
    s.addText("Machine-learning scorer, tested on 2023–2025 fires it never saw", {
      x: bx, y: 4.5, w: bw, h: 0.25, fontFace: F.mono, bold: true, fontSize: 8.5, color: C.dim, margin: 0,
    });

    const px = 6.0, pw = 3.4;
    s.addShape(pres.shapes.RECTANGLE, { x: px, y: 1.55, w: pw, h: 3.2, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
    const facts = [
      { big: "10 years", text: "of Kansas satellite fires, matched to 224 reported wildfires and 490 burns" },
      { big: "2 sources", text: "before anyone is paged; one source only sends the duty officer an FYI" },
      { big: "0 texts", text: "for a burn the landowner registered, unless it escapes" },
    ];
    facts.forEach((f, i) => {
      const y = 1.72 + i * 0.98;
      s.addText(f.big, { x: px + 0.25, y, w: pw - 0.5, h: 0.34, fontFace: F.head, bold: true, fontSize: 16, color: C.amber, margin: 0 });
      s.addText(f.text, { x: px + 0.25, y: y + 0.36, w: pw - 0.5, h: 0.56, fontFace: F.body, fontSize: 10, color: C.muted, margin: 0, valign: "top" });
    });
    footer(s, 6);
    s.addNotes("(30 s) Trust is the whole game, so we measured false alarms. Our scorer is trained on ten years of Kansas satellite fires and tested on 2023 to 2025 fires it never saw. It keeps 99 percent of refinery and plant heat and 82 percent of unreported spring pasture burns quiet, while 76 percent of real wildfires reach the duty officer. On top of that, it takes two independent sources to page anyone, and a registered burn texts nobody unless it escapes.");
  }

  // 7. One bar
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "BUILT FOR ONE BAR OF CELL", C.sky);
    title(s, "Reaches people where cell doesn't");
    const rows = [
      { icon: ic.sms, color: C.sky, head: "Plain text messages", text: "Reply PAGE, 1, 2 or 3. Works on any phone, about 1 cent a text." },
      { icon: ic.tower, color: C.ok, head: "LoRa mesh radios", text: "Meshtastic radios carry the same texts to trucks and ranches out of coverage. Tested with real radios." },
      { icon: ic.phone, color: C.amber, head: "Phone app", text: "Alerts by text or radio, an offline map of where it's heading, and a board for neighbors' reports." },
    ];
    rows.forEach((r, i) => {
      const y = 1.6 + i * 1.08;
      s.addShape(pres.shapes.OVAL, { x: 0.6, y, w: 0.6, h: 0.6, fill: { color: r.color }, line: { type: "none" } });
      s.addImage({ data: r.icon, x: 0.75, y: y + 0.15, w: 0.3, h: 0.3 });
      s.addText(r.head, { x: 1.4, y: y - 0.02, w: 3.1, h: 0.3, fontFace: F.head, bold: true, fontSize: 14, color: C.text, margin: 0 });
      s.addText(r.text, { x: 1.4, y: y + 0.3, w: 3.1, h: 0.66, fontFace: F.body, fontSize: 10.5, color: C.muted, margin: 0, valign: "top" });
    });
    const ph = 3.1, pw = ph * 1206 / 2622, gap = 0.16;
    const px0 = 9.4 - 3 * pw - 2 * gap;
    [IMG.phoneHome, IMG.phoneAlert, IMG.phoneBoard].forEach((p, i) => {
      const x = px0 + i * (pw + gap), y = 1.5;
      s.addShape(pres.shapes.RECTANGLE, { x: x - 0.03, y: y - 0.03, w: pw + 0.06, h: ph + 0.06, fill: { color: C.line2 }, line: { type: "none" } });
      s.addImage({ path: p, x, y, w: pw, h: ph });
    });
    footer(s, 7);
    s.addNotes("(30 s) Rural Kansas often has one bar of cell, so everything is plain text: reply PAGE, or 1, 2, 3. Where there's no cell at all, the same texts go over Meshtastic LoRa mesh radios to trucks and ranches; we've run it on real radios this weekend. And the phone app gets alerts by text or by radio, shows where the fire is heading on an offline map, and lets neighbors report and confirm smoke.");
  }

  // 8. Sensor node (CAD revision 2 renders from sensors/cad)
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "THE SENSOR NODE  ·  CAD REVISION 2", C.ok);
    title(s, "One box, two tiers, on a stake or a pole", 0.72, 26);

    const tile = (data, x, y, w, h) => {
      s.addShape(pres.shapes.RECTANGLE, { x: x - 0.03, y: y - 0.03, w: w + 0.06, h: h + 0.06, fill: { color: C.line2 }, line: { type: "none" } });
      s.addImage({ data, x, y, w, h });
    };
    const top = 1.45;
    const eh = 3.3, ew = eh * 1600 / 1800;
    tile(await photo(IMG.nodeExploded), 0.6, top, ew, eh);
    s.addText("RICH NODE, EXPLODED", { x: 0.75, y: top + 0.12, w: ew - 0.3, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8, color: C.text, charSpacing: 2, margin: 0 });

    const mx = 0.6 + ew + 0.35, mh = 1.75, mw = mh * 1400 / 1600, mgap = 0.2;
    const mounts = [[IMG.nodeStake, "Bare · ground stake"], [IMG.nodeBand, "Rich · pole band"]];
    for (const [i, [p, cap]] of mounts.entries()) {
      const x = mx + i * (mw + mgap);
      tile(await photo(p, 700), x, top, mw, mh);
      s.addText(cap, { x, y: top + mh + 0.08, w: mw, h: 0.22, fontFace: F.mono, bold: true, fontSize: 8.5, color: C.muted, margin: 0 });
    }

    const chipX = mx + 2 * mw + mgap + 0.3, chipW = 9.4 - chipX;
    const chips = [
      { big: "$136", text: "bare node at ~100 units" },
      { big: "$204", text: "rich node, adds smoke sensing" },
      { big: "Solar", text: "no wiring, relays the mesh" },
    ];
    chips.forEach((c, i) => {
      const y = top + i * 0.62;
      s.addShape(pres.shapes.RECTANGLE, { x: chipX, y, w: chipW, h: 0.52, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: chipX, y, w: 0.06, h: 0.52, fill: { color: C.ok }, line: { type: "none" } });
      s.addText(c.big, { x: chipX + 0.18, y: y + 0.03, w: chipW - 0.25, h: 0.24, fontFace: F.head, bold: true, fontSize: 12.5, color: C.ok, margin: 0 });
      s.addText(c.text, { x: chipX + 0.18, y: y + 0.26, w: chipW - 0.25, h: 0.22, fontFace: F.body, fontSize: 8.5, color: C.muted, margin: 0, fit: "shrink" });
    });

    const cardY = top + mh + 0.45, cardH = 4.75 - cardY, cardGap = 0.25, cardW = (9.4 - mx - cardGap) / 2;
    const tiers = [
      { name: "BARE", color: C.sky, text: "Gas, temperature, humidity, pressure (Bosch BME688). 2\u00A0W panel, 4,400\u00A0mAh." },
      { name: "RICH", color: C.amber, text: "Adds a particle sensor that sees smoke (Plantower PMSA003I). 5\u00A0W panel, 6,600\u00A0mAh." },
    ];
    tiers.forEach((t, i) => {
      const x = mx + i * (cardW + cardGap);
      s.addShape(pres.shapes.RECTANGLE, { x, y: cardY, w: cardW, h: cardH, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x, y: cardY, w: cardW, h: 0.05, fill: { color: t.color }, line: { type: "none" } });
      s.addText(t.name, { x: x + 0.2, y: cardY + 0.15, w: cardW - 0.4, h: 0.25, fontFace: F.mono, bold: true, fontSize: 10, color: t.color, charSpacing: 3, margin: 0 });
      s.addText(t.text, { x: x + 0.2, y: cardY + 0.45, w: cardW - 0.4, h: cardH - 0.55, fontFace: F.body, fontSize: 10, color: C.text, margin: 0, valign: "top" });
    });

    s.addText("Blender design model, not a routed board. Detection distance, power budget and radio range are what the field burn trial measures.", {
      x: 0.6, y: 4.9, w: 8.8, h: 0.22, fontFace: F.body, fontSize: 8.5, italic: true, color: C.dim, margin: 0,
    });
    footer(s, 8);
    s.addNotes("(20 s) This is our sensor node. One weatherproof box in two tiers: the bare node measures gas, temperature, humidity and pressure; the rich node adds a particle sensor that sees smoke. Both run on solar, talk over the same Meshtastic mesh and relay each other's messages, and mount on a ground stake or band onto a pole. At about a hundred units it's 136 dollars bare and 204 rich. It's a design model today; the field burn trial measures how far away it can smell a fire.");
  }

  // 9. Planner
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "REGION PLANNER");
    title(s, "Plan sensors for any Kansas county", 0.72, 26);
    const iw = 4.95, ih = iw / 1.6, ix = 9.4 - iw, iy = 1.45;
    s.addShape(pres.shapes.RECTANGLE, { x: ix - 0.03, y: iy - 0.03, w: iw + 0.06, h: ih + 0.06, fill: { color: C.line2 }, line: { type: "none" } });
    s.addImage({ path: IMG.planner, x: ix, y: iy, w: iw, h: ih });
    s.addText("Places 15-acre sensor plots where fires start and where the wind carries their smoke, from ten years of fires, power lines, tallgrass, terrain and hourly winds. Each plot says why it was chosen.", {
      x: 0.6, y: 1.45, w: 3.6, h: 1.2, fontFace: F.body, fontSize: 11.5, color: C.text, margin: 0, valign: "top",
    });
    const chips = [
      { big: "$15.6k", text: "Cottonwood Creek: 10 plots, 90 nodes, 5 relays, with spares" },
      { big: "$136 / $204", text: "custom-board bare and rich nodes" },
      { big: "$0 / month", text: "free public data, no subscriptions" },
    ];
    chips.forEach((c, i) => {
      const y = 2.8 + i * 0.66;
      s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y, w: 3.6, h: 0.56, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
      s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y, w: 0.06, h: 0.56, fill: { color: C.ok }, line: { type: "none" } });
      s.addText(c.big, { x: 0.8, y, w: 1.35, h: 0.56, fontFace: F.head, bold: true, fontSize: 12.5, color: C.ok, valign: "middle", margin: 0, fit: "shrink" });
      s.addText(c.text, { x: 2.15, y, w: 1.95, h: 0.56, fontFace: F.body, fontSize: 9, color: C.muted, valign: "middle", margin: 0 });
    });
    footer(s, 9);
    s.addNotes("(25 s) For districts that want their own sensors, the planner lays out a network for any Kansas county. It puts sensor plots where fires start and where the wind carries smoke, routes relays with terrain line of sight, and prices it. For Cottonwood Creek, ten plots and five relays come to about fifteen and a half thousand dollars with spares, and every data source is free.");
  }

  // 10. Proof + next
  {
    const s = pres.addSlide();
    s.background = { color: C.bg };
    brackets(s, pres);
    kicker(s, "WHERE IT STANDS");
    title(s, "Built this weekend, tested on real data");
    const built = [
      "598 automated tests pass",
      "Scorer trained on 10 years of Kansas fires",
      "Spread forecast back-tested on real fires",
      "13 live public data feeds checked today",
      "Packet scenario runs end to end, every text logged",
    ];
    const next = [
      "Field burn trial to measure sensor range",
      "Live texting on real phones",
      "Pilot with one Kansas district before spring burn season",
    ];
    const col = (x, w, head, color, items, iconData) => {
      s.addText(head, { x, y: 1.5, w, h: 0.3, fontFace: F.mono, fontSize: 10, bold: true, charSpacing: 3, color, margin: 0 });
      items.forEach((t, i) => {
        const y = 2.0 + i * 0.58;
        s.addImage({ data: iconData, x, y: y + 0.02, w: 0.2, h: 0.2 });
        s.addText(t, { x: x + 0.38, y, w: w - 0.4, h: 0.5, fontFace: F.body, fontSize: 12.5, color: C.text, valign: "top", margin: 0 });
      });
    };
    s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 1.35, w: 4.85, h: 3.6, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
    col(0.85, 4.5, "BUILT AND TESTED", C.ok, built, ic.ok);
    s.addShape(pres.shapes.RECTANGLE, { x: 5.7, y: 1.35, w: 3.7, h: 3.6, fill: { color: C.panel }, line: { color: C.line, width: 0.75 } });
    col(5.95, 3.35, "NEXT", C.amber, next, ic.next);
    s.addShape(pres.shapes.RECTANGLE, { x: 5.95, y: 3.95, w: 3.2, h: 0.78, fill: { color: C.raised }, line: { type: "none" } });
    s.addText([
      { text: "To run a district", options: { bold: true, color: C.text, breakLine: true } },
      { text: "Free public data, about 1 cent a text, optional sensors from $136 a node", options: { color: C.muted } },
    ], { x: 6.1, y: 3.95, w: 2.95, h: 0.78, fontFace: F.body, fontSize: 10, valign: "middle", margin: 0 });
    footer(s, 10);
    s.addNotes("(25 s) It's real code: 598 automated tests, a scorer trained on ten years of Kansas fires, a spread forecast back-tested on real fires, and thirteen live public data feeds we checked working today. Next: a field burn to measure sensor range, live texting on real phones, and a pilot with one Kansas district before spring burn season.");
  }

  // 11. Close
  {
    const s = pres.addSlide();
    s.background = { color: C.void };
    s.addImage({ path: IMG.spread, x: 0, y: 0, w: W, h: H, sizing: { type: "cover", w: W, h: H } });
    s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: W, h: H, fill: { color: C.void, transparency: 10 }, line: { type: "none" } });
    brackets(s, pres, C.muted);
    s.addImage({ data: LOGO, x: W / 2 - 0.35, y: 1.0, w: 0.7, h: 0.7 });
    s.addText("Win back the first 31 minutes.", { x: 0.6, y: 1.95, w: 8.8, h: 0.8, fontFace: F.head, bold: true, fontSize: 34, color: C.text, align: "center", margin: 0 });
    s.addText("Firewatch  ·  Detect → Confirm → Respond", { x: 0.6, y: 2.8, w: 8.8, h: 0.4, fontFace: F.body, fontSize: 16, color: C.ember, bold: true, align: "center", margin: 0 });
    s.addText("Paged at T+9 instead of T+31  ·  on scene at T+38 instead of T+62  ·  humans decide every page", {
      x: 0.6, y: 3.35, w: 8.8, h: 0.35, fontFace: F.body, fontSize: 12, color: C.text, align: "center", margin: 0,
    });
    s.addText("github.com/isaksmith/Firewatch", { x: 0.6, y: 4.45, w: 8.8, h: 0.3, fontFace: F.mono, bold: true, fontSize: 11, color: C.muted, align: "center", margin: 0, charSpacing: 1 });
    s.addNotes("(10 s) Firewatch wins back those first 31 minutes, with people deciding every page. Thank you; we'd love your questions.");
  }

  await pres.writeFile({ fileName: `${REPO}/docs/pitch/Firewatch-Pitch.pptx` });
  console.log("written");
})();
