import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Same-origin API in development so session and CSRF cookies just work.
    proxy: {
      "/api": process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8010",
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
