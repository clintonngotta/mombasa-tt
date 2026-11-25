import { expect, test } from "@playwright/test"

// Help is for everyone, so these run signed out.
test.use({ storageState: { cookies: [], origins: [] } })

test("the help centre lists its topics and opens an answer", async ({ page }) => {
  await page.goto("/help")
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible()
  const topics = page.getByRole("navigation", { name: "Help topics" })
  for (const topic of ["Enter a tournament", "Follow matches", "Clubs", "Find clubs and places near you", "Run a tournament"]) {
    await expect(topics.getByRole("link", { name: topic, exact: true })).toBeVisible()
  }
  const question = page.getByText("How do I join a club?")
  await expect(page.getByText("then choose Request to join")).toBeHidden()
  await question.click()
  await expect(page.getByText("then choose Request to join")).toBeVisible()
})

test("searching help narrows to the matching answers and opens them", async ({ page }) => {
  await page.goto("/help")
  await page.getByLabel("Search help").fill("check in")
  await expect(page.getByText("How do I check in on the day?")).toBeVisible()
  await expect(page.getByText("Choose Check in now beside your entry.")).toBeVisible()
  await expect(page.getByText("How do I join a club?")).toBeHidden()
  await page.getByLabel("Search help").fill("zzzz nothing")
  await expect(page.getByText("Nothing matches")).toBeVisible()
})

test("a link to one answer opens it", async ({ page }) => {
  await page.goto("/help#near-me")
  await expect(page.getByText("Pick how far to look: 300 m, 1 km, 5 km, 10 km or 25 km.", { exact: false })).toBeVisible()
})

test("the welcome page links to help and to tournaments without an account", async ({ page }) => {
  await page.goto("/")
  await page.getByRole("link", { name: "Browse tournaments" }).click()
  await expect(page).toHaveURL(/\/tournaments$/)
  await expect(page.getByRole("heading", { level: 1, name: "Tournaments" })).toBeVisible()
  await expect(page.getByRole("heading", { name: "Find a tournament" })).toBeVisible()
})
