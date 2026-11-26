import { expect, test } from "@playwright/test"
import { apiGet, sessionFile } from "./accounts.ts"

// The entry desk's player picker (REQ-003). This only reads: adding a player makes a guest that
// can't be removed, so creating, inviting and joining are covered by the API tests.
type Me = { results: { organization: { id: string; name: string } }[] }
type Hosted = { results: { id: string }[] }
type Detail = { id: string; status: string; events: { id: string; status: string }[] }

test.describe("whoever runs competitions", () => {
  test.use({ storageState: sessionFile("admin") })

  test("chooses between finding a player and adding a new one at the entry desk", async ({ page }) => {
    await page.goto("/home")
    const mine = await apiGet<Me>(page.request, "/me/memberships/")
    const club = mine.results.find((m) => m.organization.name === "Mombasa Dev TT Club")
    if (!club) throw new Error("The test admin has no Mombasa Dev TT Club; run seed_dev.")
    const hosted = await apiGet<Hosted>(page.request, `/organizations/${club.organization.id}/tournaments/`)
    const open = page.getByRole("button", { name: "Add an entry" })
    let found = false
    for (const { id } of hosted.results) {
      const t = await apiGet<Detail>(page.request, `/tournaments/${id}/`)
      for (const event of t.events ?? []) {
        await page.goto(`/tournaments/${t.id}/events/${event.id}/entries`)
        await expect(page.getByRole("heading", { name: "Entry desk" })).toBeVisible()
        if ((await open.count()) > 0) {
          found = true
          break
        }
      }
      if (found) break
    }
    test.skip(!found, "The test club has no event that is taking entries.")
    await open.click()

    // Both ways are offered before anything is searched.
    const find = page.getByRole("button", { name: "Find a player", exact: true })
    const addNew = page.getByRole("button", { name: "Add a new player" })
    await expect(find).toHaveAttribute("aria-pressed", "true")
    await expect(page.getByPlaceholder("Find a player by name")).toBeVisible()

    await addNew.click()
    await expect(addNew).toHaveAttribute("aria-pressed", "true")
    await expect(page.getByPlaceholder("Find a player by name")).toHaveCount(0)
    const add = page.getByRole("button", { name: "Add without inviting" })
    await expect(add).toBeDisabled()
    await page.getByLabel("Name").fill("Amina Test")
    await expect(add).toBeEnabled()
    await page.getByLabel("Email").fill("amina@example.com")
    await expect(page.getByRole("button", { name: "Add and invite" })).toBeEnabled()

    await find.click()
    await expect(page.getByPlaceholder("Find a player by name")).toBeVisible()
  })
})
