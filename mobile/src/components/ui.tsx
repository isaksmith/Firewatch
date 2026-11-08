import React from 'react';
import { Pressable, StyleSheet, Text, TextInput, View, type TextInputProps, type ViewStyle } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useApp } from '@/lib/store';
import { font, MIN_TARGET } from '@/lib/theme';

export function Screen({ children, scroll }: { children: React.ReactNode; scroll?: boolean; }) {
  const { p } = useApp();
  void scroll;
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: p.bg }} edges={['top', 'left', 'right', 'bottom']}>
      {children}
    </SafeAreaView>
  );
}

export function H1({ children }: { children: React.ReactNode }) {
  const { p } = useApp();
  return <Text accessibilityRole="header" style={{ color: p.text, fontFamily: font.bold, fontSize: 30, lineHeight: 36 }}>{children}</Text>;
}

export function Body({ children, muted, size = 18, style }: { children: React.ReactNode; muted?: boolean; size?: number; style?: object }) {
  const { p } = useApp();
  return <Text style={[{ color: muted ? p.muted : p.text, fontFamily: font.regular, fontSize: size, lineHeight: size * 1.35 }, style]}>{children}</Text>;
}

type BtnProps = {
  label: string;
  onPress: () => void;
  tone?: 'main' | 'quiet' | 'fire';
  disabled?: boolean;
  sub?: string;
  style?: ViewStyle;
};

/** At least 56 pt tall, full width, one clear label. */
export function Button({ label, onPress, tone = 'main', disabled, sub, style }: BtnProps) {
  const { p } = useApp();
  const bg = tone === 'main' ? p.text : tone === 'fire' ? p.escalate : 'transparent';
  const fg = tone === 'main' ? p.bg : tone === 'fire' ? '#08090b' : p.text;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled: !!disabled }}
      disabled={disabled}
      onPress={onPress}
      style={({ pressed }) => [
        styles.btn,
        { backgroundColor: bg, borderColor: tone === 'quiet' ? p.text : bg, opacity: disabled ? 0.4 : pressed ? 0.7 : 1 },
        style,
      ]}
    >
      <Text style={{ color: fg, fontFamily: font.bold, fontSize: 22 }}>{label}</Text>
      {sub ? <Text style={{ color: fg, fontFamily: font.regular, fontSize: 15 }}>{sub}</Text> : null}
    </Pressable>
  );
}

export function Field(props: TextInputProps & { label: string }) {
  const { p } = useApp();
  const { label, ...rest } = props;
  return (
    <View style={{ gap: 6 }}>
      <Body muted size={16}>{label}</Body>
      <TextInput
        placeholderTextColor={p.muted}
        autoCapitalize="none"
        autoCorrect={false}
        {...rest}
        style={{ minHeight: MIN_TARGET, borderWidth: 2, borderColor: p.text, color: p.text, backgroundColor: p.panel, fontFamily: font.regular, fontSize: 20, paddingHorizontal: 14, borderRadius: 8 }}
      />
    </View>
  );
}

export function Choice({ label, sub, selected, onPress }: { label: string; sub?: string; selected: boolean; onPress: () => void }) {
  const { p } = useApp();
  return (
    <Pressable
      accessibilityRole="checkbox"
      accessibilityState={{ checked: selected }}
      accessibilityLabel={label}
      onPress={onPress}
      style={({ pressed }) => [styles.choice, { backgroundColor: selected ? p.panel2 : p.panel, borderColor: selected ? p.text : p.line, opacity: pressed ? 0.7 : 1 }]}
    >
      <View style={[styles.tick, { borderColor: p.text, backgroundColor: selected ? p.ok : 'transparent' }]}>
        {selected ? <Text style={{ color: p.bg, fontFamily: font.bold, fontSize: 18 }}>OK</Text> : null}
      </View>
      <View style={{ flex: 1 }}>
        <Text style={{ color: p.text, fontFamily: font.bold, fontSize: 20 }}>{label}</Text>
        {sub ? <Text style={{ color: p.muted, fontFamily: font.regular, fontSize: 15 }}>{sub}</Text> : null}
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  btn: { minHeight: MIN_TARGET + 4, borderWidth: 2, borderRadius: 10, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 16, paddingVertical: 10 },
  choice: { minHeight: MIN_TARGET + 8, borderWidth: 2, borderRadius: 10, flexDirection: 'row', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 10 },
  tick: { width: 36, height: 36, borderWidth: 2, borderRadius: 8, alignItems: 'center', justifyContent: 'center' },
});
