import * as Clipboard from 'expo-clipboard';
import { Redirect, router } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { FlatList, Pressable, Text, View } from 'react-native';
import { Body, Button, H1, Screen } from '@/components/ui';
import type { StoredAlert } from '@/lib/alerts';
import { findCodes, hasSig } from '@/lib/codec';
import { slotItems } from '@/lib/extensions';
import { ageText, whereFromStation } from '@/lib/geo';
import { loadPack } from '@/lib/packs';
import { useApp } from '@/lib/store';
import { cap, levelColorKey, plainWords, sourceWords } from '@/lib/text';
import { font } from '@/lib/theme';
import type { Pack } from '@/lib/types';

function useNow() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000);
    return () => clearInterval(t);
  }, []);
  return now;
}

function Row({ a, pack, now }: { a: StoredAlert; pack: Pack | null; now: number }) {
  const { p } = useApp();
  const color = p[levelColorKey(a)];
  const where = pack ? cap(whereFromStation(a, pack)) : a.pack;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={`${plainWords(a)}. ${where}. ${ageText(a.time, now)}${a.verified ? '' : '. Not confirmed by dispatch'}`}
      onPress={() => router.push({ pathname: '/alert/[pack]/[id]', params: { pack: a.pack, id: String(a.id) } })}
      style={({ pressed }) => ({ flexDirection: 'row', backgroundColor: p.panel, borderColor: p.line, borderWidth: 1, borderRadius: 10, minHeight: 88, opacity: pressed ? 0.7 : 1, overflow: 'hidden' })}
    >
      <View style={{ width: 14, backgroundColor: color }} />
      <View style={{ flex: 1, padding: 14, gap: 2 }}>
        <Text style={{ color: p.text, fontFamily: font.bold, fontSize: 21 }}>{plainWords(a)}</Text>
        <Text style={{ color: p.text, fontFamily: font.regular, fontSize: 18 }}>{where}</Text>
        <Text style={{ color: p.muted, fontFamily: font.regular, fontSize: 16 }}>{cap(ageText(a.time, now))}</Text>
        {!a.verified && <Text style={{ color: p.investigate, fontFamily: font.bold, fontSize: 16 }}>Not confirmed by dispatch</Text>}
      </View>
    </Pressable>
  );
}

export default function Home() {
  const { settings, alerts, last, openText, p } = useApp();
  const now = useNow();
  const [packs, setPacks] = useState<Record<string, Pack | null>>({});
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const m: Record<string, Pack | null> = {};
      for (const code of new Set(alerts.map((a) => a.pack))) m[code] = await loadPack(code);
      setPacks(m);
    })();
  }, [alerts]);

  if (settings.loaded && !settings.onboarded) return <Redirect href="/setup" />;

  const paste = async () => {
    setMsg(null);
    const text = await Clipboard.getStringAsync();
    const r = await openText(text, 'paste');
    if (r.kind === 'none') setMsg('No alert code found. Copy the whole text message, then tap Paste alert.');
    else if (r.kind === 'damaged') {
      // A signed code that was refused may be forged as well as damaged, so say both.
      setMsg(findCodes(text).some(hasSig)
        ? 'This alert code is damaged or did not come from dispatch. Ask dispatch to resend.'
        : 'This alert code is damaged. Ask dispatch to resend.');
    }
    else if (r.kind === 'no_pack') setMsg(`This alert is for an area you have not downloaded (${r.pack}). Open Settings to add it.`);
  };

  const updateLine = last
    ? `Last update ${ageText(last.at, now)}, by ${sourceWords(last.source)}`
    : 'No updates yet';
  const Extras = slotItems('home');

  return (
    <Screen>
      <View style={{ flex: 1, paddingHorizontal: 20, paddingTop: 12, gap: 12 }}>
        <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <H1>Fires near you</H1>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Settings"
            onPress={() => router.push('/settings')}
            style={{ minHeight: 56, minWidth: 56, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 8 }}
          >
            <Text style={{ color: p.text, fontFamily: font.bold, fontSize: 18, textDecorationLine: 'underline' }}>Settings</Text>
          </Pressable>
        </View>
        <Body muted size={16}>{updateLine}</Body>
        <FlatList
          style={{ flex: 1 }}
          data={alerts}
          keyExtractor={(a) => `${a.pack}-${a.id}`}
          contentContainerStyle={{ gap: 10, paddingBottom: 8 }}
          renderItem={({ item }) => <Row a={item} pack={packs[item.pack] ?? null} now={now} />}
          ListEmptyComponent={
            <View style={{ paddingVertical: 32, gap: 8 }}>
              <Body size={22}>No fires reported.</Body>
              <Body muted>When dispatch sends an alert it shows up here. You can also copy an alert text and tap Paste alert.</Body>
            </View>
          }
        />
        {msg && (
          <Pressable onPress={() => setMsg(null)} accessibilityRole="button" accessibilityLabel="Dismiss message" style={{ borderColor: p.investigate, borderWidth: 2, borderRadius: 10, padding: 14, minHeight: 56 }}>
            <Body>{msg}</Body>
            <Body muted size={15}>Tap to close</Body>
          </Pressable>
        )}
        <View style={{ gap: 10, paddingBottom: 8 }}>
          {Extras.map((E, i) => <E key={i} />)}
          <Button label="Community board" tone="quiet" sub="See and share what neighbors see" onPress={() => router.push('/board')} />
          <Button label="Paste alert" onPress={paste} sub="Copy the text message first" />
        </View>
      </View>
    </Screen>
  );
}
