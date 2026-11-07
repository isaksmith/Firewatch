import { router } from 'expo-router';
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { AppState, Platform } from 'react-native';
import { getAlert, ingestCode, ingestText, listAlerts, type IngestResult, type StoredAlert } from './alerts';
import { kvGet, kvSet } from './db';
import { pollFeed } from './feed';
import { installedPacks } from './packs';
import { palettes, type Palette, type ThemeName } from './theme';
import type { PackInfo, Role, Source } from './types';

export type Settings = {
  loaded: boolean;
  onboarded: boolean;
  role: Role;
  server: string;
  phone: string;
  theme: ThemeName;
  simRadio: boolean;
};

export const DEFAULT_SERVER = Platform.OS === 'android' ? 'http://10.0.2.2:8031' : 'http://localhost:8031';

const DEFAULTS: Settings = {
  loaded: false, onboarded: false, role: 'firefighter', server: DEFAULT_SERVER, phone: '', theme: 'dark', simRadio: false,
};

type Ctx = {
  settings: Settings;
  setSetting: <K extends keyof Settings>(k: K, v: Settings[K]) => Promise<void>;
  p: Palette;
  alerts: StoredAlert[];
  packs: PackInfo[];
  last: { at: number; source: Source } | null;
  refresh: () => Promise<void>;
  /** Open text that may contain codes (paste, link, radio). Navigates to the alert when one opens. */
  openText: (text: string, source: Source) => Promise<{ kind: 'opened' | 'none' | 'damaged' | 'no_pack'; pack?: string }>;
  ingest: (code: string, source: Source) => Promise<IngestResult>;
  feedOk: boolean | null;
};

const C = createContext<Ctx | null>(null);
export function useApp(): Ctx {
  const v = useContext(C);
  if (!v) throw new Error('no provider');
  return v;
}

const BOOL_KEYS = ['onboarded', 'simRadio'] as const;

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [settings, setSettings] = useState<Settings>(DEFAULTS);
  const [alerts, setAlerts] = useState<StoredAlert[]>([]);
  const [packs, setPacks] = useState<PackInfo[]>([]);
  const [last, setLast] = useState<Ctx['last']>(null);
  const [feedOk, setFeedOk] = useState<boolean | null>(null);

  const refresh = useCallback(async () => {
    setAlerts(await listAlerts());
    setPacks(await installedPacks());
    const l = await kvGet('lastUpdate');
    setLast(l ? JSON.parse(l) : null);
  }, []);

  useEffect(() => {
    (async () => {
      const s: Settings = { ...DEFAULTS, loaded: true };
      for (const k of Object.keys(DEFAULTS) as (keyof Settings)[]) {
        if (k === 'loaded') continue;
        const v = await kvGet(`s:${k}`);
        if (v == null) continue;
        (s as Record<string, unknown>)[k] = (BOOL_KEYS as readonly string[]).includes(k) ? v === '1' : v;
      }
      setSettings(s);
      await refresh();
    })();
  }, [refresh]);

  const setSetting: Ctx['setSetting'] = useCallback(async (k, v) => {
    setSettings((s) => ({ ...s, [k]: v }));
    await kvSet(`s:${k}`, typeof v === 'boolean' ? (v ? '1' : '0') : String(v));
  }, []);

  const ingest = useCallback(async (code: string, source: Source) => {
    const r = await ingestCode(code, source);
    await refresh();
    return r;
  }, [refresh]);

  const openText: Ctx['openText'] = useCallback(async (text, source) => {
    const res = await ingestText(text, source);
    await refresh();
    if (res.found === 0) return { kind: 'none' };
    const good = res.opened.find((o) => o.ok);
    if (good && good.ok) {
      router.push({ pathname: '/alert/[pack]/[id]', params: { pack: good.alert.pack, id: String(good.alert.id) } });
      return { kind: 'opened' };
    }
    const bad = res.opened[0];
    if (!bad.ok && bad.reason === 'no_pack') return { kind: 'no_pack', pack: bad.pack };
    return { kind: 'damaged' };
  }, [refresh]);

  // Feed: every 60 s in the foreground, backing off after failures. Never blocks the screen.
  const packCodes = useMemo(() => packs.map((x) => x.code).join(','), [packs]);
  useEffect(() => {
    if (!settings.loaded || !settings.onboarded || !packCodes) return;
    let stop = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let fails = 0;
    const tick = async () => {
      if (stop || AppState.currentState !== 'active') return schedule();
      let changed = false;
      let anyFail = false;
      for (const c of packCodes.split(',')) {
        const r = await pollFeed(settings.server, c);
        if (r === 'fail') anyFail = true;
        if (r === 'new') changed = true;
      }
      fails = anyFail ? Math.min(fails + 1, 5) : 0;
      if (!stop) setFeedOk(!anyFail);
      if (changed && !stop) await refresh();
      schedule();
    };
    const schedule = () => {
      if (stop) return;
      timer = setTimeout(tick, 60000 * Math.pow(2, fails));
    };
    timer = setTimeout(tick, 1500);
    const sub = AppState.addEventListener('change', (st) => {
      if (st === 'active') { if (timer) clearTimeout(timer); timer = setTimeout(tick, 500); }
    });
    return () => { stop = true; if (timer) clearTimeout(timer); sub.remove(); };
  }, [settings.loaded, settings.onboarded, settings.server, packCodes, refresh]);

  const value = useMemo<Ctx>(() => ({
    settings, setSetting, p: palettes[settings.theme], alerts, packs, last, refresh, openText, ingest, feedOk,
  }), [settings, setSetting, alerts, packs, last, refresh, openText, ingest, feedOk]);

  return <C.Provider value={value}>{children}</C.Provider>;
}

export { getAlert };
