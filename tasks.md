# mombasa-tt — delivery checklist

Updated 2026-09-08. Requirements: [spec.md](spec.md). Acceptance: [test.md](test.md). Operations: [deployment.md](deployment.md).

## Execution rules

Complete documents → create/review Stitch screens → application coding. Work through dependencies; later-phase readiness does not authorize starting a production broadcast or charging a subscription. All application tasks below begin unchecked. For a completed task append evidence (test report, reviewed artifact or release), date, and commit where available. A partial task stays unchecked. An EVAL reference means its applicable cases must pass, not that a test already exists.

Phase dependencies: Foundation → 1 → 2 → 3. Phase 4 depends on Phase 1 and its media policy gate; Phase 5 depends on Phase 4; Phase 6 depends on approved commercial policy and production operational readiness. The order shown is the delivery baseline; changing it requires updating intent.md.

## Phase 0: documentation and design

- [x] **TASK-001** — Write and cross-check the five planning documents. Depends: none. REQ-036 / EVAL-036. Done: no orphan requirement/task/evaluation IDs, broken local links, or superseded stack choices. Evidence: 2026-09-08 documentation validation passed all 36 traceability rows, 70 task IDs, local links/anchors and code fences; see test.md execution record. No application tests claimed.
- [ ] **TASK-002** — Create the shared Stitch brand system and missing mobile/desktop screens, adapt relevant references, record screen IDs in spec.md. Depends: TASK-001. REQ-002, REQ-036 / EVAL-002, EVAL-036. Done: player/club/score comparisons use left/right columns at every viewport, the umpire deck follows the supplied two-panel reference, and all inventory workflows have reviewed references; future screens have phase labels in inventory; no app coding has begun before this gate.
- [ ] **TASK-003** — Validate competition rules from current authoritative ITTF clauses and create a reviewed rule/fixture table in spec.md/test.md. Depends: TASK-001. REQ-009, REQ-010, REQ-012 / EVAL-009, EVAL-010, EVAL-012. Done: normal scoring and group tie resolution, walkovers, withdrawals, byes and ultimate ties are unambiguous before their implementation.

## Foundation

- [ ] **TASK-004** — Scaffold React/Vite PWA, Django modules and reusable TypeScript packages with stable compatible dependencies and lockfiles. Includes setup for TanStack Query and shadcn/ui. Depends: TASK-002. REQ-001 / EVAL-001. Done: clean checkout builds frontend/API and starts local services; no launch dependency on Expo.
- [ ] **TASK-005** — Implement shared design tokens, fonts, navigation and component states using Tailwind CSS and shadcn/ui. Depends: TASK-004. REQ-002 / EVAL-002. Done: mobile/web component gallery matches reviewed screens and accessibility gates.
- [ ] **TASK-006** — Configure Django/DRF versioned API, UUIDs, schema generation, pagination, errors and generated TypeScript contracts. Depends: TASK-004. REQ-032 / EVAL-032. Done: generated clients compile; contract and error fixtures pass.
- [ ] **TASK-007** — Build PostgreSQL migrations, outbox, Celery/Redis, Channels, health checks and structured logs. Depends: TASK-006. REQ-001, REQ-033 / EVAL-001, EVAL-033. Done: retry/dedupe survives a worker restart; database/Redis stay private.
- [ ] **TASK-008** — Add CI for Python/TypeScript checks, tests, builds, migration drift and dependency/secrets checks. Depends: TASK-004. REQ-032, REQ-033 / EVAL-032, EVAL-033. Done: a seeded deliberate failure blocks a candidate release.
- [ ] **TASK-009** — Configure PWA manifest/icons, service worker, offline shell, staging/production URLs and safe update lifecycle. Depends: TASK-004. REQ-003, REQ-035 / EVAL-003, EVAL-035. Done: install/reopen offline on supported devices; active-match updates deferred; no private generic caches or server secrets in bundle.

## Phase 1: identities and clubs

