import vectors from '../../docs/mobile/codec-vectors.json';
import { decodeFw1 } from '../src/lib/codec';
import { nearestRoadText, spreadCone, summarize, toXY } from '../src/lib/geo';
import type { Pack } from '../src/lib/types';

const origin = vectors.origin;
const pack = {
  format: 'fwpack/1', code: 'cwc', name: 'T', state: 'KS', counties: [], version: 'x', origin, bbox: [0, 0, 0, 0],
  boundary: { type: 'Polygon', coordinates: [[]] },
  roads: [
    { name: 'Rd K', kind: 'county', line: [[-99.4681, 37.3], [-99.4681, 37.5]] },
    { name: 'CR 12', kind: 'county', line: [[-99.6, 37.3735], [-99.3, 37.3735]] },
  ],
  towns: [], buildings: [{ lon: -99.4681, lat: 37.4, kind: 'home' }], power_lines: [],
  stations: [{ name: 'Station 1', lon: origin.lon, lat: origin.lat }],
  places: [{ id: 'p1', name: 'Miller house', kind: 'home', lon: -99.4681, lat: 37.425 }],
} as unknown as Pack;

it('names the nearest road against a crossing road', () => {
  const f = decodeFw1(vectors.vectors[1].code, origin);
  expect(nearestRoadText(f, pack)).toMatch(/^Rd K, .* N of CR 12$/);
});

it('builds a worst-case cone and arrival times', () => {
  const f = decodeFw1(vectors.vectors[1].code, origin);
  const s = spreadCone(f, pack)!;
  expect(s.speedWorst).toBeCloseTo(3);
  expect(s.exposed[0].name).toBe('Miller house');
  const miles = toXY(pack.places[0].lon, pack.places[0].lat, f).y;
  expect(s.exposed[0].minutes).toBe(Math.round((miles / 3) * 60));
  expect(summarize(f, pack)).toMatch(/^Fire .* NW of Station 1\. Moving north\. Miller house: as little as \d+ min\.$/);
});

it('has no cone without direction and speed', () => {
  expect(spreadCone(decodeFw1(vectors.vectors[0].code, origin), pack)).toBeNull();
});
