import * as Location from 'expo-location';
import { router } from 'expo-router';
import React, { useCallback, useEffect, useState } from 'react';
import { AppState, Pressable, RefreshControl, ScrollView, Text, View } from 'react-native';
import { Body, Button, Field, H1, Screen } from '@/components/ui';
import {
  BoardError, cachedBoard, categoryWords, confirmMessage, confirmPost, confirmWords, distanceText, drainOutbox, ensureDevice,
  fetchBoard, fetchMe, listOutbox, myPostIds, NoSignal, plainAge, postAgeMin, queueReport, removeQueued, reportBody,
  sentLateText, type BoardMe, type BoardPost, type Category, type LatLon, type Queued, type Snapshot,
} from '@/lib/board';
import { useApp } from '@/lib/store';
import { font } from '@/lib/theme';

const POLL_MS = 30000;
type LocState = 'unknown' | 'granted' | 'denied' | 'undetermined';

// Keep sending waiting reports while the app is open, even after leaving this screen.
let senderServer: string | null = null;
let senderTimer: ReturnType<typeof setInterval> | null = null;
function startSender(server: string) {
  senderServer = server;
  if (senderTimer) return;
  senderTimer = setInterval(() => {
    if (senderServer && AppState.currentState === 'active') void drainOutbox(senderServer).catch(() => undefined);
  }, POLL_MS);
}

async function locState(): Promise<LocState> {
  try {
    const p = await Location.getForegroundPermissionsAsync();
    return p.granted ? 'granted' : p.canAskAgain ? 'undetermined' : 'denied';
  } catch {
    return 'denied';
  }
}

/** The phone's position, or null. Never waits more than 8 seconds. */
async function position(): Promise<LatLon | null> {
  try {
    const last = await Location.getLastKnownPositionAsync({ maxAge: 5 * 60000 });
    const pos = last ?? (await Promise.race([
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }),
      new Promise<null>((r) => setTimeout(() => r(null), 8000)),
    ]));
    return pos ? { lat: pos.coords.latitude, lon: pos.coords.longitude } : null;
  } catch {
    return null;
  }
}

function clock(ms: number) {
  const d = new Date(ms);
  return `${d.getHours() % 12 || 12}:${String(d.getMinutes()).padStart(2, '0')} ${d.getHours() < 12 ? 'AM' : 'PM'}`;
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  const { p } = useApp();
  return (
    <View style={{ gap: 10 }}>
      <Text accessibilityRole="header" style={{ color: p.text, fontFamily: font.bold, fontSize: 22 }}>{title}</Text>
      {children}
    </View>
  );
}

function Card({ stripe, children }: { stripe: string; children: React.ReactNode }) {
  const { p } = useApp();
  return (
    <View style={{ flexDirection: 'row', backgroundColor: p.panel, borderColor: p.line, borderWidth: 1, borderRadius: 10, overflow: 'hidden' }}>
      <View style={{ width: 10, backgroundColor: stripe }} />
      <View style={{ flex: 1, padding: 14, gap: 6 }}>{children}</View>
    </View>
  );
}

