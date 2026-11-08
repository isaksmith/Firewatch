import * as Location from 'expo-location';
import { findCodes } from '@/lib/codec';
import { ingestText } from '@/lib/alerts';
import { kvDelete, kvGet, kvSet } from '@/lib/db';
import { SERVICE_UUID, TORADIO_UUID, FROMRADIO_UUID, FROMNUM_UUID, b64ToBytes, bytesToB64 } from './ble-ids';
import { decodeFromRadio, encodePositionPacket, encodeText, encodeWantConfig } from './proto';
import { SIM_CODES } from './sim-codes';
import { addMessage, getRadio, setRadio } from './state';

// react-native-ble-plx is a native module. It is loaded lazily so the rest of the app never needs it.
let manager: any = null;
function ble(): any {
  if (!manager) {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { BleManager } = require('react-native-ble-plx');
    manager = new BleManager();
  }
  return manager;
}

let onChange: () => void = () => {};
export function setOnAlertsChanged(f: () => void) { onChange = f; }

let device: any = null;
let myNum: number | null = null;
let fromNumSub: { remove: () => void } | null = null;
let discSub: { remove: () => void } | null = null;
let simTimers: ReturnType<typeof setTimeout>[] = [];
let wantReconnect = true;
let draining = false;
let drainAgain = false;

const hex = (n: number) => `!${n.toString(16).padStart(8, '0')}`;

/** A text from the radio: FW1 codes go into the same store as texts and paste; anything else is channel chatter. */
export async function handleRadioText(from: number, text: string) {
  if (findCodes(text).length > 0) {
    const r = await ingestText(text, 'radio');
    if (r.opened.some((o) => o.ok && o.changed)) onChange();
    return;
  }
  addMessage({ at: Date.now(), from: hex(from), text });
}

async function handleBytes(b: Uint8Array) {
  const d = decodeFromRadio(b);
  if (d.kind === 'text') await handleRadioText(d.from, d.text);
  else if (d.kind === 'myInfo') myNum = d.myNum;
  else if (d.kind === 'nodeInfo' && d.num === myNum) {
    const patch: Partial<ReturnType<typeof getRadio>> = {};
    if (d.battery !== undefined) patch.battery = d.battery;
    if (d.longName && !getRadio().name) patch.name = d.longName;
    setRadio(patch);
  } else if (d.kind === 'battery' && d.from === myNum) setRadio({ battery: d.percent });
}

async function drain() {
  if (draining) { drainAgain = true; return; }
  draining = true;
  try {
    do {
      drainAgain = false;
      for (let i = 0; i < 400; i++) {
        const c = await device.readCharacteristicForService(SERVICE_UUID, FROMRADIO_UUID);
        const bytes = c.value ? b64ToBytes(c.value) : new Uint8Array();
        if (bytes.length === 0) break;
        await handleBytes(bytes);
      }
    } while (drainAgain);
  } finally {
    draining = false;
  }
}

export async function loadSaved() {
  const ch = await kvGet('radio:channel');
  const name = await kvGet('radio:name');
  setRadio({ channel: ch ? Number(ch) || 0 : 0, savedName: name });
}

export async function setChannel(n: number) {
  const v = Math.max(0, Math.min(7, Math.round(n) || 0));
  setRadio({ channel: v });
  await kvSet('radio:channel', String(v));
}

function clean() {
  fromNumSub?.remove(); fromNumSub = null;
  discSub?.remove(); discSub = null;
  device = null; myNum = null;
}

async function waitPoweredOn(): Promise<boolean> {
  const m = ble();
  if ((await m.state()) === 'PoweredOn') return true;
  return new Promise((res) => {
    const sub = m.onStateChange((s: string) => {
      if (s === 'PoweredOn') { sub.remove(); res(true); }
    }, true);
    setTimeout(() => { sub.remove(); res(false); }, 6000);
  });
}

/** Look for Meshtastic radios for a few seconds. One found means connect to it; several means let the person choose. */
export async function scanAndConnect() {
  stopSim();
  setRadio({ status: 'searching', found: [], note: null, btOff: false });
  try {
    if (!(await waitPoweredOn())) { setRadio({ status: 'off', btOff: true, note: 'Bluetooth is off. Turn it on in Settings, then try again.' }); return; }
    const m = ble();
    const found = new Map<string, string>();
    await new Promise<void>((done) => {
      m.startDeviceScan([SERVICE_UUID], null, (err: any, d: any) => {
        if (err) { done(); return; }
        if (d && !found.has(d.id)) { found.set(d.id, d.localName || d.name || 'Meshtastic radio'); setRadio({ found: [...found].map(([id, name]) => ({ id, name })) }); }
      });
      setTimeout(done, 6000);
    });
    m.stopDeviceScan();
    if (found.size === 0) { setRadio({ status: 'off', note: 'No radio found. Turn the radio on and hold it close to the phone.' }); return; }
    if (found.size === 1) { const [id, name] = [...found][0]; await connectTo(id, name); }
    else setRadio({ status: 'off', note: 'Tap your radio.' });
  } catch (e) {
    manager = null;
    setRadio({ status: 'off', note: friendly(e) });
  }
}

function friendly(e: unknown): string {
  const t = String((e as Error)?.message ?? e);
  if (/unauthor|permission/i.test(t)) return 'Firewatch needs Bluetooth. Allow it in Settings, then try again.';
  if (/Cannot find native|ble-plx|BleManager|null/i.test(t)) return 'Radio needs the full Firewatch app, not a preview.';
  return 'Could not reach the radio. Hold it close and try again.';
}

