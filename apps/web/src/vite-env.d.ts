/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

/** This release's build number (pwa-worker.ts): sent to the API, which may ask an old build to update. */
declare const __APP_BUILD__: string
