import React, { memo, useCallback, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { GestureDetector, useSimultaneousGestures, usePanGesture, usePinchGesture } from 'react-native-gesture-handler';
import Svg, { Circle, G, Polygon, Polyline, Rect, Text as SvgText } from 'react-native-svg';
import { toXY, type Spread } from '@/lib/geo';
import { font, type Palette } from '@/lib/theme';
import { placeLabels } from '@/lib/labels';
import type { Pack, RoadKind } from '@/lib/types';

type Fire = { lat: number; lon: number; level: 'escalate' | 'investigate' | 'monitor'; label?: string };

const ROAD: Record<RoadKind, { w: number; dash?: string }> = {
  highway: { w: 4 },
  state: { w: 3 },
  county: { w: 2 },
  local: { w: 1.2 },
  track: { w: 1, dash: '3,3' },
};

type Layer = {
  pack: Pack; fire: Fire; spread: Spread | null; p: Palette; ppm: number; tx: number; ty: number; w: number; h: number;
};

// The still picture. It only redraws when a gesture ends, so panning stays smooth.
const StaticLayer = memo(function StaticLayer({ pack, fire, spread, p, ppm, tx, ty, w, h }: Layer) {
  const o = { lat: fire.lat, lon: fire.lon };
  const pt = (lon: number, lat: number) => {
    const q = toXY(lon, lat, o);
    return { x: w / 2 + tx + q.x * ppm, y: h / 2 + ty - q.y * ppm };
  };
  const pts = (line: [number, number][]) => line.map((c) => { const a = pt(c[0], c[1]); return `${a.x.toFixed(1)},${a.y.toFixed(1)}`; }).join(' ');
  const labelRoads = useMemo(() => {
    const seen = new Set<string>();
    return pack.roads.filter((r) => {
      if (!r.name || (r.kind !== 'highway' && r.kind !== 'state' && r.kind !== 'county') || seen.has(r.name)) return false;
      seen.add(r.name);
      return true;
    });
  }, [pack]);
  const color = fire.level === 'escalate' ? p.escalate : p.investigate;
  const margin = 40;
  const visible = (a: { x: number; y: number }) => a.x > -margin && a.x < w + margin && a.y > -margin && a.y < h + margin;
  const placedLabels = placeLabels(labelRoads.map((r, i) => {
    const mid = r.line[Math.floor(r.line.length / 2)];
    const a = pt(mid[0], mid[1]);
    return { key: `rl${i}`, text: r.name ?? '', x: a.x + 4, y: a.y - 3, kind: r.kind, onScreen: visible(a) };
  }).filter((l) => l.onScreen), 11);
  return (
    <Svg width={w} height={h}>
      <Rect x={0} y={0} width={w} height={h} fill={p.mapGrass} />
      <Polygon points={pts(pack.boundary.coordinates[0])} fill="none" stroke={p.muted} strokeWidth={1.5} strokeDasharray="8,5" />
      {pack.roads.map((r, i) => (
        <Polyline key={`r${i}`} points={pts(r.line)} fill="none" stroke={p.mapRoad} strokeWidth={ROAD[r.kind].w} strokeDasharray={ROAD[r.kind].dash} />
      ))}
      {placedLabels.map((l) => (
        <SvgText key={l.key} x={l.x} y={l.y} fontSize={11} fill={p.muted} fontFamily={font.medium}>{l.text}</SvgText>
      ))}
      {pack.power_lines.map((l, i) => (
        <Polyline key={`pl${i}`} points={pts(l.line)} fill="none" stroke={p.mapLine} strokeWidth={2} strokeDasharray="10,4" />
      ))}
      {spread && <Polygon points={pts(spread.polygon)} fill={color} fillOpacity={0.28} stroke={color} strokeWidth={2} />}
      {pack.buildings.map((b, i) => {
        const a = pt(b.lon, b.lat);
        return visible(a) ? <Rect key={`b${i}`} x={a.x - 2.5} y={a.y - 2.5} width={5} height={5} fill={p.mapBuilding} opacity={b.kind === 'home' ? 1 : 0.55} /> : null;
      })}
      {pack.towns.map((t, i) => {
        const a = pt(t.lon, t.lat);
        return visible(a) ? <SvgText key={`t${i}`} x={a.x + 8} y={a.y + 4} fontSize={14} fontWeight="700" fill={p.text} fontFamily={font.bold}>{t.name}</SvgText> : null;
      })}
      {pack.stations.map((s, i) => {
        const a = pt(s.lon, s.lat);
        return visible(a) ? (
          <G key={`s${i}`}>
            <Rect x={a.x - 7} y={a.y - 7} width={14} height={14} fill={p.ok} stroke={p.bg} strokeWidth={2} />
            <SvgText x={a.x + 11} y={a.y + 4} fontSize={13} fontWeight="700" fill={p.text} fontFamily={font.bold}>{s.name}</SvgText>
          </G>
        ) : null;
      })}
      {spread?.exposed.slice(0, 6).map((e, i) => {
        const a = pt(e.lon, e.lat);
        return (
          <G key={`e${i}`}>
            <Circle cx={a.x} cy={a.y} r={7} fill="none" stroke={color} strokeWidth={3} />
            <SvgText x={a.x + 11} y={a.y + 4} fontSize={13} fontWeight="700" fill={p.text} fontFamily={font.bold}>{e.name}</SvgText>
          </G>
        );
      })}
      <Circle cx={w / 2 + tx} cy={h / 2 + ty} r={16} fill={color} fillOpacity={0.3} />
      <Circle cx={w / 2 + tx} cy={h / 2 + ty} r={8} fill={color} stroke={p.bg} strokeWidth={2} />
    </Svg>
  );
});


export function FireMap({ pack, fire, spread, p, height = 340, width }: {
  pack: Pack; fire: Fire; spread: Spread | null; p: Palette; height?: number; width: number;
}) {
  const startPpm = useMemo(() => {
    const miles = spread ? Math.min(Math.max(spread.speedWorst * 1.2, 4), 12) : 6;
    return width / (miles * 2);
  }, [spread, width]);
  const [m, setM] = useState({ ppm: startPpm, tx: 0, ty: 0, ls: 1, lx: 0, ly: 0 });
  const clampPpm = (v: number) => Math.min(Math.max(v, 3), 600);

  const commit = useCallback(() => {
    setM((c) => ({ ppm: clampPpm(c.ppm * c.ls), tx: c.ls * c.tx + c.lx, ty: c.ls * c.ty + c.ly, ls: 1, lx: 0, ly: 0 }));
  }, []);

  const pan = usePanGesture({
    runOnJS: true,
    onUpdate: (e) => setM((c) => ({ ...c, lx: c.lx + e.changeX, ly: c.ly + e.changeY })),
    onFinalize: commit,
  });
  const pinch = usePinchGesture({
    runOnJS: true,
    onUpdate: (e) => setM((c) => ({ ...c, ls: Math.min(Math.max(c.ls * e.scaleChange, 0.3), 8) })),
    onFinalize: commit,
  });
  const gesture = useSimultaneousGestures(pan, pinch);

  const zoom = (k: number) => setM((c) => ({ ...c, ppm: clampPpm(c.ppm * k), tx: c.tx * k, ty: c.ty * k }));
  const reset = () => setM({ ppm: startPpm, tx: 0, ty: 0, ls: 1, lx: 0, ly: 0 });
  const view = m;
  const live = { s: m.ls, x: m.lx, y: m.ly };

  return (
    <View style={{ width, height, overflow: 'hidden', backgroundColor: p.mapGrass, borderColor: p.line, borderWidth: 1 }}>
      <GestureDetector gesture={gesture}>
        <View style={{ width, height, transform: [{ translateX: live.x }, { translateY: live.y }, { scale: live.s }] }}>
          <StaticLayer pack={pack} fire={fire} spread={spread} p={p} ppm={view.ppm} tx={view.tx} ty={view.ty} w={width} h={height} />
        </View>
      </GestureDetector>
      <View style={styles.btns} pointerEvents="box-none">
        <MapBtn p={p} label="+" onPress={() => zoom(1.6)} a11y="Zoom in" />
        <MapBtn p={p} label="-" onPress={() => zoom(1 / 1.6)} a11y="Zoom out" />
        <MapBtn p={p} label="Fire" onPress={reset} a11y="Back to the fire" small />
      </View>
    </View>
  );
}

function MapBtn({ p, label, onPress, a11y, small }: { p: Palette; label: string; onPress: () => void; a11y: string; small?: boolean }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={a11y}
      onPress={onPress}
      style={({ pressed }) => [styles.btn, { backgroundColor: p.panel, borderColor: p.text, opacity: pressed ? 0.6 : 1 }]}
    >
      <Text style={{ color: p.text, fontFamily: font.bold, fontSize: small ? 16 : 28 }}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btns: { position: 'absolute', right: 8, top: 8, gap: 8 },
  btn: { width: 56, height: 56, borderWidth: 2, alignItems: 'center', justifyContent: 'center', borderRadius: 8 },
});