export async function connectTo(id: string, name: string) {
  setRadio({ status: 'connecting', found: [], note: null, name });
  try {
    const m = ble();
    const d = await m.connectToDevice(id, { requestMTU: 512, timeout: 15000 });
    await d.discoverAllServicesAndCharacteristics();
    device = d;
    discSub = d.onDisconnected(() => {
      clean();
      setRadio({ status: 'off', kind: null, note: 'Radio disconnected.' });
      if (wantReconnect) setTimeout(() => { if (getRadio().status === 'off' && wantReconnect) void autoReconnect(); }, 8000);
    });
    // Client API flow: want_config_id, drain FromRadio until empty, then follow FromNum.
    await d.writeCharacteristicWithResponseForService(SERVICE_UUID, TORADIO_UUID, bytesToB64(encodeWantConfig(1 + Math.floor(Math.random() * 0x7ffffffe))));
    await kvSet('radio:id', id);
    await kvSet('radio:name', name);
    wantReconnect = true;
    setRadio({ status: 'connected', kind: 'ble', name, savedName: name });
    await drain();
    fromNumSub = d.monitorCharacteristicForService(SERVICE_UUID, FROMNUM_UUID, (err: any) => {
      if (!err) void drain().catch(() => {});
    });
  } catch (e) {
    clean();
    setRadio({ status: 'off', kind: null, note: friendly(e) });
  }
}

/** Reconnect to the saved radio when the app opens. Quiet: no message if the radio is not near. */
export async function autoReconnect() {
  if (getRadio().status !== 'off') return;
  const id = await kvGet('radio:id');
  const name = await kvGet('radio:name');
  if (!id) return;
  try { await connectTo(id, name ?? 'Radio'); } catch { /* stays off */ }
}

export async function disconnect() {
  wantReconnect = false;
  stopSim();
  try { await device?.cancelConnection(); } catch { /* already gone */ }
  clean();
  setRadio({ status: 'off', kind: null, battery: null, note: null });
}

let forgotten: { id: string; name: string } | null = null;
export async function forget() {
  const id = await kvGet('radio:id');
  const name = await kvGet('radio:name');
  forgotten = id ? { id, name: name ?? 'Radio' } : null;
  await disconnect();
  await kvDelete('radio:id');
  await kvDelete('radio:name');
  setRadio({ savedName: null, name: null, note: forgotten ? 'Radio forgotten.' : null });
}
export function canUndoForget() { return !!forgotten; }
export async function undoForget() {
  if (!forgotten) return;
  const f = forgotten;
  forgotten = null;
  await kvSet('radio:id', f.id);
  await kvSet('radio:name', f.name);
  setRadio({ savedName: f.name, note: null });
  wantReconnect = true;
  await connectTo(f.id, f.name);
}

// ---- Sending ----------------------------------------------------------------------------------------

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const newId = () => 1 + Math.floor(Math.random() * 0xfffffffe);

export type SendResult = { ok: true } | { ok: false; why: string };

/**
 * Report smoke from the phone's GPS. The bridge places reports at the node's last position fix, so a
 * POSITION_APP packet goes first, then the channel text "FIRE <lat>,<lon>". "Sent" means the radio accepted the write.
 */
export async function reportSmoke(): Promise<SendResult> {
  const st = getRadio();
  if (st.status !== 'connected') return { ok: false, why: 'Connect your radio first.' };
  let perm = await Location.getForegroundPermissionsAsync();
  if (!perm.granted) perm = await Location.requestForegroundPermissionsAsync();
  if (!perm.granted) return { ok: false, why: 'Allow location so Firewatch can tell the radio where the smoke is.' };
  let pos: Location.LocationObject;
  try {
    pos = (await Location.getLastKnownPositionAsync({ maxAge: 60000 })) ?? (await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced }));
  } catch {
    return { ok: false, why: 'Could not find your location. Try again outside.' };
  }
  const lat = pos.coords.latitude;
  const lon = pos.coords.longitude;
  const text = `FIRE ${lat.toFixed(5)},${lon.toFixed(5)}`;
  const posPkt = encodePositionPacket(lat, lon, st.channel, newId());
  const txtPkt = encodeText(text, st.channel, newId(), true);
  if (st.kind === 'sim') {
    addMessage({ at: Date.now(), from: 'you', text });
    return { ok: true };
  }
  try {
    await device.writeCharacteristicWithResponseForService(SERVICE_UUID, TORADIO_UUID, bytesToB64(posPkt));
    await sleep(1500); // the radio drops packets handed over back to back
    await device.writeCharacteristicWithResponseForService(SERVICE_UUID, TORADIO_UUID, bytesToB64(txtPkt));
    addMessage({ at: Date.now(), from: 'you', text });
    return { ok: true };
  } catch {
    return { ok: false, why: 'The radio did not take it. Hold it close and try again.' };
  }
}

// ---- Simulated radio (hidden test tool) -------------------------------------------------------------

export function stopSim() {
  simTimers.forEach(clearTimeout);
  simTimers = [];
}

export function startSim() {
  stopSim();
  setRadio({ status: 'connected', kind: 'sim', name: 'Simulated radio', battery: 80, note: null, found: [] });
  const steps: [number, () => void][] = [
    [1500, () => void handleRadioText(1, SIM_CODES[0])],
    [6000, () => void handleRadioText(2, 'fire looks bigger')],
    [10000, () => void handleRadioText(1, `Fire alert: check the app. ${SIM_CODES[1]}`)],
    [18000, () => void handleRadioText(1, SIM_CODES[2])],
  ];
  for (const [ms, fn] of steps) simTimers.push(setTimeout(fn, ms));
}
