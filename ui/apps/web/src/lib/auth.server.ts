import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import { DatabaseSync } from "node:sqlite";

import { APIError, betterAuth } from "better-auth";
import { createAuthMiddleware } from "better-auth/api";
import { getMigrations } from "better-auth/db/migration";
import { tanstackStartCookies } from "better-auth/tanstack-start";

/**
 * Console sign-in. Email and password, users in a local SQLite file.
 * Sign-up needs CONSOLE_INVITE_CODE so only the crew can create accounts.
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
  hooks: {
    before: createAuthMiddleware(async (ctx) => {
      if (ctx.path !== "/sign-up/email") return;
      const code = process.env.CONSOLE_INVITE_CODE;
      const given = (ctx.body as { inviteCode?: string } | undefined)?.inviteCode;
      if (!code || given !== code) throw new APIError("FORBIDDEN", { message: "Invalid invite code" });
    }),
  },
  // Must be last.
  plugins: [tanstackStartCookies()],
});

/** Create tables on first use. Safe to call repeatedly. */
let ready: Promise<void> | undefined;
export function ensureAuthSchema() {
  ready ??= getMigrations(auth.options).then((m) => m.runMigrations());
  return ready;
}
