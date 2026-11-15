# mombasa-tt — functional and technical specification

Status: planning baseline, not an implementation claim. Updated 2026-11-15.
Product decisions: [intent.md](intent.md). Execution: [tasks.md](tasks.md). Acceptance: [test.md](test.md). Operations: [deployment.md](deployment.md).

## Requirement conventions

REQ-001 through REQ-043 are authoritative requirements. Each maps to the same-numbered EVAL in test.md and at least one task in tasks.md. Phase 1 is the launch boundary; later-phase contracts reserve integration points without activating unfinished features.

### REQ-001

**Application architecture — foundation.** Launch one mobile-first React/Vite TypeScript PWA with Tailwind CSS, shadcn/ui, TanStack Query, Django/DRF API, PostgreSQL, Django Channels/Redis, Celery/Redis, IndexedDB for offline score persistence, and private S3-compatible attachments. Use compatible stable package versions and commit lockfiles when scaffolding. React Native/Expo and NativeWind belong to a later native follow-on, not the launch build.

Proposed repository: `apps/web`, `services/api`, `packages/contracts`, `packages/scoring`, `packages/design-tokens`, and `infra`; add `apps/mobile` only in the native follow-on. These directories are planned, not currently present. Keep Django domain modules inside one deployable service initially. Keep heavy media processing in separate workers later. Keep frontend types, pure scoring logic and tokens reusable by future native clients; Python independently validates accepted score streams against common fixtures.

### REQ-002

**Design and navigation — foundation.** Use the following shared tokens:

| Token | Value | Use |
|---|---|---|
| brand.navy | #031539 | Text, navigation, scoring deck |
| brand.blue | #024385 | Primary actions and links, with white text |
| brand.gold | #FFD859 | Serving and awards, with navy text |
| brand.cyan | #08B8F0 | Live accents, with navy text |
| surface.canvas | #F3F7FB | Page background |
| surface.default | #FFFFFF | Forms/cards |
| surface.selected | #EAF3FC | Selected items |
| text.secondary | #52647A | Metadata |
| border.default | #D7E2EE | Dividers |
| status.success | #18794E | Paid/confirmed |
| status.warning | #8A5700 | Pending/sync warnings |
| status.danger | #B42318 | Errors/destructive actions |

Barlow Condensed 600/700 headings and score numerals; Source Sans 3 400/600 body. Body 16/24; metadata 14/20; headings 20/26, 24/28, 32/36; score 80–144 responsive. Tabular numerals. Spacing 4/8/12/16/24/32/48/64; radius 8 controls, 12 cards, 16 sheets. Mobile padding 16; web maximum content 1200 and forms 640. Touch targets at least 48 square. Honor font scaling, screen-reader labels, keyboard focus, and reduced motion. Status uses words/icons as well as color. Light app with navy scoring mode; preserve crest proportions and use a simplified small icon.

Mobile tabs: Home, Play, Club, Profile. Header inbox and organization switcher. Web sidebar uses the same domain names. Home prioritizes the next commitment over vanity statistics. Scoring is full-screen with names, high-contrast points, service marker, games, undo, and explicit finish action. Every screen has loading/empty/error/access states and applicable offline recovery. Unavailable later features are omitted from launch navigation rather than shown as functioning controls.

**Mandatory left/right comparison layout (user decision, 2026-09-08).** Whenever two players, doubles pairs, teams or clubs are compared, render them in adjacent left and right columns, never as upper/lower opponents. Apply this to live and casual scoring, fixtures, bracket match cards, head-to-head statistics, result summaries and share cards. Retain both sides on narrow screens and at enlarged text sizes; wrap names within their columns and allow surrounding content to scroll. Statistical rows align beneath the same two identities. Standings and member directories may remain lists because they are not two-sided comparisons. Preserve side identity across scores, service, game history and controls; a deliberate change-ends action moves the associated identity and all its state together.

Umpire visual reference: the user-supplied two-panel deck, `/tmp/codex-clipboard-RjesBa.png` (temporary reference path). Use its compact header, equal-width score panels separated by a vertical rule, large numerals, serving badge, completed-game strip and horizontal action row above a scrollable event log. Keep the club navy/gold/cyan tokens. Tapping the corresponding score panel is an explicit accessible point action; an optional swipe shortcut must not be the only input method. Log only known events; do not invent shot descriptions from point entry. Keep Undo and Timeout reachable, distinguish result confirmation from retirement, and show pending-sync state. The Card control follows the REQ-043 penalty-card rules (user decision, 2026-11-15); keep it behind a confirmation step so a card is never awarded by a stray tap.

### REQ-003

**Accounts and guests — Phase 1.** Verified email/password, sign-in/out, reset, and invitations. Resumable onboarding requires basic identity; extended profile and club discovery are skippable. Guests can be entered by staff and claim via verified single-use invitations. Name similarity alone never merges players. A conflicting existing identity requires staff resolution with an audit trail and preserved match references.

The PWA uses secure HttpOnly session cookies with CSRF protection. Revoke sessions on logout/password reset; authenticate live connections without durable credentials in query strings. Implement uniform login throttling and non-enumerating recovery responses. Offline score capture remains local if a session expires; require reauthentication as the same user to synchronize. Later native clients use a separately tested short-lived access/rotating refresh flow with platform secure storage.

### REQ-004

**Organizations — Phase 1.** Register club, facility, or both. Creator becomes first admin. Players can join multiple organizations. Join requests are pending/approved/rejected; invited members explicitly accept. Public tournament entry is independent of host membership. Organization switching changes operational context, not the global player identity. Platform operator authority is separate from club roles.

### REQ-005

