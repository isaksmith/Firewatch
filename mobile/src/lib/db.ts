import * as SQLite from 'expo-sqlite';

let dbp: Promise<SQLite.SQLiteDatabase> | null = null;

export function getDb(): Promise<SQLite.SQLiteDatabase> {
  if (!dbp) {
    dbp = (async () => {
      const db = await SQLite.openDatabaseAsync('firewatch.db');
      await db.execAsync(`
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS alerts (
          pack TEXT NOT NULL, id INTEGER NOT NULL, code TEXT NOT NULL,
          kind TEXT NOT NULL, level TEXT NOT NULL, score INTEGER NOT NULL,
          lat REAL NOT NULL, lon REAL NOT NULL, t INTEGER NOT NULL,
          source TEXT NOT NULL, received INTEGER NOT NULL,
          PRIMARY KEY (pack, id)
        );
        CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY NOT NULL, v TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS packs (
          code TEXT PRIMARY KEY NOT NULL, name TEXT NOT NULL, state TEXT NOT NULL,
          counties TEXT NOT NULL, version TEXT NOT NULL, bytes INTEGER NOT NULL
        );
      `);
      return db;
    })();
  }
  return dbp;
}

export async function kvGet(k: string): Promise<string | null> {
  const db = await getDb();
  const row = await db.getFirstAsync<{ v: string }>('SELECT v FROM kv WHERE k = ?', k);
  return row ? row.v : null;
}

export async function kvSet(k: string, v: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('INSERT OR REPLACE INTO kv (k, v) VALUES (?, ?)', k, v);
}

export async function kvDelete(k: string): Promise<void> {
  const db = await getDb();
  await db.runAsync('DELETE FROM kv WHERE k = ?', k);
}