- [ ] **TASK-010** — Implement signup, verification, login/logout, reset, secure PWA session cookies and CSRF. Depends: TASK-006, TASK-009. REQ-003 / EVAL-003. Done: expiry/revocation/recovery cases pass without identity enumeration; reauthentication preserves pending scores.
- [ ] **TASK-011** — Implement guest creation, invitation claim and conflict resolution. Depends: TASK-010. REQ-003 / EVAL-003. Done: verified claim preserves match references and rejects reused invitations.
- [ ] **TASK-012** — Implement organization creation/types, join requests, invitations, memberships and switcher. Depends: TASK-010. REQ-004 / EVAL-004. Done: first admin and multiple memberships work; public event entry remains independent. Progress 2026-11-15 (partial, stays unchecked): API for organization create/search, first admin, join requests with admin approve/reject, and my memberships, covered by tests/test_organizations.py. Email invitations API added the same day: admin invite/list/revoke, invitee accept/decline on a verified email, 14-day expiry, no account or member enumeration. Still to do: switcher UI and public event entry (needs TASK-018).
- [ ] **TASK-013** — Implement permission catalog, role templates/editor and grant restrictions. Depends: TASK-012. REQ-005 / EVAL-005. Done: cross-tenant and escalation attempts fail, including last-admin race.
- [ ] **TASK-014** — Implement custom member fields and field access rules. Depends: TASK-013. REQ-005 / EVAL-005. Done: staff-only values never leak to member/public serializers.
- [ ] **TASK-015** — Implement profiles, resumable onboarding, preferences and directories. Depends: TASK-012. REQ-006 / EVAL-006. Done: opt-out removes player-directory discoverability and goals do not grant roles. Progress 2026-11-15 (partial, stays unchecked): profile/goals/onboarding-complete API and opted-in player directory, wired to the existing onboarding screens and covered by tests/test_profiles.py. Still to do: avatar, profile edit/directory UI, and published extended details.
- [ ] **TASK-016** — Implement public/private serializers, attachment access and signed URLs. Depends: TASK-013, TASK-015. REQ-020, REQ-032 / EVAL-020, EVAL-032. Done: public/tenant/private data matrix passes.

## Phase 1: competitions and operations

- [ ] **TASK-017** — Implement venue/table setup and tournament/event lifecycle with configuration UI. Depends: TASK-013. REQ-007 / EVAL-007. Done: formats publish/start/freeze correctly and dates use organization timezone.
- [ ] **TASK-018** — Implement entry, waitlist, staff acceptance, withdrawal and check-in for all entry types. Depends: TASK-017. REQ-008 / EVAL-008. Done: concurrent last-slot requests cannot exceed capacity; duplicate participants rejected.
- [ ] **TASK-019** — Implement seeded round robin, knockout/byes and groups-to-knockout draw generation/versioning. Depends: TASK-003, TASK-018. REQ-009 / EVAL-009. Done: reviewed format fixtures pass and draw publication is reproducible.
- [ ] **TASK-020** — Implement groups/standings calculations and tie-break explanations. Depends: TASK-019. REQ-010 / EVAL-010. Done: reviewed exact-ratio fixtures determine qualifiers consistently.
- [ ] **TASK-021** — Implement Brackets, Groups, Schedule and Standings mobile/web views with match details. Depends: TASK-020, TASK-005. REQ-010 / EVAL-010. Done: every tab works for applicable formats and explains non-applicability.
- [ ] **TASK-022** — Implement team rosters, tie templates, lineup submission and sequential rubbers. Depends: TASK-019. REQ-011 / EVAL-011. Done: invalid lineups fail and clinched ties leave surplus rubbers unplayed.
- [ ] **TASK-023** — Implement TypeScript scoring reducer and Python validator using shared fixtures. Depends: TASK-003, TASK-006. REQ-012 / EVAL-012. Done: scoring/service/undo fixtures produce identical canonical states.
- [ ] **TASK-024** — Implement umpire assignment and mobile scoring deck with result confirmation. Depends: TASK-023, TASK-022. REQ-012 / EVAL-012. Done: only assigned/authorized users score and invalid finish attempts fail.
- [ ] **TASK-025** — Implement IndexedDB score journal, browser restart recovery, cross-tab writer ownership, quota errors, upload batching, dedupe and revision conflicts. Depends: TASK-024. REQ-013 / EVAL-013. Done: offline/restart/replay tests preserve every acknowledged event once; storage failure never reports a score as saved.
- [ ] **TASK-026** — Implement device reassignment and organizer conflict resolution screens. Depends: TASK-025. REQ-013, REQ-015 / EVAL-013, EVAL-015. Done: stale device cannot overwrite accepted data; unresolved reservations remain visible.
- [ ] **TASK-027** — Implement central reservations and transactional table/player exclusivity. Depends: TASK-017, TASK-022. REQ-014 / EVAL-014. Done: concurrency tests prevent player/table collisions across events.
- [ ] **TASK-028** — Implement ready queue, rest/dependency checks, dispatch board and optional automatic assignment. Depends: TASK-027. REQ-014 / EVAL-014. Done: priority order is deterministic; idle/blocked explanations identify real constraints.
- [ ] **TASK-029** — Implement official result transactions, outbox projections and audited correction handling. Depends: TASK-025, TASK-027, TASK-007. REQ-015 / EVAL-015. Done: retries cannot double-progress; downstream started-match corrections pause affected play.
- [ ] **TASK-030** — Implement singles/doubles Elo ledgers, deterministic replay, ranking/history UI. Depends: TASK-029. REQ-016 / EVAL-016. Done: numeric fixtures and correction replay pass; excluded outcomes have no deltas.
- [ ] **TASK-031** — Implement local and saved unrated Quick Score. Depends: TASK-023, TASK-010. REQ-017 / EVAL-017. Done: casual use cannot change competitive standings, ratings or reservations.
- [ ] **TASK-032** — Implement recaps, branded result cards, placements, discretionary awards and announcements. Depends: TASK-030, TASK-021. REQ-018 / EVAL-018. Done: cards reflect authoritative data; only authorized users publish awards.
- [ ] **TASK-033** — Implement notification inbox/read state, triggers, audience selection and preferences. Depends: TASK-007, TASK-028, TASK-032. REQ-019 / EVAL-019. Done: alerts resolve current assignment and retries create one logical item.
- [ ] **TASK-034** — Implement optional browser push with feature detection, opt-in, device setup guidance and expired-subscription cleanup. Depends: TASK-033, TASK-009. REQ-019 / EVAL-019. Done: supported real-device delivery tested; unsupported/denied permission does not break inbox or scheduling.
- [ ] **TASK-035** — Finish public tournament/player views and organizer web dashboard. Depends: TASK-021, TASK-028, TASK-032, TASK-016. REQ-020 / EVAL-020. Done: unauthenticated tournament journey and authorized admin journey pass.

