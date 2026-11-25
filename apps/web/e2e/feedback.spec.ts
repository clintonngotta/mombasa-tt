import { expect, test } from "@playwright/test"
import { apiGet, sessionFile } from "./accounts.ts"

// Feedback forms (REQ-055). These only read: a sent form keeps its answers and can't be removed, so
// building, sending, answering and totals are covered by the API tests.
type Me = { results: { organization: { id: string; name: string } }[] }
type Hosted = { results: { id: string; name: string; status: string }[] }

async function aTournament(request: import("@playwright/test").APIRequestContext) {
  const mine = await apiGet<Me>(request, "/me/memberships/")
  const club = mine.results.find((m) => m.organization.name === "Mombasa Dev TT Club")
  if (!club) throw new Error("The test admin has no Mombasa Dev TT Club; run seed_dev.")
  const hosted = await apiGet<Hosted>(request, `/organizations/${club.organization.id}/tournaments/`)
  return hosted.results.find((t) => t.status !== "draft" && t.status !== "cancelled")
}

test.describe("whoever runs competitions", () => {
  test.use({ storageState: sessionFile("admin") })

  test("opens a tournament's feedback forms and can start one", async ({ page }) => {
    await page.goto("/home")
    const tournament = await aTournament(page.request)
    test.skip(!tournament, "The test club hosts no published tournament.")
    await page.goto(`/tournaments/${tournament!.id}/feedback`)
    await expect(page.getByRole("heading", { level: 1, name: "Feedback forms" })).toBeVisible()
    await expect(page.getByRole("heading", { name: "This tournament's forms" })).toBeVisible()
    // Nothing is made until a title is typed.
    await expect(page.getByRole("button", { name: "Make the form" })).toBeDisabled()
    await page.getByLabel("Title").fill("How was it?")
    await expect(page.getByRole("button", { name: "Make the form" })).toBeEnabled()
    await expect(page.getByRole("button", { name: "Make a template instead" })).toBeEnabled()
  })
})

test("a player is told a form isn't theirs to answer", async ({ page }) => {
  await page.goto("/feedback/00000000-0000-4000-8000-000000000000")
  await expect(page.getByRole("alert")).toBeVisible()
  await expect(page.getByRole("button", { name: "Send my answers" })).toHaveCount(0)
})