**Governance — Phase 1.** Editable admin/captain/assistant captain/committee/member templates plus custom role names and permission bundles. Permission domains: members, roles, competitions, results, assigned scoring, facilities, finances, announcements, training, welfare projects, club activities, and later media/billing. Users may hold multiple roles; effective grants are the union within that organization. Granting authority cannot exceed the acting user's delegable permissions. Keep one active admin. Enforce checks on API reads/writes, live events, files, and UI actions.

Custom member fields: text, number, date, boolean, single selection; required/optional; member-visible or staff-only. Field definitions belong to an organization, values to its membership. Field access does not override other privacy rules. Preserve historical values when retiring a field.

### REQ-006

**Profiles and discovery — Phase 1.** Global display name, avatar, nickname, bio, hand, grip, style, self-described experience and optional goals. Goals affect shortcuts, not permissions or ratings. Club/facility search by name/town and opted-in player directory. Extended details are private until explicitly published. No precise player location or contact exposure. Equipment enrichment arrives under REQ-026.

### REQ-007

**Tournament setup — Phase 1.** Tournament has host, venue, dates/timezone, publication state and one or more singles/doubles/team events. Event setup includes format, capacity, scoring best-of, rest period, registration window, entry fee, seed order, groups and qualification count. Lifecycle draft → published → in progress → completed, with cancellation as audited terminal action. Separate public publication from operational permissions. Freeze format/qualification structure on start. Walkovers and withdrawals are explicit outcomes.

### REQ-008

**Registration — Phase 1.** Self-entry and staff-entry; default staff acceptance. Track pending/accepted/waitlisted/rejected/withdrawn plus check-in separately. Enforce capacity transactionally. Doubles identifies two distinct players; teams identify roster and captain. Prevent the same player from appearing in competing entries within the same event. Entry fee is declared in Phase 1; detailed receipts arrive in Phase 2. Acceptance never falsely implies paid status. Waitlist promotion requires staff action and notification; recheck capacity.

### REQ-009

**Formats and draw publication — Phase 1.** Round robin, single elimination and groups-to-knockout, applicable to player/pair/team entries. Preview draw with seeds and explicit byes; publish a version. Tie matches are distinct from their individual constituent matches. Derive knockout participants from official qualified results. Corrections follow REQ-015. Capture the competition rules version with the event.

### REQ-010

**Tournament tabs and standings — Phase 1.** Always provide Brackets, Groups, Schedule, Standings. Brackets show rounds/byes/scores/current entry; Groups show members/fixtures/qualification; Schedule shows day/table/status and player filters; Standings explain rankings and tie-breaks. Non-applicable tabs explain the format. Offer a round-list alternative to a horizontally scrollable bracket. A public match detail never exposes an unauthorized Enter score control.

Before implementing qualification, transcribe the applicable ITTF group ranking rules into versioned fixtures: match points, tied-subgroup comparisons, game/point ratios, repeat subgroup resolution and ultimate unresolved-tie procedure. Cite the adopted clauses and explicitly represent unplayed/withdrawn matches. This rules-validation task is a prerequisite to draw/standings coding, not a runtime choice delegated to users. A shared exact-ratio comparator avoids rounded-ratio ties. Do not assign arbitrary unfinished knockout rankings.

### REQ-011

**Team ties — Phase 1.** Organizer defines an ordered template of singles/doubles rubbers and required wins; each side submits an eligible lineup before a tie begins. A rubber is an individual match with its own scoring/rating. Validate distinct partners and roster membership; player reuse across sequential rubbers is allowed. Run one rubber at a time per tie by default and stop when the required wins are reached. Unneeded rubbers remain not played and do not affect ratings. Reserve active rubber participants, not every team member for the entire tie.

### REQ-012

**Scoring — Phase 1.** Assigned umpire controls point entry, undo, initial server/receiver, end changes, one timeout per side, event log, and confirmation. Default best of five; allow three/seven; games to 11 with two-point margin. Rotate service every two points, every point after 10–10, and implement doubles order and deciding-game receiving/end changes. Undo reverses the last action through an audit-preserving compensating event. Explicit walkover/retirement flows cannot fabricate normal completed scores. Assigned umpire confirmation becomes official only after server validation. Timeout timing, penalty cards, injury suspensions, the expedite system, walkovers, retirements and disqualifications follow REQ-043.

### REQ-013

**Offline assigned scoring — Phase 1.** Download full assigned-match state before disconnection. Persist each score event in an IndexedDB transaction before acknowledging it in the UI. Event envelope includes unique ID, match ID, browser/device assignment ID, sequence, expected server revision, event type and device time. Device time assists media but is not authority for result ordering. Retry safely, deduplicating IDs and rejecting gaps/stale authority. One active device assignment per match; organizer reassignment invalidates old authority. Conflicts remain visible for organizer review, never last-write-wins. Pending finish reserves players/table until accepted. Reopening restores the deck and pending events. Global scheduling and progression require connectivity; this is not a venue-wide offline server.

Cache the versioned app shell through a service worker so the downloaded match reopens offline. Use account/assignment-scoped IndexedDB records and single-writer ownership across browser tabs; sequence allocation and ownership checks are transactional. On focus/reconnect, reread local and server revision before writing. Keep authenticated API responses, finances and private notes out of generic service-worker caches. Handle quota/write errors before displaying a score as saved. Request persistent storage where supported and show actionable storage failure; browser/user eviction cannot be guaranteed against. Reconnect/open/manual retry are mandatory; background sync is optional. Logout/account switching must protect pending scores through sync or an explicit resolution flow before purging account-local records.

### REQ-014

**Dispatch and reservations — Phase 1, extended in Phases 2/3.** Central reservation model covers all participating players and physical tables across events/organizations. At dispatch lock the relevant table/player resource records in stable order, recheck eligibility and create reservations in one database transaction. Future approved booking/training ranges cannot overlap; active matches block dispatch even after estimated end. Check official predecessors, participant check-in and rest. Default rest ten minutes; configurable per event. Umpires assigned as players must not simultaneously be dispatched elsewhere. Estimate schedules without guaranteeing exact start times.

