import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { NativeModules } from 'react-native';
import * as Linking from 'expo-linking';

/**
 * Tự động phát hiện địa chỉ IP LAN của máy tính chạy Metro Bundler (Expo Go)
 * giúp điện thoại không bị kẹt ở IP cũ khi đổi mạng Wi-Fi / Hotspot.
 */
export function detectDefaultServerUrl(): string {
  try {
    const scriptURL: string | undefined = NativeModules?.SourceCode?.scriptURL;
    if (scriptURL) {
      const match = scriptURL.match(/^https?:\/\/([^:/]+)/i);
      if (match && match[1] && match[1] !== 'localhost' && match[1] !== '127.0.0.1') {
        return `http://${match[1]}:8000`;
      }
    }
  } catch {
    // Ignore
  }

  try {
    const linkingUrl = Linking.createURL('/');
    const match = linkingUrl.match(/^(?:exp|http|https):\/\/([^:/]+)/i);
    if (match && match[1] && match[1] !== 'localhost' && match[1] !== '127.0.0.1') {
      return `http://${match[1]}:8000`;
    }
  } catch {
    // Ignore
  }

  // Fallback về IP Wi-Fi hiện tại của máy tính
  return 'http://192.168.2.42:8000';
}

interface SettingsState {
  serverUrl: string;
  langPair: string;
  readingDirection: 'rtl' | 'ltr';
  autoTranslate: boolean;
  showOriginal: boolean;
}

const initialState: SettingsState = {
  serverUrl: detectDefaultServerUrl(),
  langPair: 'zh-vi',
  readingDirection: 'rtl',
  autoTranslate: false,
  showOriginal: false,
};

export const settingsSlice = createSlice({
  name: 'settings',
  initialState,
  reducers: {
    setServerUrl: (state, action: PayloadAction<string>) => {
      let url = action.payload.trim();
      if (url.endsWith('/')) {
        url = url.slice(0, -1);
      }
      state.serverUrl = url;
    },
    setLangPair: (state, action: PayloadAction<string>) => {
      state.langPair = action.payload;
    },
    setReadingDirection: (state, action: PayloadAction<'rtl' | 'ltr'>) => {
      state.readingDirection = action.payload;
    },
    toggleReadingDirection: (state) => {
      state.readingDirection = state.readingDirection === 'rtl' ? 'ltr' : 'rtl';
    },
    toggleAutoTranslate: (state) => {
      state.autoTranslate = !state.autoTranslate;
    },
    setShowOriginal: (state, action: PayloadAction<boolean>) => {
      state.showOriginal = action.payload;
    },
    toggleShowOriginal: (state) => {
      state.showOriginal = !state.showOriginal;
    },
  },
});

export const {
  setServerUrl,
  setLangPair,
  setReadingDirection,
  toggleReadingDirection,
  toggleAutoTranslate,
  setShowOriginal,
  toggleShowOriginal,
} = settingsSlice.actions;

export default settingsSlice.reducer;
