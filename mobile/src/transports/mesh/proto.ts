// Minimal protobuf wire-format reader and writer for the few Meshtastic messages the app needs.
// Written from the field numbers in the public .proto files; no Meshtastic library code is used
// (those libraries are GPL-3.0). Wire format: https://protobuf.dev/programming-guides/encoding/
//
// Field numbers, verified 2026-11-07 against the public definitions:
//   mesh.proto:      https://github.com/meshtastic/protobufs/blob/master/meshtastic/mesh.proto
//   portnums.proto:  https://github.com/meshtastic/protobufs/blob/master/meshtastic/portnums.proto
//   telemetry.proto: https://github.com/meshtastic/protobufs/blob/master/meshtastic/telemetry.proto
// Browsable reference: https://buf.build/meshtastic/protobufs

export const PORT_TEXT = 1; // portnums.proto PortNum.TEXT_MESSAGE_APP = 1
export const PORT_POSITION = 3; // portnums.proto PortNum.POSITION_APP = 3
export const PORT_TELEMETRY = 67; // portnums.proto PortNum.TELEMETRY_APP = 67
export const BROADCAST = 0xffffffff;

const VARINT = 0;
const FIXED64 = 1;
const LEN = 2;
const FIXED32 = 5;

type Field = { num: number; wire: number; value: number; bytes?: Uint8Array };

/** Read every field of one message. Unknown fields are returned and can be ignored. */
export function readFields(buf: Uint8Array): Field[] {
  const out: Field[] = [];
  let i = 0;
  const varint = (): number => {
    let result = 0;
    let mul = 1;
    for (let n = 0; n < 10; n++) {
      if (i >= buf.length) throw new Error('truncated');
      const b = buf[i++];
      result += (b & 0x7f) * mul;
      if (!(b & 0x80)) return result;
      mul *= 128;
    }
    throw new Error('varint too long');
  };
  while (i < buf.length) {
    const key = varint();
    const num = Math.floor(key / 8);
    const wire = key % 8;
    if (wire === VARINT) out.push({ num, wire, value: varint() });
    else if (wire === LEN) {
      const len = varint();
      if (i + len > buf.length) throw new Error('truncated');
      out.push({ num, wire, value: len, bytes: buf.subarray(i, i + len) });
      i += len;
    } else if (wire === FIXED32) {
      if (i + 4 > buf.length) throw new Error('truncated');
      const v = (buf[i] | (buf[i + 1] << 8) | (buf[i + 2] << 16) | (buf[i + 3] << 24)) >>> 0;
      out.push({ num, wire, value: v });
      i += 4;
    } else if (wire === FIXED64) {
      if (i + 8 > buf.length) throw new Error('truncated');
      i += 8;
    } else throw new Error('bad wire type');
  }
  return out;
}

const s32 = (u: number) => u | 0;

export class Writer {
  private bytes: number[] = [];
  private varintRaw(v: number) {
    let n = v;
    while (n >= 128) {
      this.bytes.push((n % 128) | 0x80);
      n = Math.floor(n / 128);
    }
    this.bytes.push(n);
  }
  private key(num: number, wire: number) {
    this.varintRaw(num * 8 + wire);
  }
  uint(num: number, v: number) {
    this.key(num, VARINT);
    this.varintRaw(v);
    return this;
  }
  bool(num: number, v: boolean) {
    return this.uint(num, v ? 1 : 0);
  }
  fixed32(num: number, v: number) {
    this.key(num, FIXED32);
    const u = v >>> 0;
    this.bytes.push(u & 0xff, (u >>> 8) & 0xff, (u >>> 16) & 0xff, (u >>> 24) & 0xff);
    return this;
  }
  /** sfixed32 has the same bytes as fixed32 of the two's complement value. */
  sfixed32(num: number, v: number) {
    return this.fixed32(num, v | 0);
  }
  bytesField(num: number, v: Uint8Array) {
    this.key(num, LEN);
    this.varintRaw(v.length);
    for (const b of v) this.bytes.push(b);
    return this;
  }
  done(): Uint8Array {
    return Uint8Array.from(this.bytes);
  }
}

// ---- Encoders -------------------------------------------------------------------------------------

/** ToRadio { want_config_id = 3 (uint32) }. mesh.proto ToRadio. */
export function encodeWantConfig(id: number): Uint8Array {
  return new Writer().uint(3, id).done();
}

/** Position { latitude_i = 1 (sfixed32), longitude_i = 2 (sfixed32) }, degrees times 1e7. mesh.proto Position. */
export function encodePosition(lat: number, lon: number): Uint8Array {
  return new Writer().sfixed32(1, Math.round(lat * 1e7)).sfixed32(2, Math.round(lon * 1e7)).done();
}

export type OutPacket = { to?: number; channel: number; id: number; port: number; payload: Uint8Array; wantAck?: boolean };

/**
 * ToRadio { packet = 1 (MeshPacket) }.
 * MeshPacket { to = 2 (fixed32), channel = 3 (uint32), decoded = 4 (Data), id = 6 (fixed32), want_ack = 10 (bool) }.
 * Data { portnum = 1 (enum), payload = 2 (bytes) }.
 */
export function encodeToRadioPacket(p: OutPacket): Uint8Array {
  const data = new Writer().uint(1, p.port).bytesField(2, p.payload).done();
  const mesh = new Writer()
    .fixed32(2, p.to ?? BROADCAST)
    .uint(3, p.channel)
    .bytesField(4, data)
    .fixed32(6, p.id)
    .bool(10, !!p.wantAck)
    .done();
  return new Writer().bytesField(1, mesh).done();
}