On availability/result changes, rank ready matches by planned start, then ready-since waiting duration, then stable ID. Offer manual dispatch and optional organizer-enabled automatic dispatch. Explain blocked/idle tables. Recheck at execution even after a suggestion was displayed. Override actions cannot violate a player/table exclusivity invariant.

### REQ-015

**Official results and corrections — Phase 1.** Server acceptance atomically records the official result, releases active reservations, and writes durable progression/rating/notification work. Projection jobs are idempotent and may show processing status. Admin correction records author, reason, prior and replacement result. Invalidate/rebuild dependent projections. If a changed winner affects started downstream play, pause the affected event and require explicit resolution; never silently replace an opponent. Preserve history instead of deleting it.

### REQ-016

**Ratings — Phase 1.** Separate global singles/doubles Elo. Start 1000, K32, divisor 400. Expected score = 1/(1+10^((opponent-rating)/400)); delta = 32 × (actual−expected). For doubles compare pair averages; each partner receives its side's delta. Keep precision, round only for display. Rate normal completed competitive individual matches, including team rubbers; exclude casuals, walkovers, retirements/abandoned matches, unplayed rubbers and aggregate ties. Keep immutable rating-event order based on first official server acceptance plus stable ID; correction replay preserves that order. Expose before/after values, recent form, match count and win rate with explicit filters. Rank labels identify singles/doubles and platform/club scope; provisional processing is visible.

### REQ-017

**Quick Score — Phase 1.** Unrated singles/doubles scoring independent of tournaments. Local guest use allowed; authenticated players may save casual records. Claimed participant names do not grant permission to edit another player's profile or official history. Clearly label recorder-entered casual history. Casual results do not alter Elo/standings and do not create physical reservations.

### REQ-018

**Recaps and awards — Phase 1.** Result, games, participants, and competitive rating change; branded downloadable cards and public share links for published competitions. Mark processing if rating projection is pending. Derive placements; organizer selects discretionary awards and publishes winners announcement. Do not infer aces/rally lengths/shot types from score presses. Link to private analysis when Phase 3 is available.

### REQ-019

**Notifications — Phase 1 onward.** Persistent inbox with read state, category preferences and optional browser push where supported. Feature-detect push/install capabilities and explain device-specific setup; the inbox remains available when push is unsupported or denied. Native push is deferred to the native follow-on. Triggers: next eligible queue position, table call, changed/cancelled assignment, registration decision, announcement/awards; later booking/dues/highlights. Distinguish Up next from Called to table. Version assignments and deduplicate by recipient/event/version/channel. Cancel stale pending push jobs; previously delivered alerts resolve to current state. Push is best effort; inbox is durable. Broadcast audience is explicit (organization, event or named participants).

### REQ-020

**Public and private boundaries — all phases.** Published competition pages show limited names, ratings, draws/results and awards. Public serializers use explicit allowlists. Private data includes contacts, notes, staff fields, finances, training commitments, and unpublished media. Player directory visibility does not override public competition records. Signed attachments/playback require authorization at issue time and short expiry. Revoked access blocks new links; already downloaded public media cannot be recalled. Use named test users and organizations in privacy tests.

### REQ-021

**Facility bookings — Phase 2.** Opening hours, closures, table slots, fees, and request/approve/reject/cancel lifecycle. Pending requests do not block capacity; approval atomically checks REQ-014. Organizer sees requested and approved states distinctly. Cancellation releases future reservations; completed bookings stay in history. Fees and cancellation adjustments are recorded manually and auditably; no automatic online refund promise.

### REQ-022

**Payments — Phase 2.** Record currency, integer minor-unit amount, method (cash/external), received date, reference, payer, recorder and allocations. Allocate to event fees, booking charges or dues. Prevent over-allocation; keep unmatched excess as visible credit pending allocation. Receipt references assist reconciliation but are not universally unique payment identities. Reverse erroneous records with reason and recompute balances; retain original. No payment processing in launch phases.

### REQ-023

**Contributions — Phase 2.** Multiple purpose campaigns with title/description, amount, selected members and one-time/weekly/monthly/quarterly/yearly cadence. Snapshot each generated due; idempotent generation key campaign/member/period. Monthly dates clamp to the final valid day; edits affect future ungenerated periods. Track pending/partial/paid/overdue/waived; partial overdue amounts remain visibly overdue. Members see their own dues and purpose totals. Authorized staff record waivers with reasons. Joining a club does not retroactively create old dues. Club operations dues are the standard case (user decision, 2026-11-15): a club can run a weekly or monthly "Club operations" campaign (offered as a ready-made template) that all active members owe by default, with per-member amount overrides or waivers (e.g. juniors, honorary members), and its REQ-024 expenses cover running costs such as hall/table hire, balls, nets, repairs and utilities so members see what their dues paid for. New members start owing from the next period after joining; leaving stops future dues but keeps earlier ones.

### REQ-024

**Spending transparency — Phase 2.** Expense purpose, amount, date, description and private receipt. Retain reversals/corrections. Show actual received allocations, actual expenses, and remaining funds separately from expected dues. Financial staff can inspect individual balances; members see own balances and shared purpose summaries. Expenses may exceed receipts but must visibly show the deficit; no silent invented funds. Separate campaign balances from platform subscription revenue.

### REQ-025

**Match analysis — Phase 3.** Player-owned private notes linked to a match, observations, improvement goals and timestamps. Only the owning player can read/edit through normal product APIs; club roles do not grant note access. No coach sharing in this phase. Casual and competitive match links supported. For official (umpire-confirmed) matches the player may add and edit only these private notes; the official sets, scores and result are read-only to them (user decision, 2026-10-03). Self-recorded matches are covered by REQ-037.

