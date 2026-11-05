import { createSlice, PayloadAction } from '@reduxjs/toolkit';
import { HistoryItem, BookmarkItem } from '../database/db';

interface HistoryState {
  historyList: HistoryItem[];
  bookmarks: BookmarkItem[];
  currentUrl: string;
  currentTitle: string;
}

const initialState: HistoryState = {
  historyList: [],
  bookmarks: [],
  currentUrl: 'https://m.baozimh.com',
  currentTitle: 'Baozi Manhua',
};

export const historySlice = createSlice({
  name: 'history',
  initialState,
  reducers: {
    setCurrentPage: (
      state,
      action: PayloadAction<{ url: string; title: string }>
    ) => {
      state.currentUrl = action.payload.url;
      state.currentTitle = action.payload.title;
    },
    setHistoryList: (state, action: PayloadAction<HistoryItem[]>) => {
      state.historyList = action.payload;
    },
    setBookmarksList: (state, action: PayloadAction<BookmarkItem[]>) => {
      state.bookmarks = action.payload;
    },
  },
});

export const { setCurrentPage, setHistoryList, setBookmarksList } =
  historySlice.actions;

export default historySlice.reducer;

