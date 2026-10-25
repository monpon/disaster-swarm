import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { useAuth } from "react-oidc-context";

import { ConsoleGate } from "@/components/shell/console-gate";
import { safePath } from "@/lib/spacetime-auth";

/** SpacetimeAuth sends the browser back here with a code; the provider swaps it for a session, then we move on. */
export const Route = createFileRoute("/callback")({
  head: () => ({ meta: [{ title: "Signing in" }] }),
  component: Callback,
});

function Callback() {
  const auth = useAuth();
  const navigate = useNavigate();
  const returnTo = safePath((auth.user?.state as { returnTo?: string } | undefined)?.returnTo);
  useEffect(() => {
    if (auth.isAuthenticated) void navigate({ to: returnTo, replace: true });
  }, [auth.isAuthenticated, navigate, returnTo]);
  return <ConsoleGate>{null}</ConsoleGate>;
}