### REQ-026

**Equipment and drills — Phase 3.** Optional blade/forehand/backhand free-text equipment. Personal private and club-visible drill libraries with instructions, focus, duration, repetitions and equipment. Owners edit personal drills; training permission edits club drills. Equipment data makes no automatic performance claim.

### REQ-027

**Training — Phase 3.** Personal plans with completion tracking and scheduled commitments. Staff create club sessions, reserve tables, invite members and record attendance. An invitation does not reserve a player's time until acceptance; accepted commitments use REQ-014. A non-calendar checklist is not a reservation. Unavailable table/player produces conflict feedback before confirmation.

### REQ-028

**Recording — Phase 4.** One featured table, fixed camera/phone and OBS laptop. Test 1080p50/60 local capture; outbound format depends on destination. Full table and both players in frame. Keep local recording independently of uplink; associate recording sessions/segments with table and match intervals. Model media-time-to-score-time offsets per continuous segment, recalibrating after reconnects. Capture status is distinct from social live status. Privacy, retention, and publication policy must be resolved before recording real participants.

### REQ-029

**Highlights — Phase 4.** Manual highlight markers plus score-derived candidate moments (deciding finishes, match-winning points, close scores). Store candidate start/end, source segment, event link and review state. Organizer adjusts boundaries and approves publication. Python/FFmpeg creates branded clips and tournament recaps using bounded background jobs. Idempotent processing, failed-job retry, player gallery and ready notification. AI later proposes candidates; it does not certify longest rally or other unmeasured statistics. Private recordings remain protected until approved publication.

### REQ-030

**Social broadcasting — Phase 5.** mombasa-tt controls selected destinations while OBS supplies the feed. Managed relay provisionally Cloudflare Stream; current capability/cost confirmation is a prerequisite. Facebook/Instagram/TikTok connections are conditional on actual account access; support supplied URL/key workflows and external confirmation where required. Encrypt secrets and audit control actions without logging keys. Separate selected/enabled/receiving/live/failed states; show platform confirmation uncertainty. Keep external watch links in app, not a required app-hosted audience. Portrait composition must preserve both players. Local capture continues when a destination fails. No broadcast is started by merely saving settings.

### REQ-031

**Organization subscriptions — Phase 6.** Organizations pay for platform plans; club member contributions are separate. Plan prices, provider, entitlement matrix, usage units, trial/grace/cancellation/refund/tax policies and downgrade behavior require approval before implementation. Preserve tenant data through expiry; avoid abruptly terminating active tournament scoring. Later contract includes organization subscription, versioned entitlements, invoice/provider references, usage records and idempotent billing events. Never display unapproved prices as commercial offers.

### REQ-032

**API contracts and security — foundation.** Version `/api/v1/`; OpenAPI types; UUID resource IDs; UTC ISO timestamps; explicit pagination/filters; money `{amount_minor,currency}`; errors carry code/message/field details and request ID. Resource groups: auth, organizations/memberships/roles/fields, players, tournaments/events/entries, matches/score-events/results, reservations/bookings, ratings, notifications, contributions/payments/expenses, training, and later media/subscriptions. Expected-revision conflict uses HTTP 409. Idempotency keys scope to actor/operation and validate payload reuse. Public read endpoints return only published fields. Validate attachments, rates and object ownership server-side. Store no credentials in source or public web bundles.

### REQ-033

**Reliability and observability — all phases.** PostgreSQL owns durable state and outbox; Redis is not the only copy of work. Atomic mutations enqueue outbox records; workers retry with dedupe and failed-job inspection. One scheduler prevents duplicate periodic dispatch. Track API health, latency/errors, job age/failures, disk, push errors and backup freshness without sensitive payload logging. Launch load target: eight tables, 100 simultaneous app connections, 15-minute steady test; core API p95 <500ms and score visibility p95 <2s in controlled conditions. These are acceptance targets, not measured capacity claims.

### REQ-034

**Hosting/recovery — foundation and launch.** Full ASGI/worker deployment on Contabo or Namecheap VPS. Namecheap shared hosting can serve React static assets with API on VPS. Use deployment.md for configuration, least-exposed network, staging, backup, restore, migration and rollback. Target RPO 15 minutes and RTO four hours, demonstrated by restore, not inferred from backup success. Test off-site database and attachment recovery; snapshots supplement backups.

### REQ-035

**PWA installation/update compatibility — foundation and launch.** HTTPS, manifest with name/icons/start URL/scope/display/theme, versioned app-shell service worker and offline fallback. Validate Android and iOS browser/home-screen installation experiences with capability-aware instructions. Expose an update-available action; defer activating a new service worker/reloading while a match is active or unsynced events exist. Migrate IndexedDB without discarding pending events. API remains compatible with cached older PWA bundles; handle unsupported-client versions without deleting queued scores. An install is not required for public pages or online use. No app-store signing/EAS pipeline in launch. Later native follow-on adds Expo build profiles, SQLite journal, secure tokens, push and store/update compatibility evaluations against the shared API.

### REQ-036

**Documentation and design gate — Phase 0.** Complete these five linked files, then generate/review Stitch screens before application code. Screen inventory records ID/title/device/phase/requirements and known gaps. Mark tasks complete only with evidence. Mock screenshots do not prove runtime behavior. Preserve future phases as designed/deferred, not launched. Content changes update linked tasks/evaluations in the same change.

### REQ-037