## Phase 1: personal progress

- [ ] **TASK-071** — Implement the private personal match log: records with free-text labels, sets/scores and notes, owner-only API, progress summary and mobile/web views. Depends: TASK-010. REQ-037 / EVAL-037. Done: owner-only access matrix, set validation and summary tests pass; official matches remain notes-only (REQ-025, TASK-041).

## Phase 1: club life

- [ ] **TASK-072** — Implement club activities (types, schedule fields, audience, capacity, draft/publish/cancel), RSVPs with transactional capacity and waitlist, and the members-only club schedule merging activities, tournaments and training sessions with .ics export. Depends: TASK-013, TASK-017. REQ-039 / EVAL-039. Done: capacity race, visibility and timezone tests pass.
- [ ] **TASK-073** — Implement activity and club schedule mobile/web views, RSVP controls and publish/change/cancel notifications. Depends: TASK-072, TASK-033. REQ-039 / EVAL-039. Done: audience-only notifications and schedule screenshots recorded; cost notes never imply payment.

## Phase 2: reservations and finances

- [ ] **TASK-036** — Implement opening hours, closures, booking requests, approval/rejection/cancellation and views. Depends: TASK-027, TASK-033. REQ-021 / EVAL-021. Done: approvals race safely against matches and other bookings.
- [ ] **TASK-037** — Implement charges, manual payments, allocations, excess credit and reversals. Depends: TASK-013, TASK-018, TASK-036. REQ-022 / EVAL-022. Done: ledger arithmetic reconciles and currency mismatches are rejected.
- [ ] **TASK-038** — Implement contribution campaigns, period generation, assignments and waivers. Depends: TASK-037, TASK-007. REQ-023 / EVAL-023. Done: retries/month-end/leap-year cases create exactly one correct due per period.
- [ ] **TASK-039** — Implement contribution member/staff views and reminders. Depends: TASK-038, TASK-033. REQ-023 / EVAL-023. Done: pending/partial/overdue status and visibility match records.
- [ ] **TASK-040** — Implement purpose expenses, receipts, reversals and transparent summaries. Depends: TASK-037, TASK-038, TASK-016. REQ-024 / EVAL-024. Done: received/spent/remaining totals reconcile, including deficits and reversals.
- [ ] **TASK-074** — Implement welfare projects: setup with suggested per-member amount, target, deadline, beneficiary and audience; voluntary contributions through the manual ledger; expenses, close/hide, and contributor anonymity. Depends: TASK-037, TASK-040. REQ-038 / EVAL-038. Done: ledger reconciliation, no implied overdue status and beneficiary-privacy tests pass.
- [ ] **TASK-075** — Implement welfare project member/staff views, progress against target, linked visit activities (REQ-039) and Phase 2 activity cost sharing via one-time campaigns. Depends: TASK-074, TASK-073. REQ-038, REQ-039 / EVAL-038, EVAL-039. Done: member sees totals and own contribution only; screenshots recorded.

