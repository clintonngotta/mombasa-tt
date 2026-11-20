# Handoff prompt: continue Phase 1 release in Codex

Paste everything below the line into Codex, started at the repository root (`~/projects/mombasa-tt`).

---

You are continuing work on Coast TT (repository root: this folder). It is a table tennis club and tournament platform: a Django and Channels API in `services/api`, a React PWA in `apps/web`, and shared packages in `packages/`. Read these first:

- `AGENTS.md` (project rules)
- `docs/phase1-release-plan.md` (the plan you are executing)
- `docs/completion.md` (progress counts)
- `tasks.md`, `spec.md` and `test.md` (tasks, requirements, evaluations)

**Goal.** Take every remaining Phase 1 task to done, in the order of `docs/phase1-release-plan.md`, ending with a release PR from `dev` to `main`.

**State on 2026-11-20**
- **Current branch:** `feat/tournament-organizers` holds uncommitted TASK-117 work (tournament organizers, cover pictures, PDF documents). It is already ticked in tasks.md. The web typecheck and build pass. Confirm the full API suite (`uv run --env-file .env pytest`) passes, then commit it. That is step 0.1 of the plan.
- **Waiting to merge:** `feat/role-navigation` (TASK-116, commit 0b3c08f). It conflicts with TASK-117 in `apps/web/src/pages/region/RegionPage.tsx` and `apps/web/src/pages/coaching/CoachingTab.tsx`. `feat/welfare-dues-visits` (TASK-075) is also waiting.
- **Local stack:**
  - Postgres runs on 127.0.0.1:5433 and Redis comes from `docker compose -f infra/compose.dev.yml up -d --wait`.
  - The API reads `services/api/.env`. Don't print its contents.
  - The API runs on port 8010. Port 8000 belongs to a different project.
  - Never start Vite yourself. The user runs it on localhost:5173.
- **Local build:** `apps/web/dist/assets` is owned by root, so `pnpm build` fails locally with EACCES. Build into another directory (`pnpm exec tsc -b && pnpm exec vite build --outDir /tmp/webdist`), or ask the user to chown `apps/web/dist`.

**Git flow (user's standing instruction)**
1. Put each task or slice on its own `feat/<slice>` branch cut from an up-to-date `dev`. Never commit to `dev` or `main` directly, and never stack branches.
2. Before every push, run the CI checks from `.github/workflows/ci.yml`:
   - **API** (in `services/api`): `uv run ruff check .`, `uv run ruff format --check .`, `uv run manage.py makemigrations --check --dry-run`, `uv run manage.py spectacular --fail-on-warn --file openapi.yaml` (commit the regenerated file), `uv run pytest`.
   - **Web** (in `apps/web`): `pnpm gen:api` (commit `packages/contracts`), `pnpm lint`, `pnpm typecheck:scoring`, `pnpm test:scoring`, `pnpm gen:parity`, `pnpm typecheck:deck`, `pnpm test:deck`, `pnpm build`.
   - Re-run the checks after any fix.
3. Push, open a PR into `dev`, and merge it once CI is green. Make sure a review PR from `dev` to `main` is open, but never merge that one: it is for the user's review.
4. When a task is done, tick it in tasks.md with evidence: date, files, tests, and what was browser-checked. Then update `docs/completion.md` (the counts plus a History row) in the same PR.

**What only the user can do (don't guess; report and work around it)**
- **D1 (TASK-003):** ITTF fixture and incident-clause review. This blocks TASK-083.
- **D2 (TASK-002):** Stitch screen review.
- **D3 (TASK-078):** Soda stakes stay disabled.
- **D4:** The name of the approval permission, and what happens to `OfficialAppointment` after it migrates. This blocks TASK-107.
- **D5:** The name of the referee permission.
- **D6:** The VPS, domain, object storage, registry, SMTP, alerting and test devices. These block TASK-058 and 060–062.
- **D7:** The dogfood event.

If a decision is still missing, do the tasks that don't depend on it.

**Next actions, in order**
1. Step 0.1: commit TASK-117, open its PR and merge it. Then step 0.2: rebase or merge TASK-116, resolve the conflicts, and add its tasks.md line.
2. Step 2.0, `feat/match-outcomes-referee`:
   - a `DQ` match outcome with no scores or Elo
   - the referee permission
   - a `board` realtime topic
3. TASK-035 (public views and organizer dashboard) and TASK-034 (browser push). Then TASK-109 (meetings without representatives), TASK-082, TASK-085, TASK-107 and TASK-084, following the plan.

**Rules that apply throughout**
- Enforce authority in the API.
- Public serializers use explicit allowlists, and every new route goes into `services/api/tests/test_privacy_matrix.py`.
- Officials hold no club permission by appointment alone.
- Never fabricate scores for W/O, ret. or DQ.
- Never mark an evaluation passed without a real run.
