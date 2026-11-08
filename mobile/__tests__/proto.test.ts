import { decodeFromRadio, encodePosition, encodePositionPacket, encodeText, encodeWantConfig, readFields, utf8 } from '../src/transports/mesh/proto';

const hex = (b: Uint8Array) => Buffer.from(b).toString('hex');

// FromRadio { packet { from=0x11223344, decoded { portnum=1, payload="hi FW1." } } } built by hand.
function fromRadioText(text: string): Uint8Array {
  const payload = [...utf8(text)];
  const data = [0x08, 0x01, 0x12, payload.length, ...payload];
  const mesh = [0x0d, 0x44, 0x33, 0x22, 0x11, 0x22, data.length, ...data];
  return Uint8Array.from([0x08, 0x05, 0x12, mesh.length, ...mesh]);
}

it('encodes want_config_id as field 3 varint', () => {
  expect(hex(encodeWantConfig(5))).toBe('1805');
  expect(hex(encodeWantConfig(300))).toBe('18ac02');
});

it('encodes a position with signed fixed32 degrees', () => {
  // 37.3821 * 1e7 = 373821000 = 0x16477F48 ; -99.4681 * 1e7 = -994681000 -> two's complement 0xC4B1 6C58
  const b = encodePosition(37.3821, -99.4681);
  expect(b.length).toBe(10);
  expect(b[0]).toBe(0x0d);
  expect(b[5]).toBe(0x15);
  const f = readFields(b);
  expect(f[0].value | 0).toBe(373821000);
  expect(f[1].value | 0).toBe(-994681000);
});

it('encodes a text packet that decodes back through the packet fields', () => {
  const out = encodeText('FIRE 37.38210,-99.46810', 0, 7);
  const top = readFields(out);
  expect(top[0].num).toBe(1);
  const mesh = readFields(top[0].bytes!);
  expect(mesh.find((f) => f.num === 2)!.value).toBe(0xffffffff);
  expect(mesh.find((f) => f.num === 6)!.value).toBe(7);
  expect(mesh.find((f) => f.num === 10)!.value).toBe(1);
  const data = readFields(mesh.find((f) => f.num === 4)!.bytes!);
  expect(data[0].value).toBe(1);
  expect(Buffer.from(data[1].bytes!).toString()).toBe('FIRE 37.38210,-99.46810');
});

it('encodes a position packet on portnum 3', () => {
  const mesh = readFields(readFields(encodePositionPacket(37.1, -99.2, 2, 9))[0].bytes!);
  expect(mesh.find((f) => f.num === 3)!.value).toBe(2);
  const data = readFields(mesh.find((f) => f.num === 4)!.bytes!);
  expect(data[0].value).toBe(3);
});

it('decodes a text packet from hand-built bytes', () => {
  const d = decodeFromRadio(fromRadioText('hi FW1.x'));
  expect(d).toEqual({ kind: 'text', from: 0x11223344, text: 'hi FW1.x' });
});

it('decodes my_info, node_info with battery, and config complete', () => {
  expect(decodeFromRadio(Uint8Array.from([0x1a, 0x03, 0x08, 0xe8, 0x07]))).toEqual({ kind: 'myInfo', myNum: 1000 });
  // NodeInfo { num=1000, user { long_name="Tom" }, device_metrics { battery_level=87 } }
  const user = [0x12, 3, 0x54, 0x6f, 0x6d];
  const ni = [0x08, 0xe8, 0x07, 0x12, user.length, ...user, 0x32, 2, 0x08, 87];
  const d = decodeFromRadio(Uint8Array.from([0x22, ni.length, ...ni]));
  expect(d).toEqual({ kind: 'nodeInfo', num: 1000, longName: 'Tom', shortName: undefined, battery: 87 });
  expect(decodeFromRadio(Uint8Array.from([0x38, 0x05]))).toEqual({ kind: 'configComplete', id: 5 });
});

it('survives garbage and truncated bytes', () => {
  expect(decodeFromRadio(Uint8Array.from([0x12, 0x40, 0x01]))).toEqual({ kind: 'other' });
  expect(decodeFromRadio(new Uint8Array())).toEqual({ kind: 'other' });
});
