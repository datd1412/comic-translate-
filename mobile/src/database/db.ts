import * as SQLite from 'expo-sqlite';

export interface HistoryItem {
  id: number;
  url: string;
  title: string;
  translated_count: number;
  created_at: string;
}

export interface BookmarkItem {
  id: number;
  url: string;
  title: string;
  created_at: string;
}

let dbInstance: SQLite.SQLiteDatabase | null = null;

export const getDB = async (): Promise<SQLite.SQLiteDatabase> => {
  if (!dbInstance) {
    dbInstance = await SQLite.openDatabaseAsync('comic_translate.db');
    await initDB(dbInstance);
  }
  return dbInstance;
};

export const initDB = async (db: SQLite.SQLiteDatabase): Promise<void> => {
  await db.execAsync(`
    PRAGMA journal_mode = WAL;
    CREATE TABLE IF NOT EXISTS history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL,
      title TEXT NOT NULL,
      translated_count INTEGER DEFAULT 0,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS bookmarks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      url TEXT NOT NULL UNIQUE,
      title TEXT NOT NULL,
      created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
  `);
};

export const saveHistoryItem = async (url: string, title: string, translatedCount: number = 0): Promise<void> => {
  try {
    const db = await getDB();
    await db.runAsync(
      `INSERT INTO history (url, title, translated_count, created_at) VALUES (?, ?, ?, datetime('now', 'localtime'))`,
      [url, title, translatedCount]
    );
  } catch (error) {
    console.warn('Lỗi lưu lịch sử SQLite:', error);
  }
};

export const getHistoryItems = async (): Promise<HistoryItem[]> => {
  try {
    const db = await getDB();
    const rows = await db.getAllAsync<HistoryItem>(
      `SELECT * FROM history ORDER BY id DESC LIMIT 50`
    );
    return rows;
  } catch (error) {
    console.warn('Lỗi đọc lịch sử SQLite:', error);
    return [];
  }
};

export const clearHistory = async (): Promise<void> => {
  try {
    const db = await getDB();
    await db.runAsync(`DELETE FROM history`);
  } catch (error) {
    console.warn('Lỗi xóa lịch sử SQLite:', error);
  }
};

export const saveBookmarkItem = async (url: string, title: string): Promise<void> => {
  try {
    const db = await getDB();
    await db.runAsync(
      `INSERT OR REPLACE INTO bookmarks (url, title, created_at) VALUES (?, ?, datetime('now', 'localtime'))`,
      [url, title]
    );
  } catch (error) {
    console.warn('Lỗi lưu bookmark SQLite:', error);
  }
};

export const getBookmarks = async (): Promise<BookmarkItem[]> => {
  try {
    const db = await getDB();
    const rows = await db.getAllAsync<BookmarkItem>(
      `SELECT * FROM bookmarks ORDER BY id DESC`
    );
    return rows;
  } catch (error) {
    console.warn('Lỗi đọc bookmark SQLite:', error);
    return [];
  }
};

export const deleteBookmarkItem = async (id: number): Promise<void> => {
  try {
    const db = await getDB();
    await db.runAsync(`DELETE FROM bookmarks WHERE id = ?`, [id]);
  } catch (error) {
    console.warn('Lỗi xóa bookmark SQLite:', error);
  }
};

