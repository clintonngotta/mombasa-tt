import { expect, test } from "@playwright/test"
import { apiGet, sessionFile } from "./accounts.ts"

// A club admin drafts a meeting, changes its agenda, adds a document and deletes the draft (REQ-046).
// Everything stays a draft, so nobody is invited or told, and the test removes what it made.
test.use({ storageState: sessionFile("admin") })

const TITLE = "E2E planning meeting"
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n")

type Me = { results: { organization: { id: string; name: string } }[] }
type Meeting = { id: string; title: string; status: string }

async function removeDrafts(page: import("@playwright/test").Page) {
  const mine = await apiGet<Me>(page.request, "/me/memberships/")
  const club = mine.results.find((m) => m.organization.name === "Mombasa Dev TT Club")
  if (!club) throw new Error("The test admin has no Mombasa Dev TT Club; run seed_dev.")
  const meetings = await apiGet<Meeting[]>(page.request, `/organizations/${club.organization.id}/meetings/`)
  const csrf = (await page.context().cookies()).find((cookie) => cookie.name === "csrftoken")?.value ?? ""
  for (const meeting of meetings.filter((m) => m.title === TITLE && m.status === "draft")) {
    const gone = await page.request.delete(`/api/v1/organizations/${club.organization.id}/meetings/${meeting.id}/`, { headers: { "X-CSRFToken": csrf } })
    expect(gone.ok(), "removing a draft left by an earlier run").toBe(true)
  }
}

test("staff draft a meeting, change the agenda, add a document and delete it", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "Changes shared data, so it runs in one project only.")
  await page.goto("/club/meetings")
  await expect(page.getByRole("heading", { level: 1, name: "Meetings" })).toBeVisible()
  await removeDrafts(page)

  await page.getByRole("button", { name: "Call a meeting" }).click()
  await page.getByLabel("Title").fill(TITLE)
  await page.getByLabel("Starts").fill("2031-03-01T18:00")
  await page.getByLabel("Ends").fill("2031-03-01T20:00")
  await page.getByLabel("Item 1", { exact: true }).fill("Accounts")
  await page.getByRole("button", { name: "Save draft" }).click()

  await expect(page.getByRole("heading", { level: 1, name: TITLE })).toBeVisible()
  await expect(page.getByText("Draft: only governance staff see it.")).toBeVisible()
  await expect(page.getByRole("heading", { name: "Minutes" })).toHaveCount(0) // nothing to minute before it is held

  // Change the agenda: the first item gets a presenter and a second one is added.
  await page.getByRole("button", { name: "Change the meeting" }).click()
  await page.getByLabel("Presenter").fill("Treasurer")
  await page.getByRole("button", { name: "Add an item" }).click()
  await page.getByLabel("Item 2", { exact: true }).fill("Coast Open")
  await page.getByRole("button", { name: "Save changes" }).click()
  const agenda = page.getByRole("region", { name: "Agenda" })
  await expect(agenda.getByText("Accounts · Treasurer")).toBeVisible()
  await expect(agenda.getByText("Coast Open")).toBeVisible()

  // A paper for the first agenda item.
  await page.getByLabel("Title").fill("Accounts 2030")
  await page.getByLabel("PDF").setInputFiles({ name: "accounts.pdf", mimeType: "application/pdf", buffer: PDF })
  await page.getByRole("button", { name: "Add document" }).click()
  await expect(page.getByRole("button", { name: "Accounts 2030 Download PDF" })).toBeVisible()
  await page.getByRole("button", { name: "Remove Accounts 2030" }).click()
  await expect(page.getByText("No documents yet.")).toBeVisible()

  await page.getByRole("button", { name: "Delete draft" }).click()
  await expect(page.getByRole("heading", { level: 1, name: "Meetings" })).toBeVisible()
  await expect(page.getByText(TITLE)).toHaveCount(0)
})

test("your action items page opens from anywhere", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "Runs with the test above.")
  await page.goto("/action-items")
  await expect(page.getByRole("heading", { level: 1, name: "My action items" })).toBeVisible()
})