function Pick({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  const { p } = useApp();
  return (
    <Pressable
      accessibilityRole="radio"
      accessibilityState={{ selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => ({
        flex: 1, minHeight: 60, borderRadius: 10, borderWidth: 2, alignItems: 'center', justifyContent: 'center',
        borderColor: selected ? p.text : p.line, backgroundColor: selected ? p.text : p.panel, opacity: pressed ? 0.7 : 1,
      })}
    >
      <Text style={{ color: selected ? p.bg : p.text, fontFamily: font.bold, fontSize: 20 }}>{label}</Text>
    </Pressable>
  );
}

function ReportForm({ loc, onAskLoc, onDone, onCancel }: {
  loc: LocState; onAskLoc: () => Promise<LocState>; onDone: (msg: string) => void; onCancel: () => void;
}) {
  const { settings, p } = useApp();
  const [cat, setCat] = useState<Category | null>(null);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const send = async () => {
    if (!cat) return setErr('Tap Smoke, Fire or Other first.');
    const body = reportBody(cat, note);
    if (!body) return setErr('For Other, say in a few words what you see.');
    setBusy(true);
    setErr(null);
    let st = loc;
    if (st === 'undetermined') st = await onAskLoc();
    const at = st === 'granted' ? await position() : null;
    await queueReport(cat, body, at);
    const r = await drainOutbox(settings.server).catch(() => ({ sent: [], waiting: 1, offline: true, note: null }));
    const noLoc = at ? '' : ' It has no location, so the station will see it without one.';
    if (r.sent.length > 0 && r.waiting === 0) onDone(`Sent. Neighbors and the fire district can see it.${noLoc}`);
    else if (r.note) onDone(`${r.note} Your report is saved on this phone and will send later.${noLoc}`);
    else onDone(`No signal. Saved on this phone. Waiting for signal, will send.${noLoc}`);
    setBusy(false);
  };

  return (
    <View style={{ gap: 12, borderWidth: 2, borderColor: p.text, borderRadius: 12, padding: 14 }}>
      <Body size={20} style={{ fontFamily: font.bold }}>What do you see?</Body>
      <View accessibilityRole="radiogroup" style={{ flexDirection: 'row', gap: 8 }}>
        <Pick label="Smoke" selected={cat === 'smoke'} onPress={() => setCat('smoke')} />
        <Pick label="Fire" selected={cat === 'fire'} onPress={() => setCat('fire')} />
        <Pick label="Other" selected={cat === 'other'} onPress={() => setCat('other')} />
      </View>
      <Field
        label={cat === 'other' ? 'Say what you see' : 'Short note (you can skip this)'}
        placeholder="Example: big smoke past the grain elevator"
        value={note}
        onChangeText={setNote}
        maxLength={500}
        autoCapitalize="sentences"
        autoCorrect
      />
      <Body muted size={16}>
        {loc === 'granted'
          ? 'Your location is sent with it, so the station knows where you are.'
          : loc === 'denied'
            ? 'Location is off. The station will see your report without a location.'
            : 'The phone will ask to use your location. Say Allow so the station knows where you are.'}
      </Body>
      {err && <Body style={{ color: p.investigate, fontFamily: font.bold }}>{err}</Body>}
      <Button label={busy ? 'Sending' : 'Send report'} tone="fire" disabled={busy} onPress={send} />
      <Button label="Cancel" tone="quiet" disabled={busy} onPress={onCancel} />
    </View>
  );
}

function Outbox({ rows, now, onRetry, onRemove }: { rows: Queued[]; now: number; onRetry: () => void; onRemove: (k: string) => void }) {
  const { p } = useApp();
  if (rows.length === 0) return null;
  return (
    <Section title="On this phone, not sent yet">
      {rows.map((q) => (
        <Card key={q.key} stripe={q.problem ? p.escalate : p.investigate}>
          <Body style={{ fontFamily: font.bold }}>{q.problem ? 'Not sent' : 'Waiting for signal, will send'}</Body>
          <Body>{categoryWords(q.category)}: {q.body}</Body>
          <Body muted size={16}>Saved {clock(q.savedAt)} ({plainAge((now - q.savedAt) / 60000).toLowerCase()})</Body>
          {q.problem && <Body style={{ color: p.escalate }}>{q.problem}</Body>}
          {q.problem && <Button label="Remove" tone="quiet" onPress={() => onRemove(q.key)} />}
        </Card>
      ))}
      {rows.some((q) => !q.problem) && <Button label="Try sending now" tone="quiet" onPress={onRetry} />}
    </Section>
  );
}

function PostCard({ post, me, mine, now, note, onConfirm, busy }: {
  post: BoardPost; me: LatLon | null; mine: boolean; now: number; note: string | undefined; onConfirm: () => void; busy: boolean;
}) {
  const { p } = useApp();
  const stripe = post.category === 'fire' ? p.escalate : post.category === 'smoke' ? p.investigate : p.monitor;
  const where = post.lat == null || post.lon == null ? 'No location given' : me ? distanceText(me, { lat: post.lat, lon: post.lon }) : null;
  const status = confirmWords(post);
  const late = sentLateText(post.sent_late_min);
  return (
    <Card stripe={stripe}>
      <Text style={{ color: p.text, fontFamily: font.bold, fontSize: 21 }}>{categoryWords(post.category)}</Text>
      <Body>{post.body}</Body>
      <Body muted size={16}>{[where, plainAge(postAgeMin(post, now))].filter(Boolean).join(', ')}</Body>
      <Text style={{ color: post.confirms > 0 ? p.ok : p.muted, fontFamily: font.bold, fontSize: 16 }}>{status}</Text>
      {late && <Body muted size={15}>{late}</Body>}
      {post.badge && <Body size={16} style={{ color: p.investigate }}>{post.badge}</Body>}
      {mine ? (
        <Body muted size={16}>Your report</Body>
      ) : (
        <Button label="I see it too" tone="quiet" disabled={busy} onPress={onConfirm} />
      )}
      {note && <Body size={16} style={{ fontFamily: font.medium }}>{note}</Body>}
    </Card>
  );
}

export default function BoardScreen() {
  const { settings, p } = useApp();
  const server = settings.server;
  const [now, setNow] = useState(() => Date.now());
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [online, setOnline] = useState<boolean | null>(null);
  const [me, setMe] = useState<BoardMe | null>(null);
  const [loc, setLoc] = useState<LocState>('unknown');
  const [pos, setPos] = useState<LatLon | null>(null);
  const [outbox, setOutbox] = useState<Queued[]>([]);
  const [mine, setMine] = useState<number[]>([]);
  const [reporting, setReporting] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [confirming, setConfirming] = useState<number | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const reloadLocal = useCallback(async () => {
    setOutbox(await listOutbox());
    setMine(await myPostIds());
  }, []);

  const refresh = useCallback(async () => {
    setNow(Date.now());
    const r = await drainOutbox(server).catch(() => null);
    if (r && r.sent.length > 0) {
      const late = r.sent.find((s) => s.lateMin > 0);
      setMsg(late ? `Sent ${late.lateMin} min late. Your report is on the board now.` : 'Sent. Your report is on the board now.');
    }
    await reloadLocal();
    try {
      setSnap(await fetchBoard(server));
      setOnline(true);
    } catch {
      setOnline(false);
      return;
    }
    try {
      await ensureDevice(server);
      setMe(await fetchMe(server));
    } catch { /* the board still works without this */ }
  }, [server, reloadLocal]);

  useEffect(() => {
    startSender(server);
    void (async () => {
      setSnap(await cachedBoard());
      await reloadLocal();
      const st = await locState();
      setLoc(st);
      if (st === 'granted') setPos(await position());
      await refresh();
    })();
    const t = setInterval(() => { if (AppState.currentState === 'active') void refresh(); }, POLL_MS);
    const sub = AppState.addEventListener('change', (s) => { if (s === 'active') void refresh(); });
    return () => { clearInterval(t); sub.remove(); };
  }, [server, refresh, reloadLocal]);

  const askLoc = async (): Promise<LocState> => {
    let st: LocState = 'denied';
    try {
      const r = await Location.requestForegroundPermissionsAsync();
      st = r.granted ? 'granted' : 'denied';
    } catch { /* stays denied */ }
    setLoc(st);
    if (st === 'granted') setPos(await position());
    return st;
  };

  const confirm = async (post: BoardPost) => {
    setConfirming(post.id);
    let at = pos;
    if (!at && loc === 'granted') at = await position();
    let text: string;
    try {
      const r = await confirmPost(server, post.id, at);
      text = confirmMessage(r);
      if (r.ok) setSnap(await fetchBoard(server).catch(() => snap));
    } catch (e) {
      text = e instanceof NoSignal
        ? 'No signal right now. Try again when you have signal.'
        : e instanceof BoardError ? e.message : 'That did not go through. Try again in a minute.';
    }
    setNotes((n) => ({ ...n, [post.id]: text }));
    setConfirming(null);
  };

  const pull = async () => { setRefreshing(true); await refresh(); setRefreshing(false); };

  const statusLine = online === false
    ? snap ? `No signal. Showing what we had at ${clock(snap.at)}.` : 'No signal. The board shows up when you have signal.'
    : snap ? `Updated ${plainAge((now - snap.at) / 60000).toLowerCase()}` : 'Loading the board';
  const posts = snap?.posts ?? [];
  const burns = snap?.burns ?? [];
  const pending = me && !me.member && !me.station;

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={{ padding: 20, gap: 16 }}
        keyboardShouldPersistTaps="handled"
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={pull} tintColor={p.text} />}
      >
        <H1>Community board</H1>
        <Body muted>What neighbors see right now. If you are in danger, call 911.</Body>
        <Body muted size={16} style={{ color: online === false ? p.investigate : p.muted }}>{statusLine}</Body>
        {pending && (
          <View style={{ borderWidth: 2, borderColor: p.line, borderRadius: 10, padding: 14 }}>
            <Body size={16}>The fire district has not approved this phone yet. You can still post. Your reports show as Unconfirmed until a neighbor nearby confirms them.</Body>
          </View>
        )}
        {msg && (
          <Pressable onPress={() => setMsg(null)} accessibilityRole="button" accessibilityLabel="Dismiss message" style={{ borderColor: msg.startsWith('Sent') ? p.ok : p.investigate, borderWidth: 2, borderRadius: 10, padding: 14, minHeight: 56 }}>
            <Body>{msg}</Body>
            <Body muted size={15}>Tap to close</Body>
          </Pressable>
        )}
        {reporting ? (
          <ReportForm
            loc={loc}
            onAskLoc={askLoc}
            onCancel={() => setReporting(false)}
            onDone={(m) => { setReporting(false); setMsg(m); void reloadLocal(); void fetchBoard(server).then(setSnap).catch(() => undefined); }}
          />
        ) : (
          <Button label="Report what I see" tone="fire" sub="Smoke, fire or something else" onPress={() => { setMsg(null); setReporting(true); }} />
        )}
        <Outbox
          rows={outbox}
          now={now}
          onRetry={() => void refresh()}
          onRemove={(k) => void removeQueued(k).then(reloadLocal)}
        />
        <Section title={`Burns today (${burns.length})`}>
          {burns.length === 0 && <Body muted>No controlled burns registered today.</Body>}
          {burns.map((b, i) => (
            <Card key={`${b.lat},${b.lon},${i}`} stripe={p.ok}>
              <Text style={{ color: p.text, fontFamily: font.bold, fontSize: 20 }}>Controlled burn</Text>
              <Body>{pos ? `${distanceText(pos, b)} (rough spot)` : `Near ${b.lat.toFixed(2)}, ${b.lon.toFixed(2)}`}</Body>
              <Body muted size={16}>Registered {b.registered_at}</Body>
              {b.reports_nearby && <Body size={16} style={{ color: p.investigate, fontFamily: font.bold }}>Reports nearby. Check the posts below.</Body>}
            </Card>
          ))}
          {burns.length > 0 && <Body muted size={15}>A registered burn can still escape. If it looks out of control, call 911.</Body>}
        </Section>
        <Section title="Nearby reports">
          {!pos && loc === 'undetermined' && (
            <Button label="Show how far they are from me" tone="quiet" onPress={() => void askLoc()} />
          )}
          {!pos && loc === 'denied' && <Body muted size={16}>Location is off, so distances are not shown.</Body>}
          {posts.length === 0 && <Body muted>No reports in the last day.</Body>}
          {posts.map((post) => (
            <PostCard
              key={post.id}
              post={post}
              me={pos}
              mine={mine.includes(post.id)}
              now={now}
              note={notes[post.id]}
              busy={confirming === post.id}
              onConfirm={() => void confirm(post)}
            />
          ))}
        </Section>
        <Button label="Back" onPress={() => (router.canGoBack() ? router.back() : router.replace('/'))} />
      </ScrollView>
    </Screen>
  );
}