**Personal match log — Phase 1 (user decision, 2026-10-03).** An authenticated player can record matches they played outside official mombasa-tt scoring: date, a free-text label of their choosing (suggestions such as Friendly, Tournament, Practice, League; previously used labels offered again), singles/doubles, free-text opponent (and partner) names, optional venue, set-by-set points, and notes. The record is personal data owned by the recording player: only that player can list, read, edit or delete it; club roles, platform staff APIs, public pages, directories and other players never see it. Free-text names never link to, notify, or grant edit rights over another player's identity. Each set needs a winner; the match result is derived from sets won. Progress summaries (played/won/lost, win rate, by label, recent form) are computed only from the owner's records. Personal records never alter Elo, standings, official history, or reservations, and are always labeled as self-recorded. Matches scored officially on mombasa-tt are not re-entered here: their scores are read-only and the player adds private notes per REQ-025.

### REQ-038

**Welfare projects — Phase 2 (user decision, 2026-11-15).** Club staff with the welfare permission set up a welfare project for a shared cause, for example supporting a sick or bereaved member, with a title, purpose description, optional beneficiary member, suggested contribution per member (e.g. KES 50 as `{amount_minor,currency}`), optional target and deadline, and audience (all active members or selected members). Contributions are voluntary unless staff explicitly make the project a due under REQ-023; a suggested amount never creates an overdue status on its own. Contributions are recorded manually through the REQ-022 ledger (cash/external, no payment processing) and allocated to the project; spending such as a hospital visit gift uses REQ-024 expenses, so received, spent and remaining amounts reconcile and show deficits. Members see the project, the total raised against the target, and their own contribution; per-member amounts are visible only to financial staff unless the club opts to show a contributor list, and each contributor may stay anonymous in it. The beneficiary's health or personal circumstances are sensitive: staff write only what the beneficiary (or their family) agreed to share, the beneficiary can ask staff to hide the project, and no medical detail appears in notifications, public pages or directories. A project can include a planned visit or support activity (date, meeting point, who is going) using REQ-039 activities. Projects close manually or at the deadline; closing keeps the ledger and summary read-only.

### REQ-039

**Club activities and schedule — Phase 1, cost sharing in Phase 2 (user decision, 2026-11-15).** Staff with the activities permission post club activities beyond competitions: social nights out, fun days, group visits (including REQ-038 welfare visits), meetings and practice nights. An activity has title, type, description, start/end in the organization timezone, venue or meeting point (free text, no precise member locations), audience (all members or selected members), optional capacity and RSVP deadline, and draft/published/cancelled state; cancellation keeps the record with a reason. Members RSVP going/maybe/not going; capacity applies transactionally to "going" and full activities offer a waitlist without automatic promotion. The club schedule lists published activities together with the organization's published tournaments and club training sessions (REQ-027) in date order, with upcoming/past views, type filters and an add-to-calendar (.ics) export; it is visible to members only, never public, unless an activity is explicitly marked public. Publishing, changing time/venue and cancelling notify the audience through REQ-019. Attendee lists are visible to members of the audience as display names only. In Phase 2 an activity can carry a per-person cost or shared expense tracked through a REQ-023 one-time campaign and REQ-024 expenses; Phase 1 shows a cost note only and never implies payment.

### REQ-040

**Soda games (friendly challenges) — Phase 1, stakes behind a policy gate (user decision, 2026-11-15).** A player challenges another player (same club or any player reachable through the opted-in directory) to a friendly singles or doubles match called a soda game. The challenge carries date/time or "next time we meet", optional venue, best-of, a message, and an optional stake: the amount the challenger pledges to pay if they lose (`{amount_minor,currency}`, e.g. KES 100, or a soda). The challenged player can accept and match the same stake, accept and play without staking, propose a new time, or decline; the challenger may withdraw before acceptance. When only the challenger staked, only the challenger owes on a loss. The match is scored through Quick Score (REQ-017) or recorded by both players; the result needs confirmation by both players (or an assigned umpire) before the stake outcome is shown, and a disputed result shows "disputed" with no amount owed. Soda games are unrated, never affect Elo, standings or official history, and do not reserve tables (REQ-014). mombasa-tt only records the pledge and lets the winner mark it "settled"; it never collects, holds or transfers money, sets odds, or lets anyone other than the two players stake, so no spectator or third-party betting. Stakes are visible only to the two players; club members see the challenge and result only if both players allow it. Organizations can disable stakes, or soda games entirely, for their members. Enabling stakes in production requires a recorded legal/policy sign-off (Kenyan betting and gaming law, minimum age 18, stake limits); until then the stake fields stay hidden and soda games run without stakes.

### REQ-041

**Annual financial report — Phase 2 (user decision, 2026-11-15).** Club officials with the finance permission record every club expense in mombasa-tt (purpose/campaign, category such as hall hire, equipment, welfare, events, transport, amount, date, payee, description, private receipt, recorder) as the single source for the club's accounts; corrections use REQ-024 reversals, never edits that erase history. At the end of the club's financial year (configurable year-end date, default 31 December, organization timezone) officials generate a report for the period: opening balance, receipts by campaign (operations dues, welfare projects, event fees, other), expenses by category and campaign, closing balance, outstanding dues total, waivers total, and deficits shown as negative. Officials review a draft, add a narrative summary, and publish it; publishing freezes a versioned snapshot with publisher and time. Members of the organization see published reports (aggregates only, no individual member balances, payer names or receipts); the club may optionally make a report public. A later correction to a reported period never changes the published snapshot silently: officials publish an amended version that lists the changes and keeps the original visible. Reports export to PDF/CSV. Arithmetic must reconcile exactly with the REQ-022/REQ-024 ledger for the period.

### REQ-042

