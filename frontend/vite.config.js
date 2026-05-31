import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During local dev, set VITE_API_TARGET to the running agent's HTTP base
// (e.g. http://localhost:8000) so `/api/*` calls are proxied to it.
const API_TARGET = process.env.VITE_API_TARGET || "http://localhost:8000";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
      },
    },
  },
});
