import { IBMPlexSans_400Regular, IBMPlexSans_500Medium, IBMPlexSans_700Bold, useFonts } from '@expo-google-fonts/ibm-plex-sans';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import React from 'react';
import { View } from 'react-native';
import { GestureHandlerRootView } from 'react-native-gesture-handler';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { slotItems } from '@/lib/extensions';
import { AppProvider, useApp } from '@/lib/store';
import '@/transports/mesh'; // optional radio add-on; delete this line and the folder to remove it

function Shell() {
  const { p, settings } = useApp();
  return (
    <View style={{ flex: 1, backgroundColor: p.bg }}>
      <StatusBar style={settings.theme === 'dark' ? 'light' : 'dark'} />
      {slotItems('root').map((C, i) => <C key={i} />)}
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: p.bg }, animation: 'fade' }} />
    </View>
  );
}

export default function Root() {
  const [loaded] = useFonts({ IBMPlexSans_400Regular, IBMPlexSans_500Medium, IBMPlexSans_700Bold });
  if (!loaded) return <View style={{ flex: 1, backgroundColor: '#08090b' }} />;
  return (
    <GestureHandlerRootView style={{ flex: 1 }}>
      <SafeAreaProvider>
        <AppProvider>
          <Shell />
        </AppProvider>
      </SafeAreaProvider>
    </GestureHandlerRootView>
  );
}
