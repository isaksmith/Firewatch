import { router } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { Text, View } from 'react-native';
import { Body, Button } from '@/components/ui';
import { registerSlot } from '@/lib/extensions';
import { useApp } from '@/lib/store';
import { autoReconnect, loadSaved, reportSmoke, setOnAlertsChanged } from './controller';
import { useRadio } from './state';

/** Mounted once at the root: reconnects the saved radio and refreshes the list when a radio alert lands. */
function MeshHost() {
  const { refresh, settings } = useApp();
  useEffect(() => {
    setOnAlertsChanged(() => { void refresh(); });
  }, [refresh]);
  useEffect(() => {
    if (!settings.loaded || !settings.onboarded) return;
    void loadSaved().then(autoReconnect);
  }, [settings.loaded, settings.onboarded]);
  return null;
}

function SmokeButton() {
  const r = useRadio();
  const { p } = useApp();
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (r.status !== 'connected') return null;
  const go = async () => {
    setBusy(true);
    setMsg(null);
    const res = await reportSmoke();
    setBusy(false);
    setMsg(res.ok ? 'Sent over radio' : res.why);
  };
  return (
    <View style={{ gap: 6 }}>
      <Button label={busy ? 'Sending' : 'Report smoke here'} tone="fire" disabled={busy} onPress={go} />
      {msg && <Text style={{ color: p.text, fontSize: 18, fontFamily: 'IBMPlexSans_700Bold' }}>{msg}</Text>}
    </View>
  );
}

function RadioRow() {
  const r = useRadio();
  const label = r.status === 'connected' ? `Radio: ${r.name ?? 'connected'}` : 'Radio: not connected';
  return (
    <View style={{ gap: 6 }}>
      <Button label={label} tone="quiet" onPress={() => router.push('/radio')} />
      {r.status === 'connected' && r.battery != null && <Body muted>Radio battery {r.battery}%</Body>}
    </View>
  );
}

registerSlot('root', MeshHost);
registerSlot('home', SmokeButton);
registerSlot('settings', RadioRow);
