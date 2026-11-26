import { expect, test } from "@playwright/test"
import { apiGet } from "./accounts.ts"

// A tournament's results announcements as a PDF (REQ-043). Read-only: it downloads the sheet of a
// tournament that is already published, whatever it holds.
type Listing = { results: { id: string; name: string }[] }

test("anyone who sees a tournament can download its results as a PDF", async ({ page }) => {
  await page.goto("/tournaments")
  const found = await apiGet<Listing>(page.request, "/tournaments/?when=past")
  const upcoming = await apiGet<Listing>(page.request, "/tournaments/")
  const tournament = [...found.results, ...upcoming.results][0]
  test.skip(!tournament, "No published tournament to read.")
  const sheet = await page.request.get(`/api/v1/tournaments/${tournament.id}/announcements/export.pdf`)
  expect(sheet.ok()).toBe(true)
  expect(sheet.headers()["content-type"]).toBe("application/pdf")
  const body = await sheet.body()
  expect(body.subarray(0, 8).toString()).toBe("%PDF-1.4")
  expect(body.toString("latin1")).toContain("Results announcements")
})
