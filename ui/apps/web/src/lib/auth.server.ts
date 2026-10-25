import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

import { betterAuth } from "better-auth";
import { getMigrations } from "better-auth/db/migration";
import { tanstackStartCookies } from "better-auth/tanstack-start";

/**
 * Console sign-in. Email and password, users in a local SQLite file.
 * Server only: import from server functions and server routes.
 */
const dbPath = process.env.AUTH_DB_PATH ?? "./data/auth.db";
mkdirSync(dirname(dbPath), { recursive: true });

const secret = process.env.BETTER_AUTH_SECRET;
if (!secret && process.env.NODE_ENV === "production") throw new Error("BETTER_AUTH_SECRET is required in production");

export const auth = betterAuth({
  database: new DatabaseSync(dbPath),
  secret: secret ?? "dev-only-secret-change-me-dev-only-secret",
  baseURL: process.env.BETTER_AUTH_URL,
  emailAndPassword: { enabled: true, minPasswordLength: 10 },
  // Must be last.
  plugins: [tanstackStartCookies()],
});

/** Create tables on first use. Safe to call repeatedly. */
let ready: Promise<void> | undefined;
export function ensureAuthSchema() {
  ready ??= getMigrations(auth.options).then((m) => m.runMigrations());
  return ready;
}
