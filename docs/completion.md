# Coast TT: project completion

Updated 2026-11-22. Counted from the checkboxes in [tasks.md](../tasks.md) on `dev` after PRs #82 to #88, TASK-082 (match-day control centre), TASK-083 (scoring incidents), TASK-084 (live score channel) and TASK-085 (results announcements), with TASK-123 to TASK-131 added from the owner's requests of 2026-11-21. Each task counts once, whatever its size, so these are task counts, not effort. Update this file whenever a task in tasks.md is ticked, added or removed.

## Summary

| Scope | Done | Total | Open | Done % |
| --- | --- | --- | --- | --- |
| All tasks | 85 | 131 | 46 | 65% |
| Without native follow-on, future SMS and WhatsApp (TASK-069, TASK-070, TASK-118, TASK-119) | 85 | 127 | 42 | 67% |
| **Phase 1 launch** | **74** | **96** | **22** | **77%** |

Phase 1 launch scope is Phase 0, Foundation, every Phase 1 section, the current feature checklist, and the launch gates TASK-058, TASK-060, TASK-061, TASK-062 and TASK-063.

## By section

| Section | Done | Total | Open |
| --- | --- | --- | --- |
| Phase 0: documentation and design | 1 | 3 | TASK-002, TASK-003 |
| Foundation | 6 | 6 | — |
| Phase 1: identities and clubs | 7 | 7 | — |
| Phase 1: competitions and operations | 23 | 24 | TASK-034 |
| Phase 1: personal progress | 1 | 1 | — |
| Phase 1: club life | 5 | 6 | TASK-078 |
| Current feature checklist | 31 | 44 | TASK-107 to TASK-110, TASK-123 to TASK-131 |
| Phase 2: reservations and finances | 7 | 8 | TASK-079 |
| Phase 3: player development | 4 | 4 | — |
| Phase 4: recording and highlights | 0 | 6 | TASK-045 to TASK-050 |
| Phase 5: social broadcasting | 0 | 5 | TASK-051 to TASK-053, TASK-118, TASK-119 |
| Phase 6: organization subscriptions | 0 | 4 | TASK-054 to TASK-057 |
| Operations and release gates | 0 | 11 | TASK-058 to TASK-068 |
| Deferred native follow-on | 0 | 2 | TASK-069, TASK-070 |
| **All tasks** | **85** | **131** | **46** |

## Left for Phase 1 launch (22)

Sequenced, with the owner decisions each task waits on, in [phase1-release-plan.md](phase1-release-plan.md).

- **Competition features:** browser push (TASK-034, real-device check only).
- **Governance:** regional and national bodies (TASK-107), representatives (TASK-108), meetings with agendas and minutes (TASK-109), non-competition events (TASK-110).
- **Club life and match day (added 2026-11-21):** representative squads with rotation (TASK-123), internal and external finance with source categories (TASK-124), training rules and 300 m location check-in (TASK-125), apologies for training and meetings (TASK-126), order of play with no idle tables (TASK-127), next-match recommendation (TASK-128), absence penalties (TASK-129), post-tournament review (TASK-130), feedback form builder (TASK-131).
- **Operations:** VPS deploy and staging (TASK-058), backups and restore drill (TASK-060), load tests and monitoring (TASK-061), PWA install and update rehearsal (TASK-062), Phase 1 acceptance and dogfood (TASK-063).
- **Decisions and reviews:** Stitch screen review (TASK-002), owner review of the ITTF clauses (TASK-003), legal sign-off for soda stakes (TASK-078).

After launch, Phases 2 and 3 need TASK-079, then their gates (TASK-064, TASK-065). Phases 4 to 6 have not started and each begins with a policy decision.

## Waiting on decisions, not code

TASK-002 (Stitch review), TASK-003 (ITTF clause review), TASK-045 (recording policy), TASK-051 (platform access), TASK-054 (commercial policy), TASK-078 (stakes legal sign-off).

## History

| Date | Done | Total | All % | Phase 1 launch % | Change |
| --- | --- | --- | --- | --- | --- |
| 2026-11-20 | 75 | 117 | 64% | 78% (65/83) | First count; TASK-117 done, TASK-119 added |
| 2026-11-20 | 76 | 119 | 64% | 79% (66/84) | TASK-120 done (players added before they register, phone login); TASK-118 defined (SMS verification, future) |
| 2026-11-21 | 77 | 120 | 64% | 79% (67/85) | TASK-121 done (meeting rules, secretary attendance, penalties only the admin changes) |
| 2026-11-21 | 78 | 121 | 64% | 79% (68/86) | TASK-122 done (offline app: saved screens per account, venue changes kept offline and synced once) |
| 2026-11-21 | 80 | 122 | 66% | 79% (69/87) | TASK-075 (welfare dues and linked visits) and TASK-116 (role-based navigation) merged into dev |
| 2026-11-21 | 80 | 131 | 61% | 72% (69/96) | TASK-123 to TASK-131 added (squads, external finance, location check-in, apologies, order of play, next match, penalties, reviews, feedback forms) |
| 2026-11-21 | 81 | 131 | 62% | 73% (70/96) | TASK-035 done (public tournament, results, rankings and ratings pages signed out; organizer dashboard screen) |
