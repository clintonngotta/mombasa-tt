# Coast TT: Phase 1 release plan

Updated 2026-11-20. Scope and counts: [completion.md](completion.md). Tasks: [tasks.md](../tasks.md). Requirements: [spec.md](../spec.md). Acceptance: [test.md](../test.md). Operations: [deployment.md](../deployment.md).

Phase 1 launch is 65 of 83 tasks done. This plan sequences the 18 that are left, from the work in flight to the release PR into `main`. It was drawn from a code survey on 2026-11-20. Each slice follows the git flow: a `feat/*` branch cut from `dev`, CI green, a PR into `dev`, merge, and the open review PR `dev → main` for the owner.

## 0. Land the work in flight

| Step | What | Notes |
| --- | --- | --- |
| 0.1 | Commit TASK-117 (tournament organizers and media) on `feat/tournament-organizers`, then PR and merge into `dev` | Already ticked in tasks.md. The full API suite passed on 2026-11-20. The web typecheck and build pass. `apps/web/dist/assets` is owned by root (left by a container build), so a local `pnpm build` fails with EACCES until you run `sudo chown -R $USER apps/web/dist` or delete it. CI is not affected. |
| 0.2 | Merge TASK-116 (`feat/role-navigation`, commit 0b3c08f) into `dev` and add its line to tasks.md | Conflicts with TASK-117 in `RegionPage.tsx` and `CoachingTab.tsx`. TASK-117 leaves one item open: the Regional page from 116 needs the overseen list and an organize button. |
| 0.3 | Merge TASK-075 (`feat/welfare-dues-visits`) | Phase 2, but it is already in review. Recount completion.md afterwards. |

## 1. Owner decisions (start now, they gate code)

| ID | Decision | Blocks |
| --- | --- | --- |
| D1 | **TASK-003.** Review the draw, standings and scoring fixtures (F-SC1–10, F-ST1–8, the draw fixtures). Approve the incident clauses: the card ladder and penalty points, team carry-over, adviser cards, injury suspension, expedite (Law 2.13.3) and the 3.4.4.2 countdown. | TASK-083, which feeds parts of 082, 084 and 085 |
| D2 | **TASK-002.** Review the Stitch screens for the remaining workflows: control centre, public views, announcements, meetings, representatives. | Screens for TASK-035, 082, 085, 107–110 |
| D3 | **TASK-078.** Legal sign-off on soda stakes. Not needed for launch if stakes stay off (`SODA_STAKES_ENABLED` false). | Nothing at launch. Record "launch with stakes disabled" in intent.md. |
| D4 | **Governance.** Name the approval permission (for example `tournaments.approve`, or reuse `governance.manage`). Decide whether `OfficialAppointment` is deleted or kept read-only after it migrates to body membership. | TASK-107 |
| D5 | **Referee role.** Add a new `results.referee` permission (or similar). Only it awards walkovers and disqualifications. | TASK-082, TASK-083 |
| D6 | **Infrastructure purchases.** <ul><li>VPS: Contabo or Namecheap, about 4 vCPU / 8 GB / 80 GB, region chosen after a latency test from Mombasa and Nairobi.</li><li>Staging host.</li><li>Domain and DNS.</li><li>S3-compatible object storage, plus a separate backup bucket and keys.</li><li>Container registry.</li><li>SMTP provider (SPF, DKIM and DMARC).</li><li>Alerting channel and uptime service.</li><li>A machine to generate load.</li><li>Android and iOS test devices.</li></ul> | TASK-058, 060, 061, 062 |
| D7 | **Dogfood.** Pick the host club, the date and the participants for the seeded tournament. | TASK-063 |

