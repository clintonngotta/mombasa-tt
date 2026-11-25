# End-to-end tests (Playwright)

Real-browser tests of the web app against a running local stack. They cover the menu and the Tournaments
tab, Home, the help centre, club representatives, drafting a meeting, events for you, feedback forms, training rules, squads, absence penalties, and finding clubs and places to play by city and by distance (with a faked
device location).

## Run them

```sh
# 1. From the repository root: the stack, with the test logins seeded (web :8080, API :8020).
docker compose up -d
docker compose exec api python manage.py seed_dev

# 2. From apps/web. The first time, also download the browser: pnpm exec playwright install chromium
pnpm test:e2e
```

- `pnpm test:e2e --ui` opens Playwright's runner; `pnpm test:e2e --headed` shows the browser.
- `pnpm test:e2e e2e/nearby.spec.ts` runs one file; `--project=phone` runs the phone-sized checks only.
- `E2E_BASE_URL=http://localhost:5173 pnpm test:e2e` tests another running copy, such as your own dev server.
- After a failure, `pnpm exec playwright show-report` opens the report with a trace and a screenshot.

The tests never start or stop a server. Stop the stack yourself with `docker compose stop` when done.

## Writing more

- Sign in by reusing a saved session: `test.use({ storageState: sessionFile("admin") })`. The accounts are
  the development test logins in `accounts.ts`; they exist only where `DJANGO_DEBUG` is on.
- Find things the way a person does: by role and name (`getByRole("button", { name: "Near me" })`), not by
  CSS class.
- Don't depend on data another test creates. Read what you need from the API (`apiGet`), or create it in the
  test and say so.
- Tests that change data shared by the test logins should put it back, so the suite can run again.
