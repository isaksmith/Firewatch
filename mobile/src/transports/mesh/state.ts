import { useSyncExternalStore } from 'react';

export type RadioMessage = { at: number; from: string; text: string };
export type RadioState = {
  status: 'off' | 'searching' | 'connecting' | 'connected';
  kind: 'ble' | 'sim' | null;
  name: string | null;
  battery: number | null;
  found: { id: string; name: string }[];
  messages: RadioMessage[];
  note: string | null;
  /** Remembered radio, kept after a disconnect so Connect can reuse it. */
  savedName: string | null;
  channel: number;
  btOff: boolean;
};

let state: RadioState = {
  status: 'off', kind: null, name: null, battery: null, found: [], messages: [], note: null, savedName: null, channel: 0, btOff: false,
};
const subs = new Set<() => void>();

export function getRadio(): RadioState {
  return state;
}
export function setRadio(patch: Partial<RadioState>) {
  state = { ...state, ...patch };
  subs.forEach((f) => f());
}
export function useRadio(): RadioState {
  return useSyncExternalStore(
    (f) => { subs.add(f); return () => { subs.delete(f); }; },
    getRadio,
    getRadio,
  );
}
export function addMessage(m: RadioMessage) {
  setRadio({ messages: [m, ...state.messages].slice(0, 30) });
}
