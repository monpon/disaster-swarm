import { createFileRoute, Outlet } from "@tanstack/react-router";

import { requireUser } from "@/lib/session";

/** Console layout: full-height column. Each page owns its top bar and body. */
export const Route = createFileRoute("/_app")({
  beforeLoad: ({ location }) => requireUser(location.href),
  component: () => (
    <div className="flex h-svh flex-col overflow-hidden">
      <Outlet />
    </div>
  ),
});
