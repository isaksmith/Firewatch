export type ThemeName = 'dark' | 'day';
export type Palette = {
  bg: string; panel: string; panel2: string; line: string; text: string; muted: string;
  escalate: string; investigate: string; monitor: string; ok: string;
  onAccent: string; mapGrass: string; mapRoad: string; mapBuilding: string; mapLine: string;
};

// Tokens from frontend/src/index.css: void/bg/panel, escalate #ff4b2b, investigate #ffb21a.
export const palettes: Record<ThemeName, Palette> = {
  dark: {
    bg: '#08090b', panel: '#121519', panel2: '#181c21', line: '#2a3038',
    text: '#f4f6f8', muted: '#b4bcc6',
    escalate: '#ff4b2b', investigate: '#ffb21a', monitor: '#8d99a8', ok: '#3ddc97',
    onAccent: '#08090b', mapGrass: '#10130f', mapRoad: '#8b939d', mapBuilding: '#d9dde2', mapLine: '#5cc8ff',
  },
  day: {
    bg: '#f7f4ec', panel: '#ffffff', panel2: '#ece7da', line: '#8a8576',
    text: '#0a0c0f', muted: '#37404a',
    escalate: '#c41e00', investigate: '#8a5200', monitor: '#4a5560', ok: '#0b6b3f',
    onAccent: '#ffffff', mapGrass: '#efe6cc', mapRoad: '#6b665a', mapBuilding: '#1b1e22', mapLine: '#0b5f8f',
  },
};

export const font = {
  regular: 'IBMPlexSans_400Regular',
  medium: 'IBMPlexSans_500Medium',
  bold: 'IBMPlexSans_700Bold',
};

export const MIN_TARGET = 56;