## Phase 3: player development

- [ ] **TASK-041** — Implement private match notes and recap entry point. Depends: TASK-032, TASK-016. REQ-025 / EVAL-025. Done: another player or club admin cannot access notes; official sets/scores stay read-only to the player.
- [ ] **TASK-042** — Implement equipment enrichment and personal/club drill libraries. Depends: TASK-015, TASK-013. REQ-026 / EVAL-026. Done: editing/sharing permissions and required drill fields pass.
- [ ] **TASK-043** — Implement personal training plans, calendar commitments and completion. Depends: TASK-042, TASK-027. REQ-027 / EVAL-027. Done: calendar conflicts differ correctly from non-reserving checklist items.
- [ ] **TASK-044** — Implement club sessions, invitations, accepted commitments, attendance and reminders. Depends: TASK-043, TASK-036, TASK-033. REQ-027 / EVAL-027. Done: acceptance and reservation are atomic and duplicate acceptance is harmless.

## Phase 4: recording and highlights

- [ ] **TASK-045** — Approve recording/publication policy, retention, quotas and hardware pilot checklist. Depends: TASK-001, TASK-002. REQ-028, REQ-020 / EVAL-028, EVAL-020. Done: decisions recorded before any participant recording is enabled.
- [ ] **TASK-046** — Integrate one-table OBS recording/session metadata and health status. Depends: TASK-045, TASK-029. REQ-028 / EVAL-028. Done: full match recording remains local during network interruption.
- [ ] **TASK-047** — Implement segmented video/score time mapping and highlight markers. Depends: TASK-046. REQ-028, REQ-029 / EVAL-028, EVAL-029. Done: reconnects retain correct match boundaries and calibrations.
- [ ] **TASK-048** — Implement isolated FFmpeg jobs, clip boundaries, review and publication. Depends: TASK-047, TASK-016. REQ-029 / EVAL-029. Done: retries do not duplicate publications; reviewed footage matches selected intervals.
- [ ] **TASK-049** — Implement player galleries, notifications and tournament recap assembly. Depends: TASK-048, TASK-033. REQ-029 / EVAL-029. Done: published clips reach permitted players and deletion follows approved retention policy.
- [ ] **TASK-050** — Evaluate optional AI candidate ranking on consented labeled clips. Depends: TASK-049. REQ-029 / EVAL-029. Done: report human-rated candidate usefulness and false claims before enabling; retain manual workflow regardless of outcome.

## Phase 5: social broadcasting

- [ ] **TASK-051** — Verify actual Facebook/Instagram/TikTok access, relay pricing, output formats and external launch steps. Depends: TASK-045. REQ-030 / EVAL-030. Done: capability matrix identifies supported/tested/unsupported destinations; no bypass of platform access rules.
- [ ] **TASK-052** — Implement encrypted destination configuration, broadcast roles, preview and relay controls. Depends: TASK-051, TASK-046. REQ-030 / EVAL-030. Done: settings alone never publish; stream keys remain absent from logs/public clients.
- [ ] **TASK-053** — Implement destination health/recovery, external watch links and portrait/landscape validation. Depends: TASK-052. REQ-030 / EVAL-030. Done: one failed destination does not stop recording or other destinations; both players remain visible.

## Phase 6: organization subscriptions

- [ ] **TASK-054** — Approve commercial policy: plans, prices, provider, tax, quotas, trials, grace, cancellations and active-event protection. Depends: TASK-001, TASK-035. REQ-031 / EVAL-031. Done: policy is explicit and signed off before billing code or commercial UI values.
- [ ] **TASK-055** — Implement versioned plan entitlements and organization usage accounting. Depends: TASK-054. REQ-031 / EVAL-031. Done: no confusion with member dues; quota evaluation is deterministic.
- [ ] **TASK-056** — Implement billing provider integration, webhook verification, reconciliation and invoices. Depends: TASK-055. REQ-031, REQ-032 / EVAL-031, EVAL-032. Done: duplicate/out-of-order billing events cannot duplicate charges or regress state.
- [ ] **TASK-057** — Implement plan management, expiry/grace/downgrade and operator recovery flows. Depends: TASK-056. REQ-031 / EVAL-031. Done: approved lifecycle fixtures pass; data and active scoring are protected by policy.

