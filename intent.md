# mombasa-tt — product intent and decision record

Status: approved planning baseline; application implementation has not started.
Last updated: 2026-09-08.

## Read this set

- [spec.md](spec.md): authoritative behavior and architecture, identified by REQ IDs.
- [tasks.md](tasks.md): ordered delivery checklist and requirement/evaluation mapping.
- [test.md](test.md): executable evaluation definitions and release gates.
- [deployment.md](deployment.md): PWA hosting/releases, recovery, and later native distribution.

Required sequence: complete and validate these documents, create/review the missing Stitch screens, then begin application coding. Documentation and screen generation do not count as implemented application features. Future commercial decisions remain future work rather than implicit permission to charge users or publish broadcasts.

## Purpose

Help clubs run table tennis competitions without conflicting player/table assignments, give umpires a dependable scoring deck, and give players an enduring record of their matches and development. Extend that foundation to facility reservations, transparent club finances, training, recorded highlights, and social broadcasting.

The platform is named **mombasa-tt**. **Coast Table Tennis Club, Mombasa** is a club using the platform, not the identity of every tenant.

## People and outcomes

| Person | Outcome |
|---|---|
| Player | Register, know when/where to play, inspect ratings/history, pay club dues externally and track their status, plan training, and later receive highlights |
| Umpire | Score assigned singles/doubles matches, recover after connectivity loss, and confirm official results |
| Club administrator/captain/committee | Configure actual club responsibilities, manage membership, competitions, contributions, welfare projects, social activities, spending, and announcements |
| Facility staff | Approve table reservations and coordinate tournaments, training, and casual use |
| Organizer | Dispatch the next eligible match and explain idle tables or delayed fixtures |
| Spectator | Open public tournament pages and watch social broadcasts without installing the mobile app |
| Platform operator | Maintain tenant isolation, reliable services, backups, and later organization billing |

Success means that confirmed results produce correct progression and ratings; concurrent assignments never double-book a table/player; accepted offline score events survive restart; members can understand what they owe and how club money was spent. Maximizing table use is subject to dependencies, availability, and rest: continuously occupied tables cannot be guaranteed.

## Approved decisions

| Area | Decision |
|---|---|
| Delivery | Phased full product, not every feature at launch |
| Organizations | Multiple clubs/facilities; an organization can be either or both |
| Identity | One player across multiple organizations; self-signup plus staff-created claimable guests |
| Membership | Join requests approved by staff; public event entry does not require joining the host club |
| Launch application | Mobile-first React + Vite + TypeScript installable PWA with TanStack Query |
| Styling | Tailwind CSS, shadcn/ui, and the approved shared design tokens |
| Browser | One responsive PWA serving players, umpires, public pages and organizer dashboard |
| Native later | React Native + Expo, reusing the API, types, scoring rules and tokens after PWA validation |
| API | Django + Django REST Framework + PostgreSQL |
| Supporting services | Django Channels, Redis, Celery, IndexedDB for offline PWA scores, private object storage |
| Competition | Singles, doubles, configurable team ties; round robin, knockout, groups-to-knockout |
| Tournament navigation | Brackets, Groups, Schedule, Standings |
| Result authority | Assigned umpire confirms; organizer corrections are audited |
| Offline | Continue downloaded assigned match; global dispatch/progression needs connectivity |
| Ratings | Shared platform Elo with separate singles/doubles ledgers |
| Casual games | Quick Score is unrated and does not reserve a table |
| Personal match log | Players privately record their own matches (custom labels, sets, scores, notes) to track progress; official matches allow private notes only (2026-10-03) |
| Club governance | Editable role templates, custom permission bundles, custom member fields |
| Payments | Manual records initially; no payment gateway at launch |
| Contributions | Multiple purposes with descriptions, periodic dues, balances, and expenses; weekly/monthly club operations dues fund running costs (2026-11-15) |
| Welfare projects | Clubs run welfare projects (e.g. a sick member) with a suggested per-member contribution such as KES 50, recorded manually, plus a planned visit (2026-11-15) |
| Club activities | Clubs post social activities (nights out, fun days, visits) with RSVPs on a members-only club schedule (2026-11-15) |
| Soda games | Players challenge each other to friendly unrated matches; the challenger may pledge a stake if they lose, the opponent may match it or play without staking. The app records pledges only, never handles money; stakes need legal sign-off before production (2026-11-15) |
| Annual report | Officials record all expenses in the app; the club publishes a year-end report of how funds were used, frozen once published with visible amendments (2026-11-15) |
| Match-day operations | Staff run the whole match day in the app: schedules, table board, check-in and calls, real-time scoring with timeouts, yellow/red penalty cards, injury breaks, walkovers, retirements and disqualifications, and generated results announcement posts (2026-11-15) |
| Role governance (TASK-013) | Admin always holds every permission and can only be renamed, so an organization can never lose the ability to manage roles; the other templates are editable. Editing, renaming, assigning or deleting a role requires holding every permission involved. Finances is split into view and manage. Members can leave and staff can remove members, both guarded by the last-admin rule. Open question for the user: whether the Member role (which applies to everyone) may carry management permissions such as roles.manage; currently allowed for whoever holds them (2026-11-15) |
| Events calendar | Public listing of tournaments in the country, on and off mombasa-tt, including our club's; live events show their live link (2026-11-15) |
| Facilities | Member requests with staff approval |
| Development | Personal training plus club sessions; private post-match analysis |
| Notifications | Persistent in-app inbox and optional browser push where supported; native push later |
| Discovery | Club directory and opted-in player directory; no chat/challenges initially |
| Visibility | Published competition information is public; private operational information is restricted |
| Initial media | Branded result cards and recaps |
| Recording pilot | One featured table, fixed camera/phone, laptop running OBS, local backup |
| Highlights | Score-assisted candidates and human review first; AI assistance later |
| Broadcast | Later distribution to eligible Facebook/Instagram/TikTok destinations; viewers watch there |
| Subscription | Later platform plans paid by organizations; distinct from club member dues |
| Hosting | Full service on VPS; shared hosting can serve the static web frontend with API on VPS |

