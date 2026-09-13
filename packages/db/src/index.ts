import { drizzle } from 'drizzle-orm/postgres-js';
import postgres from 'postgres';
import * as schema from './schema.ts';

export * from './schema.ts';

export type Database = ReturnType<typeof createDatabase>;

// the web is the only consumer. it reads; the collector is the only writer and
// applies the migrations in packages/db/drizzle itself (apps/collector/src/collector/migrations.py).
export function createDatabase(url: string, { max = 10 }: { max?: number } = {}) {
  const client = postgres(url, { max, prepare: false });
  const db = drizzle(client, { schema, casing: 'snake_case' });
  return Object.assign(db, { close: () => client.end() });
}
