import { Button } from "@swarm/ui/components/button";
import { Link } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { useAuth } from "react-oidc-context";

import { Mark } from "@/components/icons";
import { clientId } from "@/lib/spacetime-auth";

/** Shows the console only to signed-in crew; everyone else gets the SpacetimeAuth sign-in. */
export function ConsoleGate({ children }: { children: ReactNode }) {
  const auth = useAuth();
  if (auth.isAuthenticated) return <>{children}</>;

  const message = !clientId
    ? "Sign-in is not set up yet. Set VITE_SPACETIMEAUTH_CLIENT_ID and rebuild."
    : auth.error
      ? `Sign-in failed: ${auth.error.message}`
      : auth.isLoading
        ? "Checking your sign-in…"
        : "Mission control is for crew members only.";

  return (
    <div className="flex min-h-svh flex-col items-center justify-center gap-6 bg-panel px-4">
      <Link to="/" aria-label="Home">
        <Mark />
      </Link>
      <div className="flex w-full max-w-[380px] flex-col gap-4 rounded-xl bg-white p-6 shadow-[0_0_0_1px_var(--color-line),0_10px_28px_rgb(0_0_0/0.08)]">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-[-0.01em]">Sign in to the console</h1>
          <p role={auth.error ? "alert" : undefined} className="text-[13px] text-muted">
            {message}
          </p>
        </div>
        <Button
          variant="primary"
          size="lg"
          disabled={!clientId || auth.isLoading}
          onClick={() => void auth.signinRedirect({ state: { returnTo: window.location.pathname + window.location.search } })}
        >
          Sign in with SpacetimeAuth
        </Button>
      </div>
    </div>
  );
}
