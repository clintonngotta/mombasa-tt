# Coast TT: project completion

Updated 2026-11-27. Counted from the checkboxes in [tasks.md](../tasks.md) on `dev` after PRs #82 to #88, TASK-082 (match-day control centre), TASK-083 (scoring incidents), TASK-084 (live score channel) and TASK-085 (results announcements), with TASK-123 to TASK-131 added from the owner's requests of 2026-11-21, TASK-128 (next-match recommendation), TASK-133 (tournament and table umpires, added 2026-11-22) TASK-127 (order of play), TASK-107 (regional and national bodies) TASK-134 (nearby search, Tournaments tab, help centre; added and done 2026-11-25), TASK-108 (representatives), TASK-109 (meeting minutes, documents and notices), TASK-110 (events beyond the membership), TASK-130 (post-tournament review), TASK-131 (feedback form builder), TASK-125 (training rules and location check-in), TASK-126 (apologies), TASK-123 (representative squads) and TASK-129 (absence penalties), and TASK-144 (keeping clubs, teams and regions apart in the groups; moving and swapping draw entries; late entries), and TASK-146 (adding members by finding a player or adding someone new). Each task counts once, whatever its size, so these are task counts, not effort. Update this file whenever a task in tasks.md is ticked, added or removed.

## Summary

| Scope | Done | Total | Open | Done % |
| --- | --- | --- | --- | --- |
| All tasks | 113 | 145 | 32 | 78% |
| Without native follow-on, future SMS and WhatsApp (TASK-069, TASK-070, TASK-118, TASK-119) | 113 | 141 | 28 | 80% |
| **Phase 1 launch** | **101** | **110** | **9** | **92%** |

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
| Current feature checklist | 58 | 58 | — |
| Phase 2: reservations and finances | 8 | 8 | — |
| Phase 3: player development | 4 | 4 | — |
| Phase 4: recording and highlights | 0 | 6 | TASK-045 to TASK-050 |
| Phase 5: social broadcasting | 0 | 5 | TASK-051 to TASK-053, TASK-118, TASK-119 |
| Phase 6: organization subscriptions | 0 | 4 | TASK-054 to TASK-057 |
| Operations and release gates | 0 | 11 | TASK-058 to TASK-068 |
| Deferred native follow-on | 0 | 2 | TASK-069, TASK-070 |
| **All tasks** | **113** | **145** | **32** |

## Left for Phase 1 launch (9)

Sequenced, with the owner decisions each task waits on, in [phase1-release-plan.md](phase1-release-plan.md).

- **Competition features:** browser push (TASK-034, real-device check only).
- **Operations:** VPS deploy and staging (TASK-058), backups and restore drill (TASK-060), load tests and monitoring (TASK-061), PWA install and update rehearsal (TASK-062), Phase 1 acceptance and dogfood (TASK-063).
- **Decisions and reviews:** Stitch screen review (TASK-002), owner review of the ITTF clauses (TASK-003), legal sign-off for soda stakes (TASK-078).

