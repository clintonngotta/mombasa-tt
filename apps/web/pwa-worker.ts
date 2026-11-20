import { createHash } from "node:crypto"
import { readFileSync } from "node:fs"
import type { Plugin } from "vite"

const TEMPLATE = import.meta.dirname + "/pwa/service-worker.js"
/** Public files every release keeps for offline use (besides its own scripts and styles). */
const PUBLIC_SHELL = ["/index.html", "/manifest.webmanifest", "/favicon-32.png", "/favicon.png", "/apple-touch-icon.png", "/logo-mark.png", "/icons/icon-192.png", "/icons/icon-512.png", "/icons/maskable-512.png"]

/** The release's build number: APP_BUILD when CI sets it, else the build time (UTC, to the minute). */
export const APP_BUILD = process.env.APP_BUILD || new Date().toISOString().slice(0, 16).replace(/\D/g, "")

/**
 * Write /sw.js into the production build (REQ-035): the template in pwa/ with this release's build
 * number and the files it keeps for offline use. Nothing is written in development, where no worker runs.
 */
export function pwaWorker(): Plugin {
  return {
    name: "pwa-worker",
    apply: "build",
    generateBundle(_options, bundle) {
      const built = Object.keys(bundle)
        .filter((name) => name.startsWith("assets/") && /\.(js|css|woff2)$/.test(name))
        .map((name) => `/${name}`)
      const shell = [...PUBLIC_SHELL, ...built].sort()
      // The version changes whenever any file does: fingerprinted names already say so.
      const version = `${APP_BUILD}-${createHash("sha256").update(shell.join("\n")).digest("hex").slice(0, 10)}`
      const source = readFileSync(TEMPLATE, "utf8")
        .replace('"__BUILD__"', JSON.stringify(version))
        .replace("/* __SHELL__ */ []", JSON.stringify(shell))
      this.emitFile({ type: "asset", fileName: "sw.js", source })
    },
  }
}
