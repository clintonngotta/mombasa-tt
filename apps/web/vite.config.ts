import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { geographyAssets } from "./geography-assets.ts"
import { APP_BUILD, pwaWorker } from "./pwa-worker.ts"

const API = process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8010"

export default defineConfig({
  plugins: [react(), tailwindcss(), geographyAssets(), pwaWorker()],
  define: { __APP_BUILD__: JSON.stringify(APP_BUILD) },
  server: {
    // Same-origin API in development so session and CSRF cookies just work.
    proxy: {
      // ws: live tournament updates at /api/v1/ws/ go through the same proxy.
      "/api": { target: API, ws: true },
      // Django admin (where the platform owner signs in) and its styles, as the production proxy does.
      "^/admin(/|$)": { target: API },
      "^/static/": { target: API },
    },
    // The scoring reducer lives beside the app in packages/scoring (shared with future clients).
    fs: { allow: [import.meta.dirname + "/../.."] },
  },
  resolve: {
    alias: {
      "@": import.meta.dirname + "/src",
      "@scoring": import.meta.dirname + "/../../packages/scoring/src/index.ts",
    },
  },
})