**Recorded 2026-11-21 (owner's answers):**

- **D1:** the transcribed draw, standings and scoring clauses and fixtures are approved as transcribed. The incident clauses are transcribed with TASK-083 for the owner to see; TASK-083 may start.
- **D2:** pages without Stitch screens follow the existing app's design; they are adjusted later if screens arrive.
- **D3:** launch with soda stakes disabled (`SODA_STAKES_ENABLED` off), recorded in intent.md; TASK-078 stays open.
- **D4:** a new `tournaments.approve` permission approves publication, held through body membership; `OfficialAppointment` is kept read-only as history after the migration.
- **D5:** a new `results.referee` permission (and Referee role); only it awards walkovers and disqualifications.
- D6 and D7 are still open.

## 2. Competition features (code)

Order: shared groundwork first, then the features in parallel tracks.

**2.0 Shared groundwork** (one small PR, `feat/match-outcomes-referee`). Done 2026-11-22: `disqualified` keeps the points played, as REQ-043 says (a W/O records none); only `results.referee` enters or takes away a DQ through the results desk, which the referee can use with no other role, and the Referee template (referee, results, assigned scoring) is seeded in existing organizations. Still open for TASK-083: the referee's recorded decision, removing a disqualified player from later matches, and the web control to award a DQ. Walkovers stay with competition staff until the control centre (TASK-082) moves them to the referee.
- Add `DQ` to `Match.Outcome` and the official result. None of W/O, ret. and DQ changes Elo; W/O records no game scores, while ret. and DQ keep the points played (REQ-043).
- Add the referee permission (D5) to the permission catalogue and role templates.
- Add a `board` topic to `realtime.broadcast.TOPICS` beside `scores` and `results`.

**TASK-035: public views and organizer dashboard (L)** `feat/public-tournaments`
- Public allowlist serializers and `AllowAny` views: published tournament, events, draw, groups, standings, schedule, match detail, player page, rankings. Today only the recap, the card and the events listing are public.
- Web: move `/tournaments/:id/**`, `/players/:id` and `/rankings` out of `RequireAuth`, with a signed-out shell.
- Let the WebSocket consumer accept anonymous viewers of published tournaments only. Today it closes with 4401.
- Organizer dashboard: one page per hosted tournament that links entries, draw, schedule, dispatch, scoring overview, corrections and ceremony, with counts. Replaces `HostedTournamentsPage`.
- Tests: add every new route to `tests/test_privacy_matrix.py` with negative assertions (unpublished, private fields). Browser run of the signed-out journey and the admin journey.

**TASK-082: match-day control centre (L)** `feat/control-centre`, after 2.0. Done 2026-11-22 (see tasks.md); walkovers are now the referee's alone.Choosing the umpire stays on the match page.
- Table board states: free, called, warming up, in play, blocked with a reason. Built from reservations, scoring and delays.
- Check-in desk view for the existing entry check-in and undo.
- Call timestamps (a `MatchCall` model or fields), a grace period per event, and an automatic no-show flag. Only the referee then decides the walkover.
- Referee-only walkover and DQ. Any staff member can enter them today.
- One match-day audit log covering calls, recalls, moves, assignments, outcomes and corrections.
- Tests: referee permission matrix. Screenshots at desktop and tablet sizes.

**TASK-083: scoring incidents (L)** `feat/scoring-incidents`, after D1 and 2.0. Done 2026-11-22 (see tasks.md); one house reading (a second penalty point carrying into the next game) awaits the owner.
- Add incident events to both engines (`packages/scoring/src`, `services/api/scoring/engine.py`):
  - timeout start and end with a countdown
  - player cards: the ladder, penalty points scored as normal points (including game-ending ones), and carry-over across a team tie's rubbers
  - adviser yellow and red
  - injury suspension countdown that can end in retirement
  - expedite: the return counter and alternating service
  - retirement and DQ inside the engine
- Add the `MatchIncident` entity (spec.md data model).
- Shared incident fixtures run in both languages. Regenerate the parity file (`pnpm gen:parity`).
- Umpire deck controls for each incident, at 390 px and on tablet.

**TASK-084: live score channel (M)** `feat/live-scores`, after 035 (and 083 for incident display). Done 2026-11-22 (see tasks.md); local trace p95 666 ms.
- A per-match topic. The payload stays data-free; clients refetch, as now.
- Score strip component. Live match detail showing server, games, timeouts, cards and status. Public and member live views, with polling as the fallback.
- A test that live views never render umpire controls.
- A latency trace script: p95 under 2 s from umpire event to viewer render. Reused by TASK-061.

**TASK-085: results announcements (M–L)** `feat/results-announcements`, after 2.0 (DQ) and 035. Done 2026-11-22 (see tasks.md).
- Generator scoped to a session, round, day, event or tournament, built only from official results. It marks W/O, ret., DQ and pending matches and includes no private fields.
- Draft editor with plain-text and image-card previews (reuse the `recap.py` card).
- A tournament news feed: a new model shown on the public tournament page. Publishing notifies and offers a share link.
- Published versions are frozen. A correction marks them outdated and an amendment is shown beside the original.
- Text fixtures checked against official results. Closes the winners announcement left open by TASK-114.

**TASK-034: browser push (M plus devices)** `feat/web-push`, independent
- VAPID keys from settings; `pywebpush`. A `PushSubscription` model (user, endpoint, keys, user agent, last success, disabled).
- Subscribe and unsubscribe endpoints. Feature detection, opt-in and per-device setup guidance (iOS needs the app installed to the home screen).
- Push jobs through the outbox and Celery. Dedupe per recipient, event, version and channel. Cancel stale pending pushes when a version is superseded. Disable subscriptions on 404 or 410.
- `push` and `notificationclick` handlers in `apps/web/pwa/service-worker.js`. A click opens the current state, not the old one.
- An "Up next" trigger from the ready queue, as distinct from "Called to table" (REQ-019).
- Evidence: real-device delivery on Android Chrome and iOS Safari (installed). Denied or unsupported permission leaves the inbox working.

## 3. Governance (code)

**TASK-107: regional and national bodies (M–L)** `feat/governance-bodies`, after D4 and 0.2
- Add `Organization.Kind.NATIONAL_BODY`, one per country. Serializer guards.
- Super admins create a body and name its first admin. Same positions, fields and roles as clubs (`organizations/committee.py`).
- Approval permission (D4). Rewrite `access.official_for` and `managed_organizations` to read body membership plus that permission, not `OfficialAppointment`. Keep the rule that officials hold no club permission.
- Data migration: each appointment becomes a membership of the matching body, creating the body if it is missing. Cover country appointments and users with several appointments.
- Rebuild the fixtures in `test_authority.py` and `test_regions.py` on bodies. The TASK-094 approval tests must pass.

**TASK-108: representatives (M)** `feat/representatives`, after 107
- Representative model: nominating organization, receiving body, member, term, and a status of pending, accepted, declined or ended.
- Per-club cap, enforced under the organization lock. Accept and decline. Replacement.
- End the term when the representative leaves the club (hook where leaving ends positions).
- Region-to-national nominations.
- Others see only display name and club.
- Tests for the cap, removal and privacy. Screens.

**TASK-109: meetings, agendas and minutes (L)** `feat/meeting-minutes`. The parts that don't need representatives can start after 0.1.
- Move the JSON agenda into agenda items with attachments (a new `Attachment.Purpose` and access rule). Revise after publishing, with notices.
- Add a `MEETING` notification category. Invitees are notified of publish, change and cancel only.
- Secretary records present, late, apologies or absent, with times. Check-in stays limited to the meeting window.
- Structured minutes: decisions per item, action items (owner, due date, status), and a next meeting that creates a draft. Minutes go from draft to approved, are read-only once approved, and amendments show beside the original. Free-text minutes from before the change become a legacy body.
- "My action items" across bodies. A representatives audience once TASK-108 lands.
- Tests: check-in window, minutes immutability, visibility. Browser check.

**TASK-110: non-competition events (M)** `feat/body-events`, after 108
- Activities hosted by bodies as well as clubs. New kinds: workshop, clinic, award night.
- Audiences: members, invited representatives, named people, all signed-in players, plus optional public.
- Check-in and attendance with times (reuse the TASK-109 approach).
- Notification audience resolution. Visibility tests, including that invite-only events never leak.

## 4. Operations gates

**TASK-058: production topology and staging (L)** `feat/production-deploy`, after D6
- `infra/compose.production.yml` with proxy, api, worker, beat, db and redis, using immutable images.
- A production API image (Daphne entrypoint, `collectstatic`) and a static web image.
- Caddyfile: TLS, WebSocket on `/api/v1/ws/`, a 6 MB body cap, `no-cache` on `sw.js` and the manifest, and the previous release's `/assets` kept online.
- Attachments on object storage (`django-storages`). Add `django-cors-headers` with exact origins.
- A production env example covering Redis, SMTP, storage, `APP_BUILD` and VAPID.
- A CI job that builds and publishes images and sets `APP_BUILD`. Deploy and rollback scripts.
- Evidence: a clean deploy and a rollback rehearsed on staging. Update the status section of deployment.md.

**TASK-060: backups and restore (L)** after 058
- pgBackRest: weekly full, daily differential, WAL archiving, encryption, an off-site bucket with its own credentials.
- Attachment versioning and replication with checksum manifests.
- Alerts when WAL lag passes 5 minutes or a backup fails.
- Restore drill on a separate VPS: measure RPO (15 minutes or less) and RTO (4 hours or less) and record them in test.md.

**TASK-061: load and failure (M–L)** after 058 and 084
- A k6 or Locust script for the EVAL-033 mix: 8 tables, 100 sockets, 10 req/s with 20% writes, one score event per table every 10 s, a 15-minute steady period.
- Socket visibility measured with the TASK-084 trace.
- Fault run: restart the worker, interrupt Redis, then measure the outbox draining (within 5 minutes).
- Monitoring: error tracking, uptime, outbox age, disk, certificate expiry.

**TASK-062: PWA rehearsal (M, manual)** after 058
- On HTTPS staging, using Android and iOS devices: install, reopen offline, defer an update while scoring, migrate IndexedDB, keep an old cached bundle working against a newer API, roll back the web build (republish with a higher `APP_BUILD`), open a notification link. Record each run.

**TASK-063: Phase 1 acceptance and dogfood (L)** last
- A `seed_tournament` management command: a club, a singles groups-to-knockout event, a team event, entries, a draw, staff, umpires and a referee. Usable on staging, not only with DEBUG on.
- Full-scope runs of EVAL-001–020 and EVAL-032–036, restricted to Phase 1, with rows in the test.md execution record.
- The dogfood tournament (D7) on staging, with limitations recorded.
- Then: tick the gate tasks, update completion.md, and open the release PR `dev → main`.

## Critical path

```
0.1/0.2 merge ─┬─ 2.0 ─┬─ 082 ───────────────┐
               │       ├─ 083 (needs D1) ────┤
               │       └─ 085 ───────────────┤
               ├─ 035 ── 084 ────────────────┤
               ├─ 034 ───────────────────────┤
               ├─ 107 (D4) ─ 108 ─ 110 ──────┤
               └─ 109 ───────────────────────┤
D6 ─ 058 ─┬─ 060 ────────────────────────────┤
          ├─ 061 (needs 084) ────────────────┤
          └─ 062 ────────────────────────────┴─ 063 ─ release PR dev → main
```

TASK-058 waits only on purchases, so buying the infrastructure early takes it off the critical path. D1 (the fixture and incident review) is the other long pole, because TASK-083 is the largest code change and nothing can start on it until D1 is approved.

## Suggested waves

1. **Now:** 0.1–0.3. Ask the owner for D1, D4, D5 and D6. Then 2.0, TASK-035, TASK-034 and TASK-109 (the parts without representatives).
2. **Next:** TASK-082, TASK-085, TASK-107 and TASK-084. TASK-058 once the VPS exists.
3. **Then:** TASK-083 (after D1), TASK-108, TASK-110, TASK-060 and TASK-062.
4. **Last:** TASK-061, TASK-063 and the release PR.