export function encodeText(text: string, channel: number, id: number, wantAck = true): Uint8Array {
  return encodeToRadioPacket({ channel, id, port: PORT_TEXT, payload: utf8(text), wantAck });
}

export function encodePositionPacket(lat: number, lon: number, channel: number, id: number): Uint8Array {
  return encodeToRadioPacket({ channel, id, port: PORT_POSITION, payload: encodePosition(lat, lon) });
}

// ---- Decoders -------------------------------------------------------------------------------------

export function utf8(s: string): Uint8Array {
  const out: number[] = [];
  for (const ch of s) {
    const c = ch.codePointAt(0)!;
    if (c < 0x80) out.push(c);
    else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
    else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
  }
  return Uint8Array.from(out);
}

export function fromUtf8(b: Uint8Array): string {
  let s = '';
  for (let i = 0; i < b.length; ) {
    const c = b[i];
    let cp: number;
    let n: number;
    if (c < 0x80) { cp = c; n = 1; }
    else if (c >> 5 === 6) { cp = c & 31; n = 2; }
    else if (c >> 4 === 14) { cp = c & 15; n = 3; }
    else if (c >> 3 === 30) { cp = c & 7; n = 4; }
    else { s += '�'; i++; continue; }
    for (let k = 1; k < n; k++) cp = (cp << 6) | ((b[i + k] ?? 0) & 63);
    s += String.fromCodePoint(cp);
    i += n;
  }
  return s;
}

export type Decoded =
  | { kind: 'text'; from: number; text: string }
  | { kind: 'position'; from: number; lat: number; lon: number }
  | { kind: 'battery'; from: number; percent: number }
  | { kind: 'myInfo'; myNum: number }
  | { kind: 'nodeInfo'; num: number; longName?: string; shortName?: string; battery?: number }
  | { kind: 'configComplete'; id: number }
  | { kind: 'other' };

function decodeDeviceMetrics(b: Uint8Array): number | undefined {
  // DeviceMetrics { battery_level = 1 (uint32) }. telemetry.proto.
  const f = readFields(b).find((x) => x.num === 1 && x.wire === VARINT);
  return f ? f.value : undefined;
}

/**
 * FromRadio { id = 1, packet = 2 (MeshPacket), my_info = 3 (MyNodeInfo), node_info = 4 (NodeInfo), config_complete_id = 7 }.
 * MeshPacket { from = 1 (fixed32), decoded = 4 (Data) }. Data { portnum = 1, payload = 2 }.
 * MyNodeInfo { my_node_num = 1 }. NodeInfo { num = 1, user = 2, device_metrics = 6 }. User { long_name = 2, short_name = 3 }.
 * Position { latitude_i = 1, longitude_i = 2 }. Telemetry { device_metrics = 2 }.
 */
export function decodeFromRadio(buf: Uint8Array): Decoded {
  let fields: Field[];
  try {
    fields = readFields(buf);
    for (const f of fields) {
      if (f.num === 2 && f.bytes) {
        const mp = readFields(f.bytes);
        const from = mp.find((x) => x.num === 1)?.value ?? 0;
        const dataF = mp.find((x) => x.num === 4 && x.bytes);
        if (!dataF?.bytes) return { kind: 'other' };
        const d = readFields(dataF.bytes);
        const port = d.find((x) => x.num === 1)?.value ?? 0;
        const payload = d.find((x) => x.num === 2)?.bytes ?? new Uint8Array();
        if (port === PORT_TEXT) return { kind: 'text', from, text: fromUtf8(payload) };
        if (port === PORT_POSITION) {
          const p = readFields(payload);
          const la = p.find((x) => x.num === 1);
          const lo = p.find((x) => x.num === 2);
          if (la && lo) return { kind: 'position', from, lat: s32(la.value) / 1e7, lon: s32(lo.value) / 1e7 };
        }
        if (port === PORT_TELEMETRY) {
          const dm = readFields(payload).find((x) => x.num === 2 && x.bytes);
          const pct = dm?.bytes ? decodeDeviceMetrics(dm.bytes) : undefined;
          if (pct !== undefined) return { kind: 'battery', from, percent: pct };
        }
        return { kind: 'other' };
      }
      if (f.num === 3 && f.bytes) {
        const n = readFields(f.bytes).find((x) => x.num === 1);
        if (n) return { kind: 'myInfo', myNum: n.value };
      }
      if (f.num === 4 && f.bytes) {
        const ni = readFields(f.bytes);
        const num = ni.find((x) => x.num === 1)?.value ?? 0;
        const u = ni.find((x) => x.num === 2 && x.bytes)?.bytes;
        const uf = u ? readFields(u) : [];
        const dm = ni.find((x) => x.num === 6 && x.bytes)?.bytes;
        const nameOf = (n: number) => { const b = uf.find((x) => x.num === n)?.bytes; return b ? fromUtf8(b) : undefined; };
        return { kind: 'nodeInfo', num, longName: nameOf(2), shortName: nameOf(3), battery: dm ? decodeDeviceMetrics(dm) : undefined };
      }
      if (f.num === 7 && f.wire === VARINT) return { kind: 'configComplete', id: f.value };
    }
  } catch {
    return { kind: 'other' };
  }
  return { kind: 'other' };
}
