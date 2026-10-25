import { defineConfig } from "vite";

export default defineConfig({
  build: { target: "esnext" },
  server: {
    port: 5173,
    proxy: {
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
