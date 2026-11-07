import type { RoadKind } from './types';

export type MapLabel = { key: string; text: string; x: number; y: number; kind: RoadKind };

const RANK: Record<RoadKind, number> = { highway: 0, state: 1, county: 2, local: 3, track: 4 };

/** Rough text box: x,y is the baseline start. Width is estimated from the character count. */
function box(l: { text: string; x: number; y: number }, size: number) {
  const w = l.text.length * size * 0.58;
  return { x1: l.x, x2: l.x + w, y1: l.y - size, y2: l.y + size * 0.25 };
}

/** Greedy: highest road kinds first, skip any label whose box touches one already placed. */
export function placeLabels<T extends MapLabel>(labels: T[], size: number): T[] {
  const order = labels.map((l, i) => ({ l, i })).sort((a, b) => RANK[a.l.kind] - RANK[b.l.kind] || a.i - b.i);
  const placed: { l: T; b: ReturnType<typeof box> }[] = [];
  for (const { l } of order) {
    const b = box(l, size);
    if (placed.some((q) => b.x1 < q.b.x2 && b.x2 > q.b.x1 && b.y1 < q.b.y2 && b.y2 > q.b.y1)) continue;
    placed.push({ l, b });
  }
  return placed.map((q) => q.l);
}
