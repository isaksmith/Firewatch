import type { Fw1 } from './codec';
import type { LonLat, Pack } from './types';

const MI_PER_DEG_LAT = 69.0;
export const CONE_HALF_ANGLE = 35;

export type XY = { x: number; y: number };
/** Flat local miles east (x) and north (y) of a reference. Good to a few miles' accuracy over a county. */
export function toXY(lon: number, lat: number, ref: { lat: number; lon: number }): XY {
  return {
    x: (lon - ref.lon) * MI_PER_DEG_LAT * Math.cos((ref.lat * Math.PI) / 180),
    y: (lat - ref.lat) * MI_PER_DEG_LAT,
  };
}

export function distMi(a: XY, b: XY): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Compass bearing in degrees from a to b (0 = north, clockwise). */
export function bearing(a: XY, b: XY): number {
  return (((Math.atan2(b.x - a.x, b.y - a.y) * 180) / Math.PI) + 360) % 360;
}

const POINTS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
export function compass(deg: number): string {
  return POINTS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}
const WORDS = ['north', 'northeast', 'east', 'southeast', 'south', 'southwest', 'west', 'northwest'];
export function compassWord(deg: number): string {
  return WORDS[Math.round((((deg % 360) + 360) % 360) / 45) % 8];
}

export function fmtMi(mi: number): string {
  if (mi < 0.1) return 'under 0.1 mi';
  return mi < 10 ? `${(Math.round(mi * 10) / 10).toString()} mi` : `${Math.round(mi)} mi`;
}

function nearestOnSegment(p: XY, a: XY, b: XY): { pt: XY; d: number } {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2));
  const pt = { x: a.x + t * dx, y: a.y + t * dy };
  return { pt, d: distMi(p, pt) };
}

function segIntersect(a: XY, b: XY, c: XY, d: XY): XY | null {
  const r = { x: b.x - a.x, y: b.y - a.y };
  const s = { x: d.x - c.x, y: d.y - c.y };
  const den = r.x * s.y - r.y * s.x;
  if (Math.abs(den) < 1e-12) return null;
  const t = ((c.x - a.x) * s.y - (c.y - a.y) * s.x) / den;
  const u = ((c.x - a.x) * r.y - (c.y - a.y) * r.x) / den;
  if (t < 0 || t > 1 || u < 0 || u > 1) return null;
  return { x: a.x + t * r.x, y: a.y + t * r.y };
}

export function nearestStation(pt: { lat: number; lon: number }, pack: Pack) {
  const p = toXY(pt.lon, pt.lat, pack.origin);
  let best: { name: string; d: number; bearing: number } | null = null;
  for (const s of pack.stations) {
    const q = toXY(s.lon, s.lat, pack.origin);
    const d = distMi(q, p);
    if (!best || d < best.d) best = { name: s.name, d, bearing: bearing(q, p) };
  }
  return best;
}

/** "11 mi NW of Station 1" */
export function whereFromStation(pt: { lat: number; lon: number }, pack: Pack): string {
  const s = nearestStation(pt, pack);
  if (!s) return 'Location on the map';
  if (s.d < 0.2) return `At ${s.name}`;
  return `${fmtMi(s.d)} ${compass(s.bearing)} of ${s.name}`;
}

/** "Rd K, 0.5 mi S of CR 12" or "On Rd K" or null with no roads. */
export function nearestRoadText(pt: { lat: number; lon: number }, pack: Pack): string | null {
  const p = toXY(pt.lon, pt.lat, pack.origin);
  let best: { road: Pack['roads'][number]; d: number; a: XY; b: XY; pt: XY } | null = null;
  for (const road of pack.roads) {
    if (!road.name) continue;
    const xy = road.line.map((q: LonLat) => toXY(q[0], q[1], pack.origin));
    for (let i = 0; i + 1 < xy.length; i++) {
      const n = nearestOnSegment(p, xy[i], xy[i + 1]);
      if (!best || n.d < best.d) best = { road, d: n.d, a: xy[i], b: xy[i + 1], pt: n.pt };
    }
  }
  if (!best || !best.road.name) return null;
  // Closest crossing of a differently named road along the chosen road.
  const name = best.road.name;
  const mine = best.road.line.map((q: LonLat) => toXY(q[0], q[1], pack.origin));
  let cross: { name: string; pt: XY; d: number } | null = null;
  for (const other of pack.roads) {
    if (!other.name || other.name === name) continue;
    const o = other.line.map((q: LonLat) => toXY(q[0], q[1], pack.origin));
    for (let i = 0; i + 1 < mine.length; i++) {
      for (let j = 0; j + 1 < o.length; j++) {
        const x = segIntersect(mine[i], mine[i + 1], o[j], o[j + 1]);
        if (x) {
          const d = distMi(x, best.pt);
          if (!cross || d < cross.d) cross = { name: other.name, pt: x, d };
        }
      }
    }
  }
  if (!cross) return best.d < 0.3 ? `On ${name}` : `${fmtMi(best.d)} from ${name}`;
  const along = distMi(best.pt, cross.pt);
  if (along < 0.15) return `${name} at ${cross.name}`;
  return `${name}, ${fmtMi(along)} ${compass(bearing(cross.pt, best.pt))} of ${cross.name}`;
}

