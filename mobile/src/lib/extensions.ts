import type { ComponentType } from 'react';

type Slot = 'home' | 'settings' | 'root';

// Optional add-ons (such as the radio) register themselves here. The core app only
// renders whatever has registered, so it never depends on an add-on.
const slots: Record<Slot, ComponentType[]> = { home: [], settings: [], root: [] };

export function registerSlot(slot: Slot, c: ComponentType) {
  if (!slots[slot].includes(c)) slots[slot].push(c);
}
export function slotItems(slot: Slot): ComponentType[] {
  return slots[slot];
}
