import React, { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { NavigationContainer } from '@react-navigation/native';
import { Provider } from 'react-redux';
import { store } from './src/store';
import { loginSuccess } from './src/store/authSlice';
import { setServerUrl, detectDefaultServerUrl } from './src/store/settingsSlice';
import { AppNavigator } from './src/navigation/AppNavigator';
import { setupNotifications } from './src/utils/notifications';
import { getDB, getAppSetting, saveAppSetting } from './src/database/db';
import { checkServerHealth, fetchUserInfo } from './src/api/comicApi';

export default function App() {
  useEffect(() => {
    setupNotifications();

    (async () => {
      try {
        await getDB();

        // 1. Khôi phục hoặc tự động phát hiện địa chỉ IP Server PC
        const autoUrl = detectDefaultServerUrl();
        const savedUrl = await getAppSetting('server_url');
        let activeServerUrl = savedUrl || autoUrl;

        if (savedUrl && savedUrl !== autoUrl) {
          const savedHealth = await checkServerHealth(savedUrl);
          if (!savedHealth.ok) {
            const autoHealth = await checkServerHealth(autoUrl);
            if (autoHealth.ok) {
              activeServerUrl = autoUrl;
              await saveAppSetting('server_url', autoUrl);
            }
          }
        }
        store.dispatch(setServerUrl(activeServerUrl));

        // 2. Khôi phục phiên đăng nhập đã lưu trong SQLite
        const savedSessionStr = await getAppSetting('auth_session');
        if (savedSessionStr) {
          const parsed = JSON.parse(savedSessionStr);
          if (parsed && parsed.user && parsed.accessToken) {
            store.dispatch(
              loginSuccess({
                user: parsed.user,
                accessToken: parsed.accessToken,
                refreshToken: parsed.refreshToken || '',
              })
            );
            // Làm mới số dư credit ngầm từ server
            try {
              const freshInfo = await fetchUserInfo(activeServerUrl, parsed.accessToken);
              store.dispatch(
                loginSuccess({
                  user: freshInfo,
                  accessToken: parsed.accessToken,
                  refreshToken: parsed.refreshToken || '',
                })
              );
            } catch {
              // Ignore if server offline on boot
            }
          }
        }
      } catch (err) {
        console.warn('Lỗi khởi động SQLite DB:', err);
      }
    })();
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
