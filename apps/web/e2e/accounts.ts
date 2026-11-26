import { expect, type APIRequestContext, type Page } from "@playwright/test"

/** The development test logins the API seeds (`manage.py seed_dev`). They
 * exist only where DJANGO_DEBUG is on, so these tests can never run against production. */
const PASSWORD = process.env.E2E_PASSWORD ?? "mombasa-tt-dev"
export const ACCOUNTS = {
  player: "player@mombasa-tt.test",
  admin: "admin@mombasa-tt.test",
  facility: "facility@mombasa-tt.test",
  regional: "regional@mombasa-tt.test",
} as const
export type Account = keyof typeof ACCOUNTS
export const sessionFile = (account: Account) => `e2e/.auth/${account}.json`

export async function logIn(page: Page, account: Account) {
  await page.goto("/login")
  // Wait for the page to go quiet, then type until both fields hold what we mean to send.
  await page.waitForLoadState("networkidle")
  const email = page.getByLabel("Email or phone number")
  const password = page.getByLabel("Password", { exact: true })
  await expect(async () => {
    await email.fill(ACCOUNTS[account])
    await password.fill(PASSWORD)
    await page.waitForTimeout(500)
    await expect(email).toHaveValue(ACCOUNTS[account])
    await expect(password).toHaveValue(PASSWORD)
  }).toPass({ timeout: 10_000 })
  await page.getByRole("button", { name: "Log in", exact: true }).click()
  // Wait for the session rather than for the page to move on: right after the API restarts the app reloads
  // itself once, which lands back on this page although the login worked. This also makes sure another
  // account's session is never saved under this one's name.
  await expect(async () => {
    const me = await page.request.get("/api/v1/auth/me/")
    expect(me.ok()).toBe(true)
    expect(((await me.json()) as { email?: string }).email).toBe(ACCOUNTS[account])
  }).toPass({ timeout: 15_000 })
}

/** GET an API path with the signed-in session of `request` (a page's or a context's). */
export async function apiGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(`/api/v1${path}`)
  if (!response.ok()) throw new Error(`GET ${path} answered ${response.status()}`)
  return response.json() as Promise<T>
}
