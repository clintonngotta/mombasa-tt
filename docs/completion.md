# Coast TT: project completion

Updated 2026-11-21. Counted from the checkboxes in [tasks.md](../tasks.md) on `feat/offline-sync` (contains `dev` after PR #78). Each task counts once, whatever its size, so these are task counts, not effort. Update this file whenever a task in tasks.md is ticked, added or removed.

## Summary

| Scope | Done | Total | Open | Done % |
| --- | --- | --- | --- | --- |
| All tasks | 78 | 121 | 43 | 64% |
| Without native follow-on, future SMS and WhatsApp (TASK-069, TASK-070, TASK-118, TASK-119) | 78 | 117 | 39 | 67% |
| **Phase 1 launch** | **68** | **86** | **18** | **79%** |

Phase 1 launch scope is Phase 0, Foundation, every Phase 1 section, the current feature checklist, and the launch gates TASK-058, TASK-060, TASK-061, TASK-062 and TASK-063.

## By section

| Section | Done | Total | Open |
| --- | --- | --- | --- |
| Phase 0: documentation and design | 1 | 3 | TASK-002, TASK-003 |
| Foundation | 6 | 6 | — |
| Phase 1: identities and clubs | 7 | 7 | — |
| Phase 1: competitions and operations | 18 | 24 | TASK-034, TASK-035, TASK-082, TASK-083, TASK-084, TASK-085 |
| Phase 1: personal progress | 1 | 1 | — |
| Phase 1: club life | 5 | 6 | TASK-078 |
| Current feature checklist | 30 | 34 | TASK-107, TASK-108, TASK-109, TASK-110 |
| Phase 2: reservations and finances | 6 | 8 | TASK-075, TASK-079 |
| Phase 3: player development | 4 | 4 | — |
| Phase 4: recording and highlights | 0 | 6 | TASK-045 to TASK-050 |
| Phase 5: social broadcasting | 0 | 5 | TASK-051 to TASK-053, TASK-118, TASK-119 |
| Phase 6: organization subscriptions | 0 | 4 | TASK-054 to TASK-057 |
| Operations and release gates | 0 | 11 | TASK-058 to TASK-068 |
| Deferred native follow-on | 0 | 2 | TASK-069, TASK-070 |
| **All tasks** | **78** | **121** | **43** |

## Left for Phase 1 launch (18)

Sequenced, with the owner decisions each task waits on, in [phase1-release-plan.md](phase1-release-plan.md).

- **Competition features:** browser push (TASK-034), public views and organizer dashboard (TASK-035), match-day control centre (TASK-082), scoring incidents: cards, injury, expedite, retirement, DQ (TASK-083), live score channel (TASK-084), results announcements (TASK-085).
- **Governance:** regional and national bodies (TASK-107), representatives (TASK-108), meetings with agendas and minutes (TASK-109), non-competition events (TASK-110).
- **Operations:** VPS deploy and staging (TASK-058), backups and restore drill (TASK-060), load tests and monitoring (TASK-061), PWA install and update rehearsal (TASK-062), Phase 1 acceptance and dogfood (TASK-063).
- **Decisions and reviews:** Stitch screen review (TASK-002), owner review of the ITTF clauses (TASK-003), legal sign-off for soda stakes (TASK-078).

After launch, Phases 2 and 3 need TASK-075 and TASK-079, then their gates (TASK-064, TASK-065). Phases 4 to 6 have not started and each begins with a policy decision.

## Waiting on decisions, not code

TASK-002 (Stitch review), TASK-003 (ITTF clause review), TASK-045 (recording policy), TASK-051 (platform access), TASK-054 (commercial policy), TASK-078 (stakes legal sign-off).

## Not yet counted

- **In review on other branches, still unchecked in tasks.md:** TASK-075 (`feat/welfare-dues-visits`) and TASK-116 (`feat/role-navigation`, which has no line in tasks.md on `dev` yet). Merging both raises the all-tasks figure to 80 of 122 (66%).

## History

| Date | Done | Total | All % | Phase 1 launch % | Change |
| --- | --- | --- | --- | --- | --- |
| 2026-11-20 | 75 | 117 | 64% | 78% (65/83) | First count; TASK-117 done, TASK-119 added |
| 2026-11-20 | 76 | 119 | 64% | 79% (66/84) | TASK-120 done (players added before they register, phone login); TASK-118 defined (SMS verification, future) |
| 2026-11-21 | 77 | 120 | 64% | 79% (67/85) | TASK-121 done (meeting rules, secretary attendance, penalties only the admin changes) |
| 2026-11-21 | 78 | 121 | 64% | 79% (68/86) | TASK-122 done (offline app: saved screens per account, venue changes kept offline and synced once) |
