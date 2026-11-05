import { configureStore } from '@reduxjs/toolkit';
import authReducer from './authSlice';
import settingsReducer from './settingsSlice';
import historyReducer from './historySlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
    settings: settingsReducer,
    history: historyReducer,
  },
  middleware: (getDefaultMiddleware) =>
    getDefaultMiddleware({
      serializableCheck: false,
    }),
});

export type RootState = ReturnType<typeof store.getState>;
export type AppDispatch = typeof store.dispatch;

