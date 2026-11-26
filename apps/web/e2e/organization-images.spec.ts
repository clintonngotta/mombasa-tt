import { expect, test } from "@playwright/test"
import { apiGet, sessionFile } from "./accounts.ts"

// Pictures a club, team or facility shows of itself (REQ-058). The test adds one to the test club and
// removes it again, so the club is left as it was.

// A 2 × 2 red PNG.
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGP8z8DAwMDAxAADAA0GAQPdGUW7AAAAAElFTkSuQmCC",
  "base64",
)
const CAPTION = "E2E league night"

test.use({ storageState: sessionFile("admin") })

test("an admin adds a picture, a player sees it on the club's profile, and the admin removes it", async ({ page, browser }) => {
  await page.goto("/club/profile")
  const pictures = page.getByRole("region", { name: "Pictures" })
  await expect(pictures.getByRole("button", { name: "Add a picture" })).toBeVisible()
  // Left over from a run that failed half way: start clean.
  while (await pictures.getByRole("button", { name: new RegExp(`^Remove picture .*${CAPTION}`) }).count()) {
    await pictures.getByRole("button", { name: new RegExp(`^Remove picture .*${CAPTION}`) }).first().click()
    await page.waitForTimeout(500)
  }
  await pictures.getByLabel(/Caption for the next picture/).fill(CAPTION)
  await pictures.locator('input[type="file"]').setInputFiles({ name: "night.png", mimeType: "image/png", buffer: PNG })
  const tile = pictures.getByRole("button", { name: `View ${CAPTION}` })
  await expect(tile).toBeVisible()
  await expect(tile.locator("img")).toHaveJSProperty("complete", true)
  // It really loaded through its signed link, not just got a tile.
  expect(await tile.locator("img").evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth)).toBeGreaterThan(0)

  const memberships = await apiGet<{ results: { organization: { id: string; kind: string } }[] }>(page.request, "/me/memberships/?page_size=50")
  const club = memberships.results.find((m) => m.organization.kind !== "team")!.organization.id

  // A player (another account) sees it on the profile, and can't change it.
  const context = await browser.newContext({ storageState: sessionFile("player") })
  const visitor = await context.newPage()
  await visitor.goto(`/club/find/${club}`)
  const shown = visitor.getByRole("region", { name: "Pictures" })
  await expect(shown.getByRole("button", { name: `View ${CAPTION}` })).toBeVisible()
  await expect(shown.getByRole("button", { name: "Add a picture" })).toHaveCount(0)
  await expect(shown.getByRole("button", { name: /^Remove picture/ })).toHaveCount(0)
  await shown.getByRole("button", { name: `View ${CAPTION}` }).click()
  await expect(visitor.getByRole("dialog").getByRole("img", { name: CAPTION })).toBeVisible()
  await context.close()

  await pictures.getByRole("button", { name: new RegExp(`^Remove picture .*${CAPTION}`) }).click()
  await expect(tile).toHaveCount(0)
})
