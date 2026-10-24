import { createFileRoute, Outlet } from "@tanstack/react-router";

/** Console layout: full-height column. Each page owns its top bar and body. */
export const Route = createFileRoute("/_app")({
  component: () => (
    <div className="flex h-svh flex-col overflow-hidden">
      <Outlet />
    </div>
  ),
});
