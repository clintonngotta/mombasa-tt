import { expect, test } from "@playwright/test"

// Teams (REQ-057): players who play together without a training place of their own. Nothing here saves
// anything: a team can't be deleted, so forming one is covered by the API tests.

test("forming a team asks for a name and a home town, and no place to find", async ({ page }) => {
  await page.goto("/team/new")
  await expect(page.getByRole("heading", { level: 1, name: "Form a team" })).toBeVisible()
  await expect(page.getByRole("textbox", { name: "Team name" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Form team" })).toBeVisible()
  // A club's form has directions and a map position; a team's has neither, and no choice of type.
  await expect(page.getByRole("group", { name: "Type" })).toHaveCount(0)
  await expect(page.getByLabel("Directions")).toHaveCount(0)
  await page.goto("/club/new")
  await expect(page.getByRole("heading", { level: 1, name: "Register an organization" })).toBeVisible()
  await expect(page.getByLabel("Directions")).toBeVisible()
  await expect(page.getByRole("radio", { name: "Team" })).toHaveCount(0)
})

test("finding a team searches teams only, with no Near me", async ({ page }) => {
  await page.goto("/team/find")
  await expect(page.getByRole("heading", { level: 1, name: "Find a team" })).toBeVisible()
  await expect(page.getByRole("navigation", { name: "What to find" }).getByRole("link", { name: "Teams" })).toHaveAttribute("aria-current", "page")
  await expect(page.getByRole("button", { name: /Near me/ })).toHaveCount(0)
  const asked = page.waitForRequest((request) => request.url().includes("/api/v1/organizations/?"))
  await page.getByRole("searchbox").fill("zz")
  await page.getByRole("button", { name: "Search" }).click()
  const url = new URL((await asked).url())
  expect(url.searchParams.getAll("kind")).toEqual(["team"])
})

test("rankings list teams between clubs and geography", async ({ page }) => {
  await page.goto("/rankings")
  const tabs = page.getByRole("group", { name: "Rankings" }).getByRole("button")
  await expect(tabs).toHaveText(["Players", "Clubs", "Teams", "Geography"])
  await tabs.filter({ hasText: "Teams" }).click()
  await expect(page.getByRole("heading", { level: 2, name: "Singles · Teams" })).toBeVisible()
})
