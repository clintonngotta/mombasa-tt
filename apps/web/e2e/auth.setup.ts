import { existsSync } from "node:fs"
import { test as setup } from "@playwright/test"
import { ACCOUNTS, logIn, sessionFile, type Account } from "./accounts.ts"

// The API allows only a few logins a minute, so a session saved by an earlier run is used again while
// it still works. Delete e2e/.auth to force fresh logins.
for (const account of Object.keys(ACCOUNTS) as Account[]) {
  setup(`log in as the test ${account}`, async ({ browser, baseURL, page }) => {
    const file = sessionFile(account)
    if (existsSync(file)) {
      const saved = await browser.newContext({ storageState: file, baseURL })
      const me = await saved.request.get("/api/v1/auth/me/")
      const email = me.ok() ? ((await me.json()) as { email?: string }).email : undefined
      await saved.close()
      if (email === ACCOUNTS[account]) return
    }
    await logIn(page, account)
    await page.context().storageState({ path: file })
  })
}