After launch, Phases 2 and 3 need their gates (TASK-064, TASK-065). Phases 4 to 6 have not started and each begins with a policy decision.

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
| 2026-11-22 | 87 | 132 | 66% | 78% (76/97) | TASK-128 done (next-match recommendation); TASK-133 added and done (tournament and table umpires) |
| 2026-11-22 | 88 | 132 | 67% | 79% (77/97) | TASK-127 done (order of play: stage order with fall-through, release window, player start times, moving matches later, idle tables) |
| 2026-11-22 | 89 | 132 | 67% | 80% (78/97) | TASK-107 done (regional and national bodies created by platform super admins; officials hold tournament approval in their body; appointments moved into bodies) |
| 2026-11-25 | 90 | 133 | 68% | 81% (79/98) | TASK-134 added and done (clubs and facilities near me by distance, one search box, Tournaments tab for everyone, Home shortcuts, help centre, Playwright e2e suite) |
| 2026-11-25 | 91 | 133 | 68% | 82% (80/98) | TASK-108 done (clubs send representatives to their regional body and regions to the national body; the body accepts, declines and sets a cap; recall, replace, terms, removal on leaving) |
| 2026-11-25 | 92 | 133 | 69% | 83% (81/98) | TASK-109 done (meeting documents, notices, minutes with decisions and action items, approval and amendments, my action items, representatives as invitees) |
| 2026-11-25 | 93 | 133 | 70% | 84% (82/98) | TASK-110 done (events for representatives, named people or every player; check-in and staff attendance; Events for you) |
| 2026-11-25 | 94 | 133 | 71% | 85% (83/98) | TASK-130 done (post-tournament review for the host's staff and officials) |
| 2026-11-25 | 95 | 133 | 71% | 86% (84/98) | TASK-131 done (feedback form builder, templates, sending to attendees, answering, totals, CSV, anonymous forms) |
| 2026-11-25 | 96 | 133 | 72% | 87% (85/98) | TASK-125 done (training rules, weekly slots, location check-in within 300 m checked by the API, moved sessions) |
| 2026-11-25 | 97 | 133 | 73% | 88% (86/98) | TASK-126 done (apologies for training sessions and meetings, with a reason, before the start) |
| 2026-11-25 | 98 | 133 | 74% | 89% (87/98) | TASK-123 done (representative squads: slots, rotation recommendation, override reasons, answers, history) |
| 2026-11-25 | 99 | 133 | 74% | 90% (88/98) | TASK-129 done (absence penalties: rules, proposals, issue or waive, fines through the ledger, appeals, suspension from selection) |
| 2026-11-25 | 101 | 135 | 75% | 90% (90/100) | TASK-135 (phone accounts add an email) and TASK-136 (results announcements as PDF) added and done |
| 2026-11-25 | 102 | 135 | 76% | 90% (90/100) | TASK-079 done (expense categories, financial year, annual report with frozen snapshots, amendments, PDF and CSV) |
| 2026-11-25 | 103 | 135 | 76% | 91% (91/100) | TASK-124 done (external income sources, internal and external totals). Every buildable Phase 1 feature is now done; what is left needs a device, a server or a decision |
| 2026-11-26 | 104 | 136 | 76% | 91% (92/101) | TASK-132 (staff add club members directly), built on its own branch on 2026-11-22, joined the rest when everything was merged for the first deployment |
| 2026-11-26 | 105 | 137 | 77% | 91% (93/102) | TASK-137 added and done (owner account made at start from the environment, no test accounts on the login page, chosen logos, image workflow, Cloudflare notes) |
| 2026-11-26 | 106 | 138 | 77% | 91% (94/103) | TASK-138 added and done (the platform's back office at /admin: accounts, organizations, places; Django admin off /admin) |
| 2026-11-26 | 107 | 139 | 77% | 91% (95/104) | TASK-139 added and done (up to three club admins: add by nomination, hand over, step down) |
| 2026-11-26 | 108 | 140 | 77% | 91% (96/105) | TASK-140 added and done (teams: players without a training place form and join a team; Team menu entry; team ranking) |
| 2026-11-26 | 110 | 142 | 77% | 92% (98/107) | TASK-141 (Secretary and Treasurer roles for clubs and teams) and TASK-142 (pictures of a club, team or facility) added and done |
| 2026-11-27 | 111 | 143 | 78% | 92% (99/108) | TASK-143 (save draft on forms, kept on the device) added and done. |
| 2026-11-27 | 112 | 144 | 78% | 92% (100/109) | TASK-144 (group rules on the draw desk: keep clubs, teams and regions apart, three to a group by default; move or swap draw entries by hand; late entries added to one group of the published draw) added and done. |
| 2026-11-27 | 113 | 145 | 78% | 92% (101/110) | TASK-146 (find a player on Coast TT and invite them to a club or team, or add someone new) added and done. |