export type Exposure = { name: string; kind: string; minutes: number; miles: number; lon: number; lat: number };
export type Spread = {
  speedWorst: number;
  /** Cone tip first, then arc points, as lon/lat. */
  polygon: LonLat[];
  exposed: Exposure[];
  otherBuildings: number;
  headingDeg: number;
};

/** Spread cone at the speed in the code (the server's worst-case spread model). Returns null when direction or speed is unknown or zero. */
export function spreadCone(f: Pick<Fw1, 'lat' | 'lon' | 'towardDeg' | 'mph'>, pack: Pack): Spread | null {
  if (f.towardDeg == null || f.mph == null || f.mph <= 0) return null;
  const heading = f.towardDeg;
  const speed = f.mph;
  const o = { lat: f.lat, lon: f.lon };
  const reachMi = speed * 2; // two hours at the worst-case speed
  const cosLat = Math.cos((f.lat * Math.PI) / 180);
  const toLL = (xy: XY): LonLat => [f.lon + xy.x / (MI_PER_DEG_LAT * cosLat), f.lat + xy.y / MI_PER_DEG_LAT];
  const poly: LonLat[] = [[f.lon, f.lat]];
  for (let a = -CONE_HALF_ANGLE; a <= CONE_HALF_ANGLE; a += CONE_HALF_ANGLE / 5) {
    const r = ((heading + a) * Math.PI) / 180;
    poly.push(toLL({ x: Math.sin(r) * reachMi, y: Math.cos(r) * reachMi }));
  }
  const inCone = (lon: number, lat: number) => {
    const q = toXY(lon, lat, o);
    const d = Math.hypot(q.x, q.y);
    if (d > reachMi || d < 0.01) return d < 0.01 ? { d: 0 } : null;
    const diff = Math.abs(((bearing({ x: 0, y: 0 }, q) - heading + 540) % 360) - 180);
    return diff <= CONE_HALF_ANGLE ? { d } : null;
  };
  const exposed: Exposure[] = [];
  const seen = new Set<string>();
  const add = (name: string, kind: string, lon: number, lat: number) => {
    const hit = inCone(lon, lat);
    if (!hit || hit.d < 0.25 || seen.has(name)) return;
    seen.add(name);
    exposed.push({ name, kind, lon, lat, miles: hit.d, minutes: Math.max(1, Math.round((hit.d / speed) * 60)) });
  };
  for (const p of pack.places) add(p.name, p.kind, p.lon, p.lat);
  for (const t of pack.towns) add(t.name, 'town', t.lon, t.lat);
  for (const b of pack.buildings) if (b.name) add(b.name, b.kind, b.lon, b.lat);
  exposed.sort((a, b) => a.minutes - b.minutes);
  let other = 0;
  for (const b of pack.buildings) if (!b.name && inCone(b.lon, b.lat)) other++;
  return { speedWorst: speed, polygon: poly, exposed, otherBuildings: other, headingDeg: heading };
}

export function fmtMinutes(m: number): string {
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const r = m % 60;
  return r === 0 ? `${h} hr` : `${h} hr ${r} min`;
}

export function ageText(ms: number, now: number): string {
  const m = Math.max(0, Math.round((now - ms) / 60000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} hr ago`;
  return dateText(ms);
}

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** "Tue 17 Mar, 2:05 PM" in the phone's local time. Used once an alert is over a day old. */
export function dateText(ms: number): string {
  const d = new Date(ms);
  const h = d.getHours();
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}, ${h % 12 || 12}:${mm} ${h < 12 ? 'AM' : 'PM'}`;
}

/** One plain sentence block for the alert screen. */
export function summarize(f: Fw1, pack: Pack): string {
  const parts = [`Fire ${whereFromStation(f, pack)}.`];
  const sp = spreadCone(f, pack);
  if (f.towardDeg != null) parts.push(`Moving ${compassWord(f.towardDeg)}.`);
  if (sp && sp.exposed[0]) parts.push(`${sp.exposed[0].name}: as little as ${fmtMinutes(sp.exposed[0].minutes)}.`);
  return parts.join(' ');
}
