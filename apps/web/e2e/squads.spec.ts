import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Representative squads (REQ-050). A draft squad can be deleted, so this spec makes one, checks the
// rotation is offered, and removes it again. Publishing and answering are covered by the API tests.
const TITLE = "E2E away open"

test("a player sees their own squads page and no selector controls", async ({ page }) => {
  await page.goto("/squads")
  await expect(page.getByRole("heading", { level: 1, name: "My squads" })).toBeVisible()
  await expect(page.getByText("Only you see this list.")).toBeVisible()
  await page.goto("/club/squads")
  await expect(page.getByRole("button", { name: "New squad" })).toHaveCount(0)
})

test.describe("whoever runs competitions", () => {
  test.use({ storageState: sessionFile("admin") })

  test("drafts a squad, is offered the rotation, and deletes the draft", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop", "Changes shared data, so it runs in one project only.")
    await page.goto("/club/squads")
    // A draft left by an earlier run that failed: remove it first.
    const stale = page.getByRole("link", { name: new RegExp(TITLE) })
    await expect(page.getByRole("button", { name: "New squad" })).toBeVisible()
    while ((await stale.count()) > 0) {
      await stale.first().click()
      await page.getByRole("button", { name: "Delete draft" }).click()
      await expect(page.getByRole("heading", { level: 1, name: "Squads" })).toBeVisible()
    }
    await page.getByRole("button", { name: "New squad" }).click()
    await page.getByLabel("Tournament").fill(TITLE)
    const soon = new Date(Date.now() + 30 * 86_400_000).toISOString().slice(0, 10)
    await page.getByLabel("Starts").fill(soon)
    await page.getByLabel("Slot 1", { exact: true }).fill("Team")
    await page.getByLabel("Players").fill("2")
    await page.getByRole("button", { name: "Save draft" }).click()

    await expect(page.getByRole("heading", { level: 1, name: TITLE })).toBeVisible()
    await expect(page.getByText("Draft: nobody has been told")).toBeVisible()
    const team = page.getByRole("region", { name: "Team" })
    await expect(team.getByRole("heading", { name: "Pick next, in rotation" })).toBeVisible()
    await expect(team.getByText("recommended").first()).toBeVisible()
    // Nothing to publish until someone is picked.
    await expect(page.getByRole("button", { name: "Publish and tell the players" })).toBeDisabled()

    await page.getByRole("button", { name: "Delete draft" }).click()
    await expect(page.getByRole("heading", { level: 1, name: "Squads" })).toBeVisible()
    await expect(page.getByRole("link", { name: new RegExp(TITLE) })).toHaveCount(0)
  })
})
