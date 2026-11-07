import { router, useLocalSearchParams } from 'expo-router';
import React, { useEffect, useState } from 'react';
import { View } from 'react-native';
import { Body, Button, H1, Screen } from '@/components/ui';
import { useApp } from '@/lib/store';

// firewatch://a/<code>. Opening a code only reads it on the phone; nothing is sent.
export default function OpenCode() {
  const { code } = useLocalSearchParams<{ code: string }>();
  const { ingest } = useApp();
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    (async () => {
      const r = await ingest(String(code ?? ''), 'text');
      if (!live) return;
      if (r.ok) router.replace({ pathname: '/alert/[pack]/[id]', params: { pack: r.alert.pack, id: String(r.alert.id) } });
      else if (r.reason === 'no_pack') setProblem(`This alert is for an area you have not downloaded (${r.pack}). Open Settings to add it.`);
      else setProblem('This alert code is damaged. Ask dispatch to resend.');
    })();
    return () => { live = false; };
  }, [code, ingest]);

  return (
    <Screen>
      <View style={{ padding: 20, gap: 16 }}>
        <H1>{problem ? 'Could not open this alert' : 'Opening alert'}</H1>
        {problem && <Body size={20}>{problem}</Body>}
        <Button label="Go to home" tone={problem ? 'main' : 'quiet'} onPress={() => router.replace('/')} />
      </View>
    </Screen>
  );
}
