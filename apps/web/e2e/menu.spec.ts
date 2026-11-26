import { expect, test } from "@playwright/test"
import { sessionFile } from "./accounts.ts"

// Runs at desktop width (sidebar) and phone width (bottom bar): whichever "Main" menu is on screen.
const menu = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "Main" }).filter({ visible: true })

test("Tournaments is in the menu and opens the tournaments page", async ({ page }) => {
  await page.goto("/home")
  const link = menu(page).getByRole("link", { name: "Tournaments", exact: true })
  await expect(link).toBeVisible()
  await link.click()
  await expect(page).toHaveURL(/\/tournaments$/)
  await expect(page.getByRole("heading", { level: 1, name: "Tournaments" })).toBeVisible()
  await expect(link).toHaveAttribute("aria-current", "page")
  // Only one entry is lit at a time.
  await expect(menu(page).locator('[aria-current="page"]')).toHaveCount(1)
})

test("the phone bar shows every label in full", async ({ page }, info) => {
  test.skip(info.project.name !== "phone", "The bottom bar only shows at phone width.")
  // The narrowest phone the app is laid out for.
  await page.setViewportSize({ width: 360, height: 740 })
  await page.goto("/home")
  const labels = menu(page).getByRole("link").locator("span")
  await expect(labels.filter({ hasText: "Tournaments" })).toBeVisible()
  for (const label of await labels.all()) {
    const cut = await label.evaluate((el) => el.scrollWidth > el.clientWidth)
    expect(cut, `"${await label.textContent()}" is cut off`).toBe(false)
  }
})

test("home offers the common tasks", async ({ page }) => {
  await page.goto("/home")
  const shortcuts = page.getByRole("navigation", { name: "Shortcuts" })
  // The test player belongs to a club, so Home points at it rather than offering to join one.
  await expect(shortcuts.getByRole("link", { name: /Your club/ })).toBeVisible()
  await expect(shortcuts.getByRole("link", { name: /Join a club/ })).toHaveCount(0)
  await expect(shortcuts.getByRole("link", { name: /Tournaments/ })).toBeVisible()
  await expect(shortcuts.getByRole("link", { name: /Find a place to play/ })).toBeVisible()
  await shortcuts.getByRole("link", { name: /Help/ }).click()
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible()
})

test.describe("whoever runs competitions", () => {
  test.use({ storageState: sessionFile("admin") })

  test("starts a new tournament from the Tournaments tab", async ({ page }) => {
    await page.goto("/tournaments")
    await page.getByRole("link", { name: "New tournament" }).click()
    await expect(page).toHaveURL(/\/club\/tournaments\/new$/)
    await expect(page.getByRole("heading", { level: 1, name: "New tournament" })).toBeVisible()
    await expect(page.getByRole("textbox", { name: "Name", exact: true })).toBeVisible()
    // The organizer's pages still light up Tournaments, not Club.
    await expect(menu(page).locator('[aria-current="page"]')).toHaveText(/Tournaments|More/)
  })
})

test("a player doesn't see New tournament", async ({ page }) => {
  await page.goto("/tournaments")
  await expect(page.getByRole("heading", { name: "Find a tournament" })).toBeVisible()
  await expect(page.getByRole("link", { name: "New tournament" })).toHaveCount(0)
})
