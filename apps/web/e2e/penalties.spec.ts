import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Absence penalties (REQ-054). These only read: an issued penalty and its fine stay on record, so rules,
// proposals, issuing, waiving and appeals are covered by the API tests.
test("a member has their own penalties page and can't open the officials' one", async ({ page }) => {
  await page.goto("/penalties")
  await expect(page.getByRole("heading", { level: 1, name: "My penalties" })).toBeVisible()
  await expect(page.getByText("Only you and your club's officials see them.")).toBeVisible()
  await page.goto("/club/penalties")
  await expect(page.getByRole("alert")).toContainText("governance staff")
  await expect(page.getByRole("button", { name: "Save rules" })).toHaveCount(0)
})

test.describe("governance staff", () => {
  test.use({ storageState: sessionFile("admin") })

  test("see the three kinds of absence and that nothing is issued by itself", async ({ page }) => {
    await page.goto("/club/penalties")
    for (const kind of ["Training accepted and missed", "Tournament entry not checked in", "Squad place not taken up"]) {
      await expect(page.getByRole("group", { name: kind })).toBeVisible()
    }
    await expect(page.getByText("The app proposes; nothing reaches a member until you issue it.")).toBeVisible()
    await expect(page.getByRole("button", { name: /Look for absences in the last 90 days/ })).toBeVisible()
  })
})
