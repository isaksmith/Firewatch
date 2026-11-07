// Meshtastic BLE client API identifiers.
// Source: https://meshtastic.org/docs/development/device/client-api/ (checked 2026-11-07)
export const SERVICE_UUID = '6ba1b218-15a8-461f-9fa8-5dcae273eafd';
export const TORADIO_UUID = 'f75c76d2-129e-4dad-a1dd-7866124401e7'; // write
export const FROMRADIO_UUID = '2c55e69e-4993-11ed-b878-0242ac120002'; // read until empty
export const FROMNUM_UUID = 'ed9da18c-a800-4f66-a670-aa7547e34453'; // notify

export function bytesToB64(b: Uint8Array): string {
  let s = '';
  for (const x of b) s += String.fromCharCode(x);
  return btoa(s);
}
export function b64ToBytes(s: string): Uint8Array {
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
