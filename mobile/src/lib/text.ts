import type { StoredAlert } from './alerts';
import type { Source } from './types';

export function levelColorKey(a: Pick<StoredAlert, 'level' | 'kind'>): 'escalate' | 'investigate' | 'monitor' {
  if (a.kind !== 'alert') return 'monitor';
  return a.level;
}

export function plainWords(a: Pick<StoredAlert, 'level' | 'kind' | 'flags'>): string {
  const practice = a.flags.includes('exercise') ? 'Practice: ' : '';
  if (a.kind === 'clear') return `${practice}Fire is out or contained`;
  if (a.kind === 'notfire') return `${practice}Not a fire`;
  if (a.level === 'escalate') return `${practice}Fire, page the district`;
  if (a.level === 'investigate') return `${practice}Possible fire, check it`;
  return `${practice}Watching, no action yet`;
}

export function sourceWords(s: Source): string {
  return { text: 'text message', paste: 'pasted text', feed: 'internet feed', radio: 'radio' }[s];
}

export function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