**Events calendar and live links — Phase 1 (user decision, 2026-11-15).** A public events listing shows table tennis tournaments and events happening in the country, both those run on mombasa-tt (REQ-007, including our own club's) and external events run elsewhere. External events are listings only: name, organizer, dates and timezone, venue and town, categories (e.g. singles/doubles, juniors, open), entry information, official info link and optional live stream link; they carry no draws, entries or ratings in mombasa-tt. Club staff with the announcements permission submit external events; a platform curator reviews them before they appear publicly (members of the submitting club see them immediately, marked "awaiting review"). Listings offer list and month-calendar views, filters by town, category, host club and "our club", and a countdown for upcoming events. When an event is live (within its scheduled times, or marked live by its organizer/curator) it shows a "Live" badge and the live link: for mombasa-tt events the live tournament page and any REQ-030 broadcast; for external events the submitted live stream URL. Links must be https, open in a new tab with the destination domain shown, and can be reported and removed by curators. Past events stay listed with results links where available. Cancelled or postponed events stay visible with their status.

### REQ-043

**Match-day operations — Phase 1 (user decision, 2026-11-15).** Tournament staff run the whole match day in mombasa-tt: schedule, tables, check-in, calling, live scoring, incidents, walkovers and results announcements. Referee is a tournament role granted through the competitions permission (REQ-005); umpires act only on matches assigned to them.

*Schedule.* Staff build each day as sessions (date, start time, tables, rounds/groups included) and the system estimates match times from best-of, estimated match length and rest (REQ-014). Staff move a match to another table or slot or reorder within a session; every move is rechecked against reservations and never violates player/table exclusivity. Publishing creates a versioned day schedule shown in the Schedule tab (REQ-010) with "times are venue local, estimates only"; changing a published match's table or time by more than a configurable threshold (default 15 minutes) notifies its players and umpire (REQ-019) and keeps the prior version in history. Delays (late start, table out of service) shift the estimates of the affected table's remaining matches.

*Control centre.* A desktop/tablet match-day board shows every table (free, called, warming up, in play, blocked with reason), the ready queue, matches awaiting a called player, and live scores. From it staff check players in, assign or reassign umpires and tables (REQ-013 device authority), call a match (REQ-019 "Called to table"), recall, and record no-shows. A called player who has not reported within the event's grace period (configurable, default 10 minutes) is flagged; only the referee can then award a walkover. Every staff action is audited with actor, time and reason.

*Live scoring in real time.* Accepted score events reach public and member live views (tournament page, match detail, score strip, REQ-042 live badge) within the REQ-033 target (p95 under 2 seconds in controlled conditions) over a server push channel, with polling fallback. Viewers see game score, games won, server, timeouts used, cards shown and match status; they never see umpire controls (REQ-010).

*Timeouts.* Each player or pair may take one timeout of up to one minute per individual match, requested by the player/pair or their adviser and recorded by the umpire. The deck shows a countdown and logs start and end; play resumes early when the requesting side is ready. A side cannot take a second timeout in the same match.

*Penalty cards.* Cards are explicit umpire actions with a required reason category (e.g. bad behaviour, racket abuse, illegal advice, delay) and optional note, logged as score events and shown in the live view. Player misbehaviour ladder per individual match: first offence yellow card (warning); second offence yellow+red, one penalty point to the opponent; third offence yellow+red, two penalty points to the opponent; a further offence suspends play and calls the referee, who may disqualify (red card). Adviser misbehaviour: yellow card warning, then red card sending the adviser away for the rest of the match (team event: the rest of the tie). Penalty points are scoring events that obey normal game and service rules and can end a game or match. In a team tie, warnings and penalties carry across that tie's rubbers. The referee can also disqualify directly for serious misconduct. Exact carry-over details and the ladder are encoded in the TASK-003 reviewed rules fixtures before implementation; configuration may not weaken them for sanctioned events.

*Injury suspension and expedite.* The referee can grant a suspension for accidental incapacity of up to 10 minutes, with a countdown; a player who cannot resume retires. The expedite system can be started by the umpire or referee under the rules fixtures (time limit in a game, with the receiver winning the point after the required number of returns); while active the deck shows the return count and alternates service accordingly.

*Walkovers, retirements, disqualifications.* Outcomes are explicit and never fabricate scores: walkover (W/O) with reason (no-show after grace, withdrawal before start, injury before start), recorded with no game scores; retirement (ret.) keeps the points played and awards the match; disqualification (DQ) keeps the points played, records the referee's decision and can remove the player from later matches in the event. All three are excluded from Elo (REQ-016), propagate to brackets and groups per the rules fixtures, and are audited; corrections follow REQ-015.

*Results announcements.* Staff generate a results announcement for a session, round, day, event or the whole tournament. The generator builds a draft only from official results: each match with both sides in the same first/second order as the match card (REQ-002 left/right), games won and per-game scores (e.g. "3-1 (11-7, 9-11, 11-5, 11-8)"), W/O, ret. and DQ marked, winners and podium/placements (REQ-018), group standings where applicable, and outstanding matches listed as pending. It never invents commentary, shot descriptions or rating values not yet projected. Staff edit the draft text, preview it as a plain-text post (for WhatsApp and social media) and a branded image card, and publish it to the tournament news feed (members or public according to the tournament's publication state), with optional notification (REQ-019) and copy/share actions. Publishing freezes the version; a later result correction marks the post outdated and offers an amended version that keeps the original visible.

## Planned entity groups

| Domain | Records and ownership |
|---|---|
| Identity | User, Player, Session, Invitation; global |
| Organization | Organization, Membership, Role, PermissionGrant, FieldDefinition/Value; tenant scoped |
| Competition | Tournament, Event, Entry, Pair, TeamRoster, Tie/Rubber, Group, DrawVersion, Match, ResultRevision |
| Operations | Venue, Table, Availability, Reservation, DeviceAssignment, ScoreEvent, OutboxEvent, ScheduleSession/ScheduleVersion, CheckIn, MatchCall, MatchIncident (timeout, card, suspension, expedite), RefereeDecision, ResultsAnnouncement/AnnouncementVersion (REQ-043) |
| Projections | RatingEvent/Projection, StandingProjection, Notification, PushSubscription |
| Finances | Charge, Campaign, Due, Payment, Allocation, Waiver, Expense, Reversal, WelfareProject (REQ-038), FinancialYear, AnnualReport/ReportVersion (REQ-041) |
| Club life | Activity, ActivityRSVP, Schedule projection (REQ-039); tenant scoped. Challenge (soda game) and StakePledge (REQ-040); owned by the two players. ExternalEvent listing and curation (REQ-042); platform scoped |
| Development | PersonalMatch/PersonalGame (REQ-037), MatchNote, EquipmentProfile, Drill, TrainingPlan/Session, Invitation/Attendance |
| Media later | RecordingSession/Segment, TimeMapping, Marker, Clip, ProcessingJob, Publication, Destination |
| Billing later | OrganizationSubscription, PlanVersion, Entitlement, UsageRecord, BillingEvent |

An entry is a player/pair/team. A game is a points contest; a match is best-of-games; a team tie contains individual rubbers. Reservations represent actual resources, not just calendar labels. This terminology is shared by API, UI and tests.

## Stitch inventory and missing coverage

Project: [1275312862625402020](https://stitch.withgoogle.com/projects/1275312862625402020). Existing screens inspected 2026-09-07; creation of new screens has not started at document creation.

| Existing screen ID | Title | Treatment |
|---|---|---|
| a2d00d4913344cbf8b0cef147a2a727d | PongForge Home Screen | Adapt brand/navigation; add next call and operational actions |
| 90d3b622797c4c528922f05861df3008 | PongForge Match Scoring | Adapt deck; add offline and official confirmation |
| 802d5d30a4a74b74b6fa952148a3c37d | Tournament Bracket View | Preserve four-tab model; provide other selected-tab states |
| 430bb5802cb446e2b39bbe10fabf4b3d | Detailed Player Profile | Separate ratings/privacy; remove challenge/chat promises |
| ea0ef10e404d4e50aa550f0f6c5d17b7 | Welcome Splash | mombasa-tt branding |
| 8cd1bcdd8da848daa97b7189501026b5 | Sign Up | Email/password; remove unsupported social buttons |
| 5f3fc1bfbefb4b99a35229492ee7d3a3 | Profile Setup | Optional enrichment |
| 7e672d9f2dc943b2b84678d76cd5967d | Equipment Setup | Phase 3; skippable free-text |
| e7bc276ec8d34119afbe1bbd31d965ee | Find Community | Town-based club/player discovery and approval |
| 25fcf09db6cb48afa7a64800bac488a6 | User Goals | Personalization, no automatic privileges |
| 63d6b49eeb6d43e394fb53dd1c3c5cee | Completion | Real next actions; no invented level/pro status |
| 975d457e60b8469aae8549f8317232c7 | Match Highlights and Media | Separate Phase 1 recap and later reviewed video; remove unsupported metrics |

Required new coverage: tournament creation/registration/check-in; selected Groups/Schedule/Standings; team lineup; desktop dispatch board; club administration/role editor/custom fields; notifications/preferences; score recovery/correction; booking/approval; campaign and member balances/expense detail; welfare project setup/progress (REQ-038); club activity, RSVP and club schedule (REQ-039); match-day control centre, schedule builder, umpire incident controls and results announcement editor (REQ-043); analysis/drills/training; later recording/highlight review/broadcast studio/organization-plan concept. Use suitable mobile and desktop layouts rather than squeezing every workflow into one screen. Store generated IDs here and evaluate through EVAL-036 before coding.

### Generated design inventory — 2026-09-08

Design system: `assets/4831977112676050334`, **mombasa-tt Coastal Club**. Explicitly attached to the new screen-generation requests. Creating the asset succeeded; the separate project-wide update call returned an invalid-argument error, so the legacy project theme must not be assumed updated.

| Screen ID | Title | Device | Phase / requirements | Review status |
|---|---|---|---|---|
| 2cfb06b593ae4b318a45cdbe0b76f0a6 | Tournament Groups | Mobile | 1 / REQ-010 | Generated; show all four text tab labels; align roster |
| c0fab481f40249619713ba70afadf788 | Tournament Brackets | Mobile | 1 / REQ-010 | Generated and retrieved by ID; reduce blank space, add round labels |
| 87cacc81b9b34a269df8d15c3f3e79c8 | Tournament Schedule | Mobile | 1 / REQ-010, REQ-014 | Generated; add text tabs/date/filter/called state |
| 3c02127d47b34a608068d13ab6885b92 | Tournament Standings | Mobile | 1 / REQ-010 | Generated; align fictional roster across views |

| 1252ed391e4a4fefa948f632395e5cbc | Mombasa TT — Player Home | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 7a3d6603347c455891aa2193c2f39f61 | Mombasa TT — Profile & Recap | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| f351002dcc3541ffa5bc08e3854b9ced | Mombasa TT — Umpire Scoring & Sync Recovery | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 05228091d90e45c4857f399f78f6eec0 | Mombasa TT — Notifications & Preferences | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 8637a73dfb614371a7c6d3d1c1ac1e09 | Table Booking Request | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| b726a6ad4ff642d8bed4638024284a6d | Club Contributions & My Dues | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 3cc9246f94124177b11dc729c1108016 | Contribution Spending & Manual Receipt | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 5e9a6694d4ba4e1ca5684f1a661d50e3 | Training and Drills | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 4e2a65b8cb134fe3a66181f61b75fb03 | Private Match Analysis | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 19cd64fe3fa2443da008a099ef9c4bdd | Club Session and Equipment | MOBILE | See workflow requirements | Generated draft; full layout gate pending |
| 023b6deb09b346e0941e798401c66647 | Phase 4 Concept: Recording & Highlight Review | DESKTOP | 4 | Generated draft; full layout gate pending |
| 630367c073e443448d7e8b11c82645e2 | Phase 6 Concept: Organization Plan Overview | DESKTOP | 6 | Generated draft; full layout gate pending |
| a62988406947474993544f8795b6a9d5 | Phase 5 Concept: Social Broadcast Studio | DESKTOP | 5 | Generated draft; full layout gate pending |
| ad61a4227ed641a3aba68473f778ef1c | mombasa-tt — Tournament Setup | DESKTOP | See workflow requirements | Generated draft; full layout gate pending |
| 86ffa3812546480cbe1758bd010ffd3f | mombasa-tt — Live Table Dispatch | DESKTOP | See workflow requirements | Generated draft; full layout gate pending |
| 4806848e4f6e45e58fd41d2a08977c4d | mombasa-tt — Club Roles & Member Fields | DESKTOP | See workflow requirements | Generated draft; full layout gate pending |
| beee1f9f0a7043afbfb07d24175aa253 | mombasa-tt — Registration & Check-in | DESKTOP | See workflow requirements | Generated draft; full layout gate pending |

The four tournament screenshots were visually reviewed. They establish the palette/layout direction but do not yet pass the full design gate. Stitch's screen-list response may lag generated screen IDs; use direct screen retrieval to verify artifacts. The four-screen organizer request timed out but its completed screens were subsequently recovered without duplicate generation.

Review follow-ups: apply the mandatory left/right rule to every comparison; make all four tournament tab labels visible; align fictional rosters and dates; keep next-match calls prominent; remove online-payment implications from manual contribution tracking; review the recovered organizer and future concepts. The original tall umpire draft is superseded by scoring-deck refinement `fc592c651fa940a6ac2208f897d8175b`, superseded in turn by reference-driven revision `c48eab3033f14a959b32b52c87c79dc3` (mombasa-tt — Refined PWA Scoring Deck). Its screenshot was visually checked on 2026-09-08: players and scores remain left/right, with game history, service, horizontal controls and a compact event log. Responsive widths, text zoom and interaction behavior still require implementation evaluation; the screenshot alone does not establish those guarantees. TASK-002 remains open until coverage and visual checks pass.

## Layout reference: WTT (guidance only, user decision 2026-11-15)

The user shared World Table Tennis (worldtabletennis.com) screens as layout and information-design guidance. Follow the patterns below; do not replicate WTT pages exactly. Never use WTT names, logos, colours, photography, event branding or copy: mombasa-tt keeps its own REQ-002 tokens, wordmark and mobile-first layouts, and every screen is still generated and reviewed through Stitch (REQ-036).

| Pattern seen in the reference | Where it applies in mombasa-tt |
|---|---|
| Live score strip above the navigation: compact cards per match with event/round, both sides, sets won, game scores, winner tick | Live tournament header on public and tournament pages (REQ-010, REQ-014); scroll horizontally on mobile |
| Match cards: round title, venue/table line, sets-won headline (e.g. 3-2), per-game points with winner games emphasised, link to match detail | Completed matches list, Quick Score and personal match log cards (REQ-010, REQ-017, REQ-037); keep the mandatory left/right rule |
| Matches tabs Completed / Scheduled / Draws with filters by event, sub-event, date and a search by player/round/table; "times are venue local" note | Tournament navigation (REQ-010); our four tabs Brackets, Groups, Schedule, Standings stay authoritative, filters and timezone note carry over |
| Scheduled match cards: date-time, round, both sides with seed/WC markers, table/area, status chip | Schedule tab and dispatch board (REQ-010, REQ-014) |
| Bracket columns per round with connector lines, winner row highlighted, date/table under each pair, empty future slots | Brackets tab (REQ-010); offer the round-list alternative on mobile |
| Event list as large cards with dates, venue, town, sub-event chips and a countdown; calendar view grouped by month with date range, category colour bar and winners | Tournament list and the members-only club schedule month view (REQ-007, REQ-039) |
| Event detail tabs Overview / Matches / Draws / Groups / Player list / Event info, with a provisional schedule grouped by day, then sessions (venue, tables, start time, rounds) | Tournament detail and published day schedule (REQ-007, REQ-010) |
| Match centre: two sides with head-to-head table (hand, grip, style, matches won) and upcoming status | Pre-match detail using only REQ-006 fields players chose to show; no age or nationality unless the player published it |
| Match page: final score hero, game-by-game table, point-by-point commentary timeline (point, serve change, game/match point, completion), per-game stats tabs (points won, on serve, biggest lead, most consecutive, deficit overcome), score-progression chart | Official match detail and recap (REQ-015, REQ-018), derived only from recorded score events; never infer shot types (REQ-018) |
| Ranking table: rank with movement arrow, player, club, points; expandable row showing which results contribute | Ratings leaderboard (REQ-016) with expandable rating-change history per confirmed match |
| Player list with search and filters; player profile hero with ranking, win/loss %, hand/style and related matches | Player directory and public player page (REQ-006, REQ-016), opted-in data only |
| News cards with category tag, headline, excerpt | Club announcements and awards posts (REQ-018, REQ-019) |

## External references

- [ITTF statutes and regulations](https://www.ittf.com/statutes/) — source for the versioned competition-rule validation task.
- [NativeWind Expo installation](https://www.nativewind.dev/docs/getting-started/installation) — reference for the deferred native follow-on only; launch styling uses Tailwind CSS on the React PWA.
- [OBS recording/streaming overview](https://obsproject.com/kb/obs-studio-overview) and [FFmpeg](https://www.ffmpeg.org/faq.html) — later media pipeline.
- Provider-specific deployment sources and dates are maintained in deployment.md.
