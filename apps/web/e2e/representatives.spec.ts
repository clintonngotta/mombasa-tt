import { expect, test, type Browser } from "@playwright/test"
import { apiGet, sessionFile, type Account } from "./accounts.ts"

// A club admin nominates a member to the region's body, the body's admin accepts, and the club recalls
// them (REQ-045). It changes data the test logins share, so it runs once, at desktop width, and puts
// things back: before and after, every open nomination of the test club is withdrawn.
test.describe.configure({ mode: "serial" })

type Row = { id: string; status: string; person: { display_name: string } }
type Listing = { body: { id: string; name: string } | null; sent: Row[] }
type Me = { results: { organization: { id: string; name: string } }[] }

async function signedIn(browser: Browser, baseURL: string | undefined, account: Account) {
  return browser.newContext({ storageState: sessionFile(account), baseURL })
}

async function clubId(request: import("@playwright/test").APIRequestContext) {
  const mine = await apiGet<Me>(request, "/me/memberships/")
  const club = mine.results.find((m) => m.organization.name === "Mombasa Dev TT Club")
  if (!club) throw new Error("The test admin has no Mombasa Dev TT Club; run seed_dev.")
  return club.organization.id
}

async function withdrawAll(browser: Browser, baseURL: string | undefined) {
  const context = await signedIn(browser, baseURL, "admin")
  const club = await clubId(context.request)
  const listing = await apiGet<Listing>(context.request, `/organizations/${club}/representatives/`)
  const csrf = (await context.cookies()).find((cookie) => cookie.name === "csrftoken")?.value ?? ""
  for (const row of listing.sent.filter((r) => r.status === "pending" || r.status === "accepted")) {
    const response = await context.request.post(`/api/v1/organizations/${club}/representatives/${row.id}/withdraw/`, { headers: { "X-CSRFToken": csrf }, data: {} })
    expect(response.ok(), `withdrawing ${row.person.display_name}`).toBe(true)
  }
  await context.close()
  return listing.body
}

test("a club sends a representative, the body accepts, the club recalls", async ({ browser, baseURL }, info) => {
  test.skip(info.project.name !== "desktop", "Changes shared data, so it runs in one project only.")
  const body = await withdrawAll(browser, baseURL)
  test.skip(!body, "The dev region has no body; run seed_dev.")

  // The club admin nominates the test player.
  const club = await signedIn(browser, baseURL, "admin")
  const admin = await club.newPage()
  await admin.goto("/club/representatives")
  await expect(admin.getByRole("heading", { level: 1, name: "Representatives" })).toBeVisible()
  await expect(admin.getByRole("heading", { name: `Sent to ${body!.name}` })).toBeVisible()
  await admin.getByLabel("Find a member").fill("Test Player")
  await admin.getByRole("button", { name: "Nominate Test Player" }).click()
  const sent = admin.getByRole("list", { name: "Representatives and nominations" })
  await expect(sent.getByText("Test Player")).toBeVisible()
  await expect(sent.getByText(/Waiting for a decision/)).toBeVisible()

  // The body's admin sees a name and a club, and accepts.
  const region = await signedIn(browser, baseURL, "regional")
  const officer = await region.newPage()
  await officer.goto("/club/representatives")
  const waiting = officer.getByRole("list", { name: "Nominations to decide" })
  await expect(waiting.getByText("Test Player")).toBeVisible()
  await expect(waiting.getByText(/Mombasa Dev TT Club/)).toBeVisible()
  await expect(officer.getByText("player@mombasa-tt.test")).toHaveCount(0)
  await officer.getByRole("button", { name: "Accept Test Player for Mombasa Dev TT Club" }).click()
  await expect(officer.getByRole("list", { name: "Current representatives" }).getByText("Test Player")).toBeVisible()
  await expect(waiting.getByText("Test Player")).toHaveCount(0)
  await region.close()

  // The club sees them as its representative and recalls them.
  await admin.reload()
  await expect(sent.getByText(/· Representative/)).toBeVisible()
  await admin.getByRole("button", { name: "Recall Test Player" }).click()
  await expect(sent.getByText("Test Player")).toHaveCount(0)
  await expect(admin.getByText("Nobody represents you there yet.")).toBeVisible()
  await club.close()
})

test("a plain member reads who represents the club and can't nominate", async ({ browser, baseURL }, info) => {
  test.skip(info.project.name !== "desktop", "Runs with the test above.")
  const context = await signedIn(browser, baseURL, "player")
  const page = await context.newPage()
  await page.goto("/club/representatives")
  await expect(page.getByRole("heading", { level: 1, name: "Representatives" })).toBeVisible()
  await expect(page.getByRole("heading", { name: /^Sent to / })).toBeVisible()
  await expect(page.getByLabel("Find a member")).toHaveCount(0)
  await context.close()
})

test.afterAll(async ({ browser }, info) => {
  if (info.project.name === "desktop") await withdrawAll(browser, info.project.use.baseURL)
})
