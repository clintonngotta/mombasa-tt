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
  },
  resolve: {
    alias: {
      "@": import.meta.dirname + "/src",
    },
  },
})