Decision revision on 2026-09-08: the user selected **React PWA + Django for launch**, with React Native added later. This supersedes the earlier native-first Expo plan. Next.js, NestJS and Spring Boot are not selected. The mobile-first Stitch designs remain applicable to the responsive PWA; they do not imply native implementation.

## Delivery phases

| Phase | Included | Exit condition |
|---|---|---|
| 0 | Documents and Stitch screens | Traceability is complete; design coverage is reviewed before code |
| 1 | Accounts, clubs, roles, profiles/directories, tournaments, registration, scoring, scheduling, ratings, notifications, awards, public pages/result cards | A complete tournament passes the Phase 1 gates in test.md |
| 2 | Bookings, fees, manual payments, contributions, expenses | Balances reconcile and shared reservation conflicts are prevented |
| 3 | Equipment, private analysis, drills, personal/club training | Private records stay private; training reservations respect conflicts |
| 4 | Recording, synchronization, clip review, player highlights, recaps | One-table recording/clip pilot passes media evaluations |
| 5 | Broadcast studio and social destinations | Eligible destinations tested; failed relay does not lose local recording |
| 6 | Organization plans, billing, entitlements, usage | Commercial policy approved and billing lifecycle evaluated |
| Native follow-on | React Native/Expo application against the same API | Scheduled after validated PWA release; independent of the media/billing phase sequence |

## Brand and references

Use the supplied coastal club crest's navy, blue, cyan, gold, and white. Light operational screens and a navy scoring deck replace the orange/dark PongForge appearance. Exact tokens are in [spec.md](spec.md#req-002).

- [Existing Stitch project](https://stitch.withgoogle.com/projects/1275312862625402020), inspected 2026-09-07: 12 reference screens covering onboarding, profile, home, scoring, brackets, and media.
- Original logo supplied as `/home/clinton/Downloads/Untitled design(1).png`; this is a reference location, not a portable application asset. Copy an approved asset into the project during design implementation.
- New screen names and IDs must be added to the screen inventory in spec.md after generation.

Two-sided comparisons always place players, teams or clubs left and right, including mobile scoring, match cards, results and head-to-head views. The umpire deck follows the user's two-panel reference; responsive layouts must never stack the opposing sides vertically.

## Deferred scope and decision gates

Player challenges, direct messaging, social login, equipment commerce, coach access to private notes, fully offline multi-table dispatch, and a general dark theme are outside the launch scope.

Before Phase 4: confirm retention, recording/publication permissions, clip visibility, storage quotas, and pilot hardware. Before Phase 5: verify actual social account access, output formats, provider pricing, and external launch steps. Before Phase 6: approve plan names/prices, billing provider, tax handling, quotas, trials, grace periods, cancellation and downgrade rules. Before native follow-on: confirm timing, native feature scope and store-distribution budget. No illustrative screen price or provider example is a commercial commitment.

## Operating defaults

English; Africa/Nairobi; KES. Organizations may configure language support as implemented, timezone, and currency; launch UI translation is English only. Store timestamps in UTC and money in integer minor units. Detailed competition defaults and security boundaries live in spec.md.
