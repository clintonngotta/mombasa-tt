import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Events that invite you beyond your club's own activities (REQ-046). These only read: creating an event
// can't be undone (an activity is cancelled, never deleted), so that flow is covered by the API tests.
test("the events-for-you page opens and explains itself", async ({ page }) => {
  await page.goto("/invited")
  await expect(page.getByRole("heading", { level: 1, name: "Events for you" })).toBeVisible()
  await expect(page.getByText("Your club's own activities are on its schedule.")).toBeVisible()
  await page.getByRole("link", { name: "Home" }).first().click()
  await expect(page).toHaveURL(/\/home$/)
})

test.describe("whoever runs activities", () => {
  test.use({ storageState: sessionFile("admin") })

  test("can choose who an activity is for, beyond the members", async ({ page }) => {
    await page.goto("/club/activities")
    await page.getByRole("button", { name: "New activity" }).click()
    const audience = page.getByRole("group", { name: "Who it's for" })
    await expect(audience.getByText("People I name")).toBeVisible()
    await expect(audience.getByText("Every player on Coast TT")).toBeVisible()
    // A club has no representatives to invite; only a governing body does.
    await expect(audience.getByText("Representatives of clubs")).toHaveCount(0)
    await audience.getByText("People I name").click()
    await expect(page.getByPlaceholder("Find a player by name")).toBeVisible()
    await page.getByRole("button", { name: "Cancel" }).click()
  })
})