## Operations and release gates

- [ ] **TASK-058** — Implement the deployment.md Compose topology, ASGI proxy, secrets and staging environment. Depends: TASK-007, TASK-008. REQ-034 / EVAL-034. Done: clean VPS deploy and rollback rehearsed on Contabo or equivalent Namecheap VPS.
- [ ] **TASK-059** — Implement optional Namecheap shared-hosting static frontend deployment. Depends: TASK-058, TASK-035. REQ-034 / EVAL-034. Done: deep links, TLS, CORS/CSRF and live API work against the VPS without requiring ASGI on shared hosting.
- [ ] **TASK-060** — Implement encrypted off-site PostgreSQL/WAL and attachment backups, restore drill and alerts. Depends: TASK-058. REQ-034 / EVAL-034. Done: measured RPO/RTO meet targets; independent credentials and restoration evidence exist.
- [ ] **TASK-061** — Run controlled API/live-update load tests and worker failure drills; configure production monitoring. Depends: TASK-029, TASK-033, TASK-058. REQ-033 / EVAL-033. Done: gates pass with hardware/network/test settings recorded.
- [ ] **TASK-062** — Rehearse PWA installation, service-worker update deferral, IndexedDB migration, cached-client compatibility and web rollback. Depends: TASK-009, TASK-025, TASK-058. REQ-035 / EVAL-035. Done: supported old bundles work through rollout; unsynced scores survive update/reopen; no app-store release required.
- [ ] **TASK-063** — Run full Phase 1 acceptance and seeded tournament dogfood. Depends: TASK-010 through TASK-035, TASK-060 through TASK-062. REQ-001 through REQ-020, REQ-032 through REQ-036 / corresponding EVALs. Done: no blocking failures; results and limitations recorded in test.md.
- [ ] **TASK-064** — Run Phase 2 release gate. Depends: TASK-036 through TASK-040, TASK-063. REQ-021 through REQ-024 / EVAL-021 through EVAL-024. Done: finance/booking checks plus core regression pass.
- [ ] **TASK-065** — Run Phase 3 release gate. Depends: TASK-041 through TASK-044, TASK-064. REQ-025 through REQ-027 / EVAL-025 through EVAL-027. Done: privacy/training checks plus core regression pass.
- [ ] **TASK-066** — Run Phase 4 recording pilot gate. Depends: TASK-045 through TASK-049, TASK-063. REQ-028, REQ-029 / EVAL-028, EVAL-029. Done: consented pilot and review evidence pass; AI is optional.
- [ ] **TASK-067** — Run Phase 5 destination gate. Depends: TASK-051 through TASK-053, TASK-066. REQ-030 / EVAL-030. Done: only validated destinations enabled; approval/recording recovery checks pass.
- [ ] **TASK-068** — Run Phase 6 subscription gate. Depends: TASK-054 through TASK-057, TASK-063. REQ-031 / EVAL-031. Done: approved policy and provider sandbox/live-readiness evidence pass before real charging.

## Deferred native follow-on

- [ ] **TASK-069** — Confirm native follow-on scope/timing after PWA validation and document API/component reuse. Depends: TASK-063. REQ-001, REQ-035 / EVAL-001, EVAL-035 native extension. Done: agreed native scope does not block PWA release or require completion of media/billing phases.
- [ ] **TASK-070** — Add Expo/React Native, NativeWind, SQLite scoring adapter, secure native tokens, native push, build signing and store-distribution tests. Depends: TASK-069. REQ-001, REQ-003, REQ-013, REQ-019, REQ-035 / corresponding native-extension evaluations. Done: native client passes the shared contracts/scoring fixtures and separately documented real-device/store gates. Deferred; no native application code in launch phase.

## Traceability index

Each row links an authoritative requirement to its minimum evaluation and primary tasks. Release tasks add regression coverage.

