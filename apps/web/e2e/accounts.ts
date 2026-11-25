import type { APIRequestContext, Page } from "@playwright/test"

/** The development test logins the API seeds (`manage.py seed_dev`; mirrors src/lib/devAccounts.ts). They
 * exist only where DJANGO_DEBUG is on, so these tests can never run against production. */
const PASSWORD = process.env.E2E_PASSWORD ?? "mombasa-tt-dev"
export const ACCOUNTS = {
  player: "player@mombasa-tt.test",
  admin: "admin@mombasa-tt.test",
  facility: "facility@mombasa-tt.test",
} as const
export type Account = keyof typeof ACCOUNTS
export const sessionFile = (account: Account) => `e2e/.auth/${account}.json`

export async function logIn(page: Page, account: Account) {
  await page.goto("/login")
  await page.getByLabel("Email or phone number").fill(ACCOUNTS[account])
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD)
  await page.getByRole("button", { name: "Log in", exact: true }).click()
  await page.waitForURL((url) => !url.pathname.startsWith("/login"))
}

/** GET an API path with the signed-in session of `request` (a page's or a context's). */
export async function apiGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`/api/v1${path}`)
  if (!response.ok()) throw new Error(`GET ${path} answered ${response.status()}`)
  return response.json() as Promise<T>
}
