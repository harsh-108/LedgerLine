import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: Vite serves the UI on :5173 and forwards API calls to FastAPI on :8000,
// so the session cookie stays same-origin. Prod: `npm run build` writes dist/,
// which FastAPI serves (backend/app/main.py, the React block at the end).
// /analyst is a client-side route, not a backend one, so it is not proxied;
// /docs is FastAPI's Swagger UI.
const backend = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": backend,
      "/docs": backend,
      "/openapi.json": backend,
    },
  },
  build: { outDir: "dist", sourcemap: false },
});