| Requirement | Evaluation | Tasks |
|---|---|---|
| [REQ-001](spec.md#req-001) | [EVAL-001](test.md#eval-001) | TASK-004, TASK-007 |
| [REQ-002](spec.md#req-002) | [EVAL-002](test.md#eval-002) | TASK-002, TASK-005 |
| [REQ-003](spec.md#req-003) | [EVAL-003](test.md#eval-003) | TASK-009, TASK-010, TASK-011 |
| [REQ-004](spec.md#req-004) | [EVAL-004](test.md#eval-004) | TASK-012 |
| [REQ-005](spec.md#req-005) | [EVAL-005](test.md#eval-005) | TASK-013, TASK-014 |
| [REQ-006](spec.md#req-006) | [EVAL-006](test.md#eval-006) | TASK-015 |
| [REQ-007](spec.md#req-007) | [EVAL-007](test.md#eval-007) | TASK-017 |
| [REQ-008](spec.md#req-008) | [EVAL-008](test.md#eval-008) | TASK-018 |
| [REQ-009](spec.md#req-009) | [EVAL-009](test.md#eval-009) | TASK-003, TASK-019 |
| [REQ-010](spec.md#req-010) | [EVAL-010](test.md#eval-010) | TASK-003, TASK-020, TASK-021 |
| [REQ-011](spec.md#req-011) | [EVAL-011](test.md#eval-011) | TASK-022 |
| [REQ-012](spec.md#req-012) | [EVAL-012](test.md#eval-012) | TASK-003, TASK-023, TASK-024 |
| [REQ-013](spec.md#req-013) | [EVAL-013](test.md#eval-013) | TASK-025, TASK-026 |
| [REQ-014](spec.md#req-014) | [EVAL-014](test.md#eval-014) | TASK-027, TASK-028 |
| [REQ-015](spec.md#req-015) | [EVAL-015](test.md#eval-015) | TASK-026, TASK-029 |
| [REQ-016](spec.md#req-016) | [EVAL-016](test.md#eval-016) | TASK-030 |
| [REQ-017](spec.md#req-017) | [EVAL-017](test.md#eval-017) | TASK-031 |
| [REQ-018](spec.md#req-018) | [EVAL-018](test.md#eval-018) | TASK-032 |
| [REQ-019](spec.md#req-019) | [EVAL-019](test.md#eval-019) | TASK-033, TASK-034 |
| [REQ-020](spec.md#req-020) | [EVAL-020](test.md#eval-020) | TASK-016, TASK-035, TASK-045 |
| [REQ-021](spec.md#req-021) | [EVAL-021](test.md#eval-021) | TASK-036 |
| [REQ-022](spec.md#req-022) | [EVAL-022](test.md#eval-022) | TASK-037 |
| [REQ-023](spec.md#req-023) | [EVAL-023](test.md#eval-023) | TASK-038, TASK-039 |
| [REQ-024](spec.md#req-024) | [EVAL-024](test.md#eval-024) | TASK-040 |
| [REQ-025](spec.md#req-025) | [EVAL-025](test.md#eval-025) | TASK-041 |
| [REQ-026](spec.md#req-026) | [EVAL-026](test.md#eval-026) | TASK-042 |
| [REQ-027](spec.md#req-027) | [EVAL-027](test.md#eval-027) | TASK-043, TASK-044 |
| [REQ-028](spec.md#req-028) | [EVAL-028](test.md#eval-028) | TASK-045, TASK-046, TASK-047 |
| [REQ-029](spec.md#req-029) | [EVAL-029](test.md#eval-029) | TASK-047, TASK-048, TASK-049, TASK-050 |
| [REQ-030](spec.md#req-030) | [EVAL-030](test.md#eval-030) | TASK-051, TASK-052, TASK-053 |
| [REQ-031](spec.md#req-031) | [EVAL-031](test.md#eval-031) | TASK-054, TASK-055, TASK-056, TASK-057 |
| [REQ-032](spec.md#req-032) | [EVAL-032](test.md#eval-032) | TASK-006, TASK-008, TASK-016, TASK-056 |
| [REQ-033](spec.md#req-033) | [EVAL-033](test.md#eval-033) | TASK-007, TASK-008, TASK-061 |
| [REQ-034](spec.md#req-034) | [EVAL-034](test.md#eval-034) | TASK-058, TASK-059, TASK-060 |
| [REQ-035](spec.md#req-035) | [EVAL-035](test.md#eval-035) | TASK-009, TASK-062; native later TASK-069, TASK-070 |
| [REQ-036](spec.md#req-036) | [EVAL-036](test.md#eval-036) | TASK-001, TASK-002 |
| [REQ-037](spec.md#req-037) | [EVAL-037](test.md#eval-037) | TASK-071 |
| [REQ-038](spec.md#req-038) | [EVAL-038](test.md#eval-038) | TASK-074, TASK-075 |
| [REQ-039](spec.md#req-039) | [EVAL-039](test.md#eval-039) | TASK-072, TASK-073, TASK-075 |
