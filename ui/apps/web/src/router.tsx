import { createRouter as createTanStackRouter } from "@tanstack/react-router";

import { routeTree } from "./routeTree.gen";

export const getRouter = () =>
  createTanStackRouter({
    routeTree,
    scrollRestoration: true,
    defaultPreloadStaleTime: 0,
    defaultNotFoundComponent: () => <div className="p-8 text-sm text-muted">Not found</div>,
  });

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
