import { ageText } from '../src/lib/geo';
import { placeLabels, type MapLabel } from '../src/lib/labels';

describe('ageText', () => {
  const now = new Date(2026, 2, 18, 14, 5).getTime();
  const H = 3600e3;
  it('keeps plain ages under 24 hours', () => {
    expect(ageText(now - 12 * 60e3, now)).toBe('12 min ago');
    expect(ageText(now - (23 * H + 59 * 60e3), now)).toBe('23 hr ago');
  });
  it('shows a date and time past 24 hours', () => {
    const t = new Date(2026, 2, 17, 14, 5).getTime();
    expect(ageText(t - 60e3, now)).toBe('Tue 17 Mar, 2:04 PM');
    expect(ageText(now - (24 * H + 60e3), now)).toBe('Tue 17 Mar, 2:04 PM');
    expect(ageText(now - 234 * 24 * H, now)).not.toMatch(/ago/);
  });
});

describe('placeLabels', () => {
  const L = (key: string, x: number, y: number, kind: MapLabel['kind']): MapLabel => ({ key, text: 'Road 3', x, y, kind });
  it('drops overlapping labels and keeps the higher road kind', () => {
    const out = placeLabels([L('a', 10, 50, 'county'), L('b', 20, 52, 'highway'), L('c', 10, 200, 'county')], 11);
    expect(out.map((l) => l.key).sort()).toEqual(['b', 'c']);
  });
  it('keeps labels that do not touch', () => {
    expect(placeLabels([L('a', 0, 20, 'county'), L('b', 200, 20, 'county')], 11)).toHaveLength(2);
  });
});
