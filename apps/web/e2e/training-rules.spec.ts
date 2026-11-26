import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Training rules (REQ-052). These only read, so the club's own rules are left as they are; checking in by
// location is covered by the API tests (range, accuracy, window, a moved session).
test("a member reads how checking in works and can't change the rules", async ({ page }) => {
  await page.goto("/club/training-rules")
  await expect(page.getByRole("heading", { level: 1, name: "Training rules" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Weekly schedule" })).toBeVisible()
  await expect(page.getByText(/You check in on your phone, within \d+ m of where the session is held\./)).toBeVisible()
  await expect(page.getByText("The club sees how far away you were, not where.")).toBeVisible()
  await expect(page.getByRole("button", { name: "Change the rules" })).toHaveCount(0)
})

test.describe("whoever runs training", () => {
  test.use({ storageState: sessionFile("admin") })

  test("can open the rules to change them, with the 300 m limit shown", async ({ page }) => {
    await page.goto("/club/training-rules")
    await page.getByRole("button", { name: "Change the rules" }).click()
    await expect(page.getByLabel("How close (metres)")).toHaveAttribute("max", "300")
    await expect(page.getByText("At most 300 m. Smaller is stricter.")).toBeVisible()
    await page.getByRole("button", { name: "Cancel" }).click()
    await expect(page.getByRole("button", { name: "Change the rules" })).toBeVisible()
  })
})
