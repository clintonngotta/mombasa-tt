import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Annual financial reports (REQ-041). These only read: a published report stays on record, so drafting,
// publishing, amending and the exports are covered by the API tests.
test("a member reads the reports page and can't draft a report", async ({ page }) => {
  await page.goto("/club/finance/reports")
  await expect(page.getByRole("heading", { level: 1, name: "Annual reports" })).toBeVisible()
  await expect(page.getByRole("button", { name: /Draft the report/ })).toHaveCount(0)
  await expect(page.getByText("Financial year ends at the end of")).toHaveCount(0)
})

test.describe("a finance manager", () => {
  test.use({ storageState: sessionFile("admin") })

  test("sees the year end and can draft the last finished year", async ({ page }) => {
    await page.goto("/club/finance/reports")
    await expect(page.getByText("Financial year ends at the end of")).toBeVisible()
    await expect(page.getByRole("button", { name: /Draft the report for the last finished year/ })).toBeEnabled()
  })
})
