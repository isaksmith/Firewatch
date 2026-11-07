import { router } from 'expo-router';
import React, { useEffect, useMemo, useState } from 'react';
import { ScrollView, View } from 'react-native';
import { Body, Button, Choice, Field, H1, Screen } from '@/components/ui';
import { DEFAULT_SERVER, useApp } from '@/lib/store';
import { BUNDLED_INFOS, PackDamaged, PackRefused, downloadPack, fetchPackIndex, fmtBytes, installBundled } from '@/lib/packs';
import type { PackInfo, Role } from '@/lib/types';

type Step = 'state' | 'area' | 'role' | 'server';

export default function Setup() {
  const { setSetting, settings, refresh } = useApp();
  const [step, setStep] = useState<Step>('state');
  const [index, setIndex] = useState<PackInfo[]>(BUNDLED_INFOS);
  const [online, setOnline] = useState<boolean | null>(null);
  const [state, setState] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [whole, setWhole] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [role, setRole] = useState<Role>('firefighter');
  const [server, setServer] = useState(settings.server || DEFAULT_SERVER);

  useEffect(() => {
    let live = true;
    fetchPackIndex(settings.server || DEFAULT_SERVER)
      .then((l) => { if (live && l.length) { setIndex(l); setOnline(true); } })
      .catch(() => { if (live) setOnline(false); });
    return () => { live = false; };
  }, [settings.server]);

  const states = useMemo(() => [...new Set(index.map((i) => i.state))].sort(), [index]);
  const inState = useMemo(() => index.filter((i) => i.state === state), [index, state]);
  const chosen = useMemo(() => (whole ? inState : inState.filter((i) => picked.has(i.code))), [whole, inState, picked]);
  const total = chosen.reduce((n, i) => n + i.bytes, 0);

  const toggle = (code: string) => {
    setWhole(false);
    setPicked((s) => { const n = new Set(s); if (n.has(code)) n.delete(code); else n.add(code); return n; });
  };

  const download = async () => {
    setError(null);
    const bundled = new Set(BUNDLED_INFOS.map((b) => b.code));
    let n = 0;
    try {
      for (const info of chosen) {
        setBusy(`Getting ${info.name} (${++n} of ${chosen.length})`);
        if (online && (info.sha256 || !bundled.has(info.code))) await downloadPack(settings.server || DEFAULT_SERVER, info);
        else if (bundled.has(info.code)) await installBundled(info.code);
        else throw new Error('offline');
      }
      await refresh();
      setBusy(null);
      setStep('role');
    } catch (e) {
      setBusy(null);
      // The demo area ships inside the app, so it can always be used.
      for (const c of chosen) if (bundled.has(c.code)) await installBundled(c.code);
      await refresh();
      setError(
        e instanceof PackRefused
          ? e.message
          : e instanceof PackDamaged
            ? 'That download was damaged. Tap the button to try again.'
            : 'Could not reach the server. Check the server address in Settings.',
      );
    }
  };

  const finish = async () => {
    await setSetting('role', role);
    await setSetting('server', server.trim().replace(/\/+$/, ''));
    await setSetting('onboarded', true);
    router.replace('/');
  };

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }}>
        {step === 'state' && (
          <>
            <H1>Pick your area</H1>
            <Body>Which state are you in?</Body>
            {online === false && <Body muted>No signal. Showing the area that comes with the app.</Body>}
            {states.map((s) => (
              <Button key={s} label={s} tone="quiet" onPress={() => { setState(s); setStep('area'); }} />
            ))}
          </>
        )}
        {step === 'area' && (
          <>
            <H1>Which counties?</H1>
            <Body muted>Maps are saved on your phone, so they work with no signal.</Body>
            <Choice label="Whole state" sub={`${inState.length} ${inState.length === 1 ? 'area' : 'areas'}`} selected={whole} onPress={() => setWhole((w) => !w)} />
            {inState.map((i) => (
              <Choice key={i.code} label={i.name} sub={`${i.counties.join(', ')}  ·  ${fmtBytes(i.bytes)}`} selected={whole || picked.has(i.code)} onPress={() => toggle(i.code)} />
            ))}
            <Body>Best on Wi-Fi at the station.</Body>
            {error && <Body style={{ fontFamily: 'IBMPlexSans_700Bold' }}>{error}</Body>}
            <Button
              label={busy ?? (chosen.length ? `Download ${fmtBytes(total)}` : 'Pick at least one')}
              disabled={!chosen.length || !!busy}
              onPress={download}
            />
            <Button label="Back" tone="quiet" onPress={() => setStep('state')} />
          </>
        )}
        {step === 'role' && (
          <>
            <H1>Who are you?</H1>
            <Choice label="Fire chief" selected={role === 'chief'} onPress={() => setRole('chief')} />
            <Choice label="Firefighter" selected={role === 'firefighter'} onPress={() => setRole('firefighter')} />
            <Button label="Next" onPress={() => setStep('server')} />
          </>
        )}
        {step === 'server' && (
          <>
            <H1>Where do alerts come from?</H1>
            <Body muted>Dispatch can give you this address. You can leave it as it is for now.</Body>
            <Field label="Server address" value={server} onChangeText={setServer} keyboardType="url" />
            <View style={{ height: 8 }} />
            <Button label="Done" onPress={finish} />
          </>
        )}
      </ScrollView>
    </Screen>
  );
}
