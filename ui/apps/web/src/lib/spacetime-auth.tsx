import { InMemoryWebStorage, WebStorageStateStore, type User } from "oidc-client-ts";
import type { ReactNode } from "react";
import { AuthProvider } from "react-oidc-context";

/**
 * Console sign-in through SpacetimeAuth (an OpenID Connect provider). The browser runs the authorization code flow;
 * nothing is stored on our server, so it works on any host.
 */
export const clientId: string | undefined = import.meta.env.VITE_SPACETIMEAUTH_CLIENT_ID;
const authority: string = import.meta.env.VITE_SPACETIMEAUTH_AUTHORITY || "https://auth.spacetimedb.com/oidc";

/** The server renders this tree too, where there is no window: keep the sign-in state in memory there. */
const store = typeof window === "undefined" ? new InMemoryWebStorage() : window.localStorage;

/** Where to land after sign-in. Only same-site paths, so the state can't send crews elsewhere. */
export const safePath = (p: unknown) => (typeof p === "string" && p.startsWith("/") && !p.startsWith("//") ? p : "/setup");

export function SpacetimeAuthProvider({ children }: { children: ReactNode }) {
  return (
    <AuthProvider
      authority={authority}
      client_id={clientId ?? "unset"}
      redirect_uri={typeof window === "undefined" ? "" : `${window.location.origin}/callback`}
      post_logout_redirect_uri={typeof window === "undefined" ? "" : window.location.origin}
      response_type="code"
      scope="openid profile email"
      automaticSilentRenew
      userStore={new WebStorageStateStore({ store })}
      stateStore={new WebStorageStateStore({ store })}
      onSigninCallback={() => window.history.replaceState({}, document.title, "/callback")}
    >
      {children}
    </AuthProvider>
  );
}

export const displayName = (user: User | null | undefined) =>
  String(user?.profile.name ?? user?.profile.preferred_username ?? user?.profile.email ?? "");
