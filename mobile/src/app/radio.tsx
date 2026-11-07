import { router } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';
import { Body, Button, Field, H1, Screen } from '@/components/ui';
import { ageText } from '@/lib/geo';
import { useApp } from '@/lib/store';
import { font } from '@/lib/theme';
import { canUndoForget, connectTo, forget, loadSaved, scanAndConnect, setChannel, startSim, undoForget, disconnect } from '@/transports/mesh/controller';
import { useRadio } from '@/transports/mesh/state';

export default function RadioScreen() {
  const r = useRadio();
  const { p, settings } = useApp();
  const [now, setNow] = useState(() => Date.now());
  const [ch, setCh] = useState(String(r.channel));
  useEffect(() => { void loadSaved().then(() => undefined); }, []);
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 20000); return () => clearInterval(t); }, []);
  const showSim = __DEV__ || settings.simRadio;
  const busy = r.status === 'searching' || r.status === 'connecting';

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }} keyboardShouldPersistTaps="handled">
        <H1>Radio</H1>
        {r.status === 'connected' ? (
          <>
            <Body size={22} style={{ fontFamily: font.bold }}>{r.name}</Body>
            <Body>{r.kind === 'sim' ? 'Test radio, sending example alerts.' : 'Connected. Alerts arrive even with no signal.'}</Body>
            {r.battery != null && <Body>Radio battery {r.battery}%</Body>}
            <Button label="Forget this radio" tone="quiet" onPress={forget} />
          </>
        ) : (
          <>
            <Body>Connect your Meshtastic radio. Fire alerts reach you with no cell signal.</Body>
            {r.note && <Body style={{ fontFamily: font.bold }}>{r.note}</Body>}
            {r.found.length > 1 && r.found.map((f) => <Button key={f.id} label={f.name} tone="quiet" onPress={() => connectTo(f.id, f.name)} />)}
            <Button label={r.status === 'searching' ? 'Looking for your radio' : r.status === 'connecting' ? 'Connecting' : r.savedName ? `Connect to ${r.savedName}` : 'Connect'} disabled={busy} onPress={scanAndConnect} />
            {canUndoForget() && r.note === 'Radio forgotten.' && <Button label="Undo" tone="quiet" onPress={undoForget} />}
          </>
        )}
        <Field label="Radio channel number (ask your admin; usually 0)" keyboardType="number-pad" value={ch} onChangeText={(v) => { setCh(v); void setChannel(Number(v)); }} />
        <Body size={20} style={{ fontFamily: font.bold }}>Radio messages</Body>
        {r.messages.length === 0 && <Body muted>Nothing yet. Messages from your crew show up here.</Body>}
        {r.messages.map((m, i) => (
          <View key={i} style={{ borderLeftWidth: 4, borderLeftColor: m.from === 'you' ? p.ok : p.line, paddingLeft: 10 }}>
            <Text style={{ color: p.text, fontFamily: font.regular, fontSize: 18 }}>{m.text}</Text>
            <Text style={{ color: p.muted, fontFamily: font.regular, fontSize: 14 }}>{m.from === 'you' ? 'You' : m.from}, {ageText(m.at, now)}</Text>
          </View>
        ))}
        {showSim && (
          <Button label={r.kind === 'sim' ? 'Stop test radio' : 'Simulated radio'} tone="quiet" onPress={() => (r.kind === 'sim' ? disconnect() : startSim())} />
        )}
        <Button label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
      </ScrollView>
    </Screen>
  );
}
