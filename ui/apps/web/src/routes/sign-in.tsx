import { Button } from "@swarm/ui/components/button";
import { createFileRoute, Link, redirect, useNavigate } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";

import { Mark } from "@/components/icons";
import { authClient } from "@/lib/auth-client";
import { getUser } from "@/lib/session";

/** Only follow same-site paths so the redirect param can't send crews elsewhere. */
const safePath = (p: unknown) => (typeof p === "string" && p.startsWith("/") && !p.startsWith("//") ? p : "/setup");

export const Route = createFileRoute("/sign-in")({
  head: () => ({ meta: [{ title: "Sign in" }] }),
  validateSearch: (s: Record<string, unknown>) => ({ redirect: safePath(s.redirect) }),
  beforeLoad: async ({ search }) => {
    if (await getUser()) throw redirect({ to: search.redirect });
  },
  component: SignInPage,
});

const field = "h-[42px] rounded-lg bg-white px-3 text-sm shadow-[0_0_0_1px_var(--color-line-strong)] outline-none focus:shadow-[0_0_0_1.5px_var(--color-orange),0_0_0_4px_rgb(255_90_31/0.15)]";

function SignInPage() {
  const search = Route.useSearch();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"in" | "up">("in");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const email = String(f.get("email"));
    const password = String(f.get("password"));
    setBusy(true);
    setError(undefined);
    const res =
      mode === "in"
        ? await authClient.signIn.email({ email, password })
        : await authClient.signUp.email({ email, password, name: String(f.get("name")) });
    setBusy(false);
    if (res.error) return setError(res.error.message ?? "Something went wrong");
    await navigate({ to: search.redirect });
  }

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-panel px-4">
      <Link to="/" aria-label="Home">
        <Mark />
      </Link>
      <form onSubmit={submit} className="flex w-full max-w-[380px] flex-col gap-4 rounded-xl bg-white p-6 shadow-[0_0_0_1px_var(--color-line),0_10px_28px_rgb(0_0_0/0.08)]">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]">{mode === "in" ? "Sign in to the console" : "Create an account"}</h1>
          <p className="text-[13px] text-muted">{mode === "in" ? "Mission control is for crew members only." : "Use your work email. You can sign in right away."}</p>
        </div>
        {mode === "up" && <input name="name" required autoComplete="name" placeholder="Name" aria-label="Name" className={field} />}
        <input name="email" type="email" required autoComplete="email" placeholder="Email" aria-label="Email" className={field} />
        <input
          name="password"
          type="password"
          required
          minLength={10}
          autoComplete={mode === "in" ? "current-password" : "new-password"}
          placeholder="Password"
          aria-label="Password"
          className={field}
        />
        {error && (
          <p role="alert" className="text-[13px] font-medium text-hazard">
            {error}
          </p>
        )}
        <Button variant="primary" size="lg" type="submit" disabled={busy}>
          {mode === "in" ? "Sign in" : "Create account"}
        </Button>
        <button type="button" onClick={() => (setMode(mode === "in" ? "up" : "in"), setError(undefined))} className="text-[13px] font-medium text-orange-edge">
          {mode === "in" ? "New here? Create an account" : "Already have an account? Sign in"}
        </button>
      </form>
    </div>
  );
}
