import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Outside income (REQ-051). A source that was never used can be deleted, so this spec adds one, checks it
// is offered when recording income, and deletes it. Recording income leaves a record for good, so that is
// covered by the API tests.
const NAME = "E2E county grant"

test("a member can't open the club's outside income", async ({ page }) => {
  await page.goto("/club/finance/external")
  await expect(page.getByRole("alert")).toContainText("finance staff")
  await expect(page.getByRole("button", { name: "Add source" })).toHaveCount(0)
})

test.describe("a finance manager", () => {
  test.use({ storageState: sessionFile("admin") })

  test("adds a source, sees it offered and the internal and external split, and deletes it", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop", "Changes shared data, so it runs in one project only.")
    await page.goto("/club/finance/external")
    const sources = page.getByRole("region", { name: "Sources" })
    await expect(page.getByRole("heading", { name: "Sources" })).toBeVisible()
    // Left by an earlier run that failed: remove it first.
    const stale = sources.getByRole("button", { name: `Delete ${NAME}` })
    if ((await stale.count()) > 0) await stale.click()
    await expect(sources.getByText(NAME)).toHaveCount(0)

    await page.getByLabel("New source").fill(NAME)
    await page.getByRole("button", { name: "Add source" }).click()
    await expect(sources.getByText(NAME)).toBeVisible()
    await page.getByRole("combobox", { name: "Source" }).first().click()
    await expect(page.getByRole("option", { name: NAME })).toBeVisible()
    await page.keyboard.press("Escape")
    const received = page.getByRole("region", { name: "Received" })
    await expect(received.getByText("Internal: from members")).toBeVisible()
    await expect(received.getByText("External: from outside")).toBeVisible()

    await sources.getByRole("button", { name: `Delete ${NAME}` }).click()
    await expect(sources.getByText(NAME)).toHaveCount(0)
  })
})
