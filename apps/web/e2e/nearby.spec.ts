import { expect, test, type Page, type Request } from "@playwright/test"
import { apiGet, sessionFile } from "./accounts.ts"

type Membership = { organization: { id: string; name: string; latitude: number | null; longitude: number | null } }
type Venue = { name: string; latitude: number | null; longitude: number | null; profile: string }
type Paged<T> = { results: T[] }

/** Where the test club and the test facility's branch really are in this database, read as their own staff. */
async function seededPlaces(browser: import("@playwright/test").Browser, baseURL: string) {
  const asAdmin = await browser.newContext({ storageState: sessionFile("admin"), baseURL })
  const clubs = await apiGet<Paged<Membership>>(asAdmin.request, "/me/memberships/")
  await asAdmin.close()
  const asFacility = await browser.newContext({ storageState: sessionFile("facility"), baseURL })
  const facility = (await apiGet<Paged<Membership>>(asFacility.request, "/me/memberships/")).results[0]?.organization
  const branches = facility ? await apiGet<Venue[]>(asFacility.request, `/organizations/${facility.id}/venues/`) : []
  await asFacility.close()
  return {
    club: clubs.results.map((m) => m.organization).find((o) => o.latitude !== null),
    branch: branches.find((v) => v.latitude !== null && v.profile === "public"),
  }
}

const nearbyCalls = (page: Page) => {
  const calls: Request[] = []
  page.on("request", (request) => {
    if (request.url().includes("/nearby/")) calls.push(request)
  })
  return calls
}

test("clubs near me, within 300 m, with the position kept out of every address", async ({ browser, baseURL, context, page }) => {
  const { club } = await seededPlaces(browser, baseURL!)
  test.skip(!club, "No test club has a map position: run `manage.py seed_dev`.")
  await context.grantPermissions(["geolocation"])
  await context.setGeolocation({ latitude: club!.latitude!, longitude: club!.longitude!, accuracy: 10 })
  const calls = nearbyCalls(page)

  await page.goto("/club/find")
  await page.getByRole("button", { name: "Near me" }).click()
  await page.getByRole("group", { name: "How far to look" }).getByRole("button", { name: "300 m" }).click()
  const found = page.getByRole("region", { name: "Clubs found" })
  await expect(found.getByText(club!.name)).toBeVisible()
  await expect(found.getByText(/\d+ m away/)).toBeVisible()
  await expect(page.getByText("Your location is used for this search only.", { exact: false })).toBeVisible()

  // The position travels in a request body, never in the page's or the API's address.
  expect(calls.length).toBeGreaterThan(0)
  for (const call of calls) {
    expect(call.method()).toBe("POST")
    expect(new URL(call.url()).search).toBe("")
    expect(call.postDataJSON()).toMatchObject({ radius_m: expect.any(Number), latitude: expect.any(Number) })
  }
  expect(page.url()).not.toContain(String(club!.latitude))

  // Stopping goes back to the ordinary search.
  await page.getByRole("button", { name: "Stop" }).click()
  await expect(page.getByRole("button", { name: "Near me" })).toBeVisible()
})

test("far from every club, a 300 m search says so and suggests what to do", async ({ context, page }) => {
  await context.grantPermissions(["geolocation"])
  // The middle of the South Atlantic.
  await context.setGeolocation({ latitude: -30, longitude: -15, accuracy: 10 })
  await page.goto("/club/find")
  await page.getByRole("button", { name: "Near me" }).click()
  await page.getByRole("group", { name: "How far to look" }).getByRole("button", { name: "300 m" }).click()
  await expect(page.getByText("No club has a map location within 300 m of you.", { exact: false })).toBeVisible()
})

test("when location is refused the page explains and city search still works", async ({ browser, baseURL, page }) => {
  const { club } = await seededPlaces(browser, baseURL!)
  await page.goto("/club/find")
  await page.getByRole("button", { name: "Near me" }).click()
  await expect(page.getByRole("alert")).toContainText(/Location is switched off|couldn't work out|took too long/)

  test.skip(!club, "No test club: run `manage.py seed_dev`.")
  await page.getByLabel("Club name, city or town").fill("Mombasa")
  await page.getByRole("button", { name: "Search", exact: true }).click()
  await expect(page.getByRole("region", { name: "Clubs found" }).getByText(club!.name)).toBeVisible()
  await expect(page).toHaveURL(/name=Mombasa/)
})

test("places to play near me, and switching between the two finders", async ({ browser, baseURL, context, page }) => {
  const { branch } = await seededPlaces(browser, baseURL!)
  test.skip(!branch, "The test facility has no public branch with a map position: run `manage.py seed_dev`.")
  await context.grantPermissions(["geolocation"])
  await context.setGeolocation({ latitude: branch!.latitude!, longitude: branch!.longitude!, accuracy: 10 })

  await page.goto("/club/find")
  await page.getByRole("navigation", { name: "What to find" }).getByRole("link", { name: "Places to play" }).click()
  await expect(page.getByRole("heading", { level: 1, name: "Find a place to play" })).toBeVisible()
  await page.getByRole("button", { name: "Near me" }).click()
  await page.getByRole("group", { name: "How far to look" }).getByRole("button", { name: "300 m" }).click()
  const found = page.getByRole("region", { name: "Facilities found" })
  await expect(found.getByRole("link", { name: new RegExp(branch!.name) })).toBeVisible()
  await expect(found.getByText(/\d+ m away/)).toBeVisible()
})
