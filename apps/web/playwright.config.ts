import { defineConfig, devices } from "@playwright/test"

/**
 * End-to-end tests in a real browser, against the local stack (see e2e/README.md):
 *
 *   docker compose up -d          # from the repository root: web on :8080, API on :8020, test logins seeded
 *   pnpm test:e2e                 # from apps/web
 *
 * Point E2E_BASE_URL at another running copy (e.g. http://localhost:5173) to test that instead. The tests
 * never start or stop a server themselves.
 */
const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:8080"
const player = "e2e/.auth/player.json"

export default defineConfig({
  testDir: "e2e",
  // A hung page fails its test rather than the whole run waiting on it.
  timeout: 30_000,
  globalTimeout: 10 * 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL, trace: "retain-on-failure", screenshot: "only-on-failure", actionTimeout: 10_000, navigationTimeout: 20_000 },
  projects: [
    // Logs each test account in once and keeps its session for the other projects.
    // Retried: right after the stack starts, the API's seeding signs the test accounts out once more.
    { name: "setup", testMatch: /auth\.setup\.ts/, retries: 2 },
    { name: "desktop", use: { ...devices["Desktop Chrome"], storageState: player }, dependencies: ["setup"] },
    // The bottom bar and phone layouts.
    { name: "phone", use: { ...devices["Pixel 7"], storageState: player }, dependencies: ["setup"], testMatch: /(menu|help)\.spec\.ts/ },
  ],
})
