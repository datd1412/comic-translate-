import { createSlice, PayloadAction } from '@reduxjs/toolkit';

interface SettingsState {
  serverUrl: string;
  langPair: string;
  readingDirection: 'rtl' | 'ltr';
  autoTranslate: boolean;
  showOriginal: boolean;
}

const initialState: SettingsState = {
  // IP Wi-Fi của máy tính đang chạy Backend (172.20.10.4)
  serverUrl: 'http://172.20.10.4:8000',
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
