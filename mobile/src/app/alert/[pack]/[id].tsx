import { router, useLocalSearchParams } from 'expo-router';
import * as Linking from 'expo-linking';
import React, { useEffect, useMemo, useState } from 'react';
import { ScrollView, Text, useWindowDimensions, View } from 'react-native';
import { Body, Button, H1, Screen } from '@/components/ui';
import { getAlert, type StoredAlert } from '@/lib/alerts';
import { FireMap } from '@/components/MapView';
import { ageText, compassWord, fmtMinutes, nearestRoadText, spreadCone, summarize, whereFromStation } from '@/lib/geo';
import { loadPack } from '@/lib/packs';
import { useApp } from '@/lib/store';
import { cap, levelColorKey, plainWords, sourceWords } from '@/lib/text';
import { font } from '@/lib/theme';
import type { Pack } from '@/lib/types';

export default function AlertScreen() {
  const { pack: packCode, id } = useLocalSearchParams<{ pack: string; id: string }>();
  const { p, settings, alerts } = useApp();
  const { width } = useWindowDimensions();
  const [alert, setAlert] = useState<StoredAlert | null>(null);
  const [pack, setPack] = useState<Pack | null>(null);
  const [now] = useState(() => Date.now());

  useEffect(() => {
    (async () => {
      setPack(await loadPack(packCode));
      setAlert(await getAlert(packCode, Number(id)));
    })();
  }, [packCode, id, alerts]);

  const spread = useMemo(() => (alert && pack ? spreadCone(alert, pack) : null), [alert, pack]);
  const road = useMemo(() => (alert && pack ? nearestRoadText(alert, pack) : null), [alert, pack]);

  if (!alert || !pack) {
    return (
      <Screen>
        <View style={{ padding: 20, gap: 16 }}>
          <H1>Loading</H1>
          <Button label="Back" tone="quiet" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const color = p[levelColorKey(alert)];
  const call = () => {
    if (!settings.phone.trim()) router.push('/settings');
    else Linking.openURL(`tel:${settings.phone.replace(/[^0-9+]/g, '')}`);
  };
  const flagWords = [
    alert.flags.includes('red_flag') && 'Red flag day: wind and dryness make fires worse.',
    alert.flags.includes('homes_in_path') && 'Homes may be in the path.',
    alert.flags.includes('mutual_aid') && 'Help from nearby districts was asked for.',
    alert.flags.includes('two_sources') && 'Two sources agree.',
    alert.flags.includes('exercise') && 'This is a practice alert.',
  ].filter(Boolean) as string[];

  return (
    <Screen>
      <ScrollView contentContainerStyle={{ gap: 14, paddingBottom: 24 }}>
        <View style={{ padding: 20, paddingBottom: 0, gap: 6 }}>
          <Button label="Back" tone="quiet" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} style={{ alignSelf: 'flex-start', minHeight: 56, paddingHorizontal: 24 }} />
          <View style={{ height: 6, backgroundColor: color, marginTop: 8 }} />
          <H1>{plainWords(alert)}</H1>
          <Text style={{ color: p.muted, fontFamily: font.regular, fontSize: 16 }}>
            {cap(ageText(alert.time, now))}, by {sourceWords(alert.source)}
          </Text>
        </View>
        <View style={{ paddingHorizontal: 20, gap: 8 }}>
          <Body size={22} style={{ fontFamily: font.medium }}>{alert.kind === 'alert' ? summarize(alert, pack) : cap(whereFromStation(alert, pack)) + '.'}</Body>
        </View>
        <FireMap pack={pack} fire={{ lat: alert.lat, lon: alert.lon, level: levelColorKey(alert) === 'escalate' ? 'escalate' : 'investigate' }} spread={spread} p={p} width={width} height={300} />
        <View style={{ paddingHorizontal: 20 }}>
          <Button label={settings.phone.trim() ? 'Call dispatch' : 'Add dispatch number'} tone="fire" onPress={call} sub={settings.phone.trim() || undefined} />
        </View>
        <View style={{ paddingHorizontal: 20, gap: 8 }}>
          {road && <Body>Nearest road: {road}</Body>}
          {spread ? (
            <>
              <Body size={20} style={{ fontFamily: font.bold }}>
                If it keeps moving {compassWord(spread.headingDeg)} (worst case)
              </Body>
              {spread.exposed.length === 0 && <Body muted>Nothing named in its path.</Body>}
              {spread.exposed.slice(0, 8).map((e) => (
                <Body key={e.name}>{e.name}: as little as {fmtMinutes(e.minutes)}</Body>
              ))}
              {spread.otherBuildings > 0 && <Body muted>{spread.otherBuildings} more buildings in the path.</Body>}
            </>
          ) : (
            alert.kind === 'alert' && <Body muted>{alert.mph == null ? 'Speed not known yet' : 'Direction not known yet'}</Body>
          )}
          {flagWords.map((f) => <Body key={f} muted>{f}</Body>)}
        </View>
      </ScrollView>
    </Screen>
  );
}
