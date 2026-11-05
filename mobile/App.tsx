import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { NavigationContainer } from '@react-navigation/native';
import { Provider } from 'react-redux';
import { store } from './src/store';
import { AppNavigator } from './src/navigation/AppNavigator';
import { setupNotifications } from './src/utils/notifications';
import { getDB } from './src/database/db';

export default function App() {
  useEffect(() => {
    // Initialize push notifications & SQLite database
    setupNotifications();
    getDB().catch((err) => console.warn('Lỗi khởi động SQLite DB:', err));
  }, []);

  return (
    <Provider store={store}>
      <SafeAreaProvider>
        <NavigationContainer>
          <StatusBar style="light" />
          <AppNavigator />
        </NavigationContainer>
      </SafeAreaProvider>
    </Provider>
  );
}
