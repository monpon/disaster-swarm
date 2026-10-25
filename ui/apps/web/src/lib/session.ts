import { redirect } from "@tanstack/react-router";
import { createServerFn } from "@tanstack/react-start";
import { getRequestHeaders } from "@tanstack/react-start/server";

/** Current user from the session cookie, or null. */
export const getUser = createServerFn({ method: "GET" }).handler(async () => {
  const { auth, ensureAuthSchema } = await import("./auth.server");
  await ensureAuthSchema();
  const session = await auth.api.getSession({ headers: getRequestHeaders() });
  return session ? { id: session.user.id, name: session.user.name, email: session.user.email } : null;
});

/** Route guard: send signed-out visitors to /sign-in and come back after. */
export async function requireUser(href: string) {
  const user = await getUser();
  if (!user) throw redirect({ to: "/sign-in", search: { redirect: href } });
  return { user };
}
