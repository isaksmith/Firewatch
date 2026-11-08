import { router } from 'expo-router';
import React, { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView } from 'react-native';
import { Body, Button, Choice, Field, H1, Screen } from '@/components/ui';
import { slotItems } from '@/lib/extensions';
import { fmtBytes } from '@/lib/packs';
import { useApp } from '@/lib/store';

export default function Settings() {
  const { settings, setSetting, packs, p } = useApp();
  const [taps, setTaps] = useState(0);
  const [server, setServer] = useState(settings.server);
  const [saved, setSaved] = useState(false);
  const serverRef = useRef(server);
  const typed = useRef(false);
  useEffect(() => { if (!typed.current) setServer(settings.server); }, [settings.server]);
  const saveServer = () => {
    if (!typed.current) return;
    typed.current = false;
    const v = serverRef.current.trim();
    setServer(v);
    if (v !== settings.server) { void setSetting('server', v); setSaved(true); }
  };
  useEffect(() => () => { if (typed.current) void setSetting('server', serverRef.current.trim()); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const Extras = slotItems('settings');
  void p;
  return (
    <Screen>
      <ScrollView contentContainerStyle={{ padding: 20, gap: 16 }} keyboardShouldPersistTaps="handled">
        <H1>Settings</H1>
        <Field label="Dispatch phone number" value={settings.phone} onChangeText={(v) => setSetting('phone', v)} keyboardType="phone-pad" placeholder="Example: 620 555 0100" />
        <Choice label="Daylight mode" sub="Light screen for bright sun" selected={settings.theme === 'day'} onPress={() => setSetting('theme', settings.theme === 'day' ? 'dark' : 'day')} />
        <Choice label="I am a fire chief" selected={settings.role === 'chief'} onPress={() => setSetting('role', settings.role === 'chief' ? 'firefighter' : 'chief')} />
        <Field label="Server address" value={server} onChangeText={(v) => { typed.current = true; serverRef.current = v; setSaved(false); setServer(v); }} onBlur={saveServer} onSubmitEditing={saveServer} returnKeyType="done" keyboardType="url" />
        {saved && <Body muted size={16}>Saved</Body>}
        {Extras.map((E, i) => <E key={i} />)}
        <Body size={20} style={{ fontFamily: 'IBMPlexSans_700Bold' }}>Maps on this phone</Body>
        {packs.length === 0 && <Body muted>None yet.</Body>}
        {packs.map((k) => <Body key={k.code}>{k.name} ({fmtBytes(k.bytes)})</Body>)}
        <Button label="Change area" tone="quiet" onPress={() => router.push('/setup')} />
        <Button label="Back" onPress={() => router.back()} />
        <Pressable accessibilityRole="button" accessibilityLabel="Version" onPress={() => { const n = taps + 1; setTaps(n); if (n >= 5) { setTaps(0); void setSetting('simRadio', !settings.simRadio); } }} style={{ minHeight: 56, justifyContent: 'center' }}>
          <Body muted size={14} style={{ textAlign: 'center' }}>Firewatch 1.0{settings.simRadio ? '  (test tools on)' : ''}</Body>
        </Pressable>
      </ScrollView>
    </Screen>
  );
}
