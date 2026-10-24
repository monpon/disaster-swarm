import tailwindcss from "@tailwindcss/vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import viteReact from "@vitejs/plugin-react";
import { nitro } from "nitro/vite";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 3001,
  },
  resolve: {
    tsconfigPaths: true,
  },
  plugins: [tailwindcss(), tanstackStart(), nitro(), viteReact()],
  // Bundle all SSR deps for serverless hosts. Production only: in dev,
  // noExternal inlines CJS deps (react) as ESM and every SSR request 500s.
  ssr: process.env.NODE_ENV === "production" ? { noExternal: true } : undefined,
});
