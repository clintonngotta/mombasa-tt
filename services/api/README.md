# mombasa-tt API

Django + DRF service for the mombasa-tt PWA. Versioned under `/api/v1/`; OpenAPI schema at `/api/v1/schema/`.

## Local development

```sh
# from the repo root: PostgreSQL 17 on 127.0.0.1:5433
docker compose -f infra/compose.dev.yml up -d --wait

cd services/api
cp .env.example .env          # first time only
uv sync
uv run --env-file .env manage.py migrate
uv run --env-file .env manage.py seed_dev     # test logins, DEBUG only
uv run --env-file .env manage.py runserver 8010   # http://127.0.0.1:8010
```

The web dev server (`apps/web`, port 5173) proxies `/api` to `127.0.0.1:8010` (8000 is often taken by other local projects), so the browser sees one origin and the
session/CSRF cookies work without CORS. Override the target with `VITE_API_PROXY_TARGET`.

Emails (verification, password reset) print readable bodies and copyable links to the `runserver` console unless
`SMTP_HOST` is set. The local preview backend avoids MIME transfer encoding so long links remain intact.

### Test logins (`seed_dev`)

| Email | Password |
|---|---|
| `player@mombasa-tt.test` | `mombasa-tt-dev` |
| `umpire@mombasa-tt.test` | `mombasa-tt-dev` |
| `admin@mombasa-tt.test` | `mombasa-tt-dev` |

All three belong to "Mombasa Dev TT Club": admin as Admin, umpire as Assistant captain, player as a plain member.
Re-running the command resets their passwords and club roles. Override the password with `DEV_LOGIN_PASSWORD`. The
command refuses to run when `DJANGO_DEBUG` is off.

## Attachments

Uploaded files (profile photos so far) are private. They are stored through `STORAGES["attachments"]` (a local
folder, `ATTACHMENTS_ROOT`, default `var/attachments`) and are never served directly. A client gets a file only
through a signed link: the API checks the viewer's access (`attachments/access.py`), then issues a link that works
without a session for `ATTACHMENT_URL_TTL` seconds (default 300). `GET /api/v1/attachments/<id>/url/` issues a
fresh link. Images are re-encoded on upload, which also removes location and camera metadata.

## Checks

```sh
uv run --env-file .env pytest
uv run ruff check . && uv run ruff format --check .
uv run --env-file .env manage.py makemigrations --check --dry-run
```

### API contract

`openapi.yaml` is the committed schema; `packages/contracts/api-schema.d.ts` is generated from it and used by the web
app. Every operation documents the `ApiError` envelope as its 4XX reply (`core.schema.contract_hook`). After changing a serializer or view, regenerate both; CI fails when either is stale:

```sh
uv run --env-file .env manage.py spectacular --fail-on-warn --file openapi.yaml
cd ../../apps/web && pnpm gen:api
```

CI (`.github/workflows/ci.yml`) also runs ruff, migration drift, pytest, `pip-audit`, oxlint, the web build,
`pnpm audit --prod` and a gitleaks secret scan on every PR into `dev` and `main`.

## Auth endpoints (`/api/v1/auth/`)

| Method | Path | Notes |
|---|---|---|
| GET | `csrf/` | Sets the `csrftoken` cookie |
| POST | `signup/` | Always 201 with the same body; an existing address gets an "already registered" email |
| POST | `verification/resend/` | Always 202 |
| POST | `verification/confirm/` | `{token}`; verifies and signs in |
| POST | `login/` | `invalid_credentials` for unknown email or wrong password; `email_unverified` only after a correct password |
| POST | `logout/` | Flushes the session |
| POST | `password-reset/` | Always 202 |
| POST | `password-reset/confirm/` | `{uid, token, password}`; single-use; ends every other session |
| GET | `me/` | 401 without a session |

Errors share one shape: `{code, message, fields, request_id}`. Login and the email endpoints are rate-limited per IP.

## Profile and onboarding endpoints (`/api/v1/me/`)

| Method | Path | Notes |
|---|---|---|
| GET, PATCH | `profile/` | Display name (stored on the user), nickname, hand, grip, style, experience, bio, `directory_opt_in` (off by default), `published_details` (which of hand, grip, style, experience, bio show on the player page; empty by default). `avatar` is read-only here: a signed link `{id, url, expires_at}` or null |
| PUT, DELETE | `avatar/` | Profile photo. `PUT` is a multipart upload with `file` (JPEG, PNG or WebP, up to 5 MB; 400 with a `file` message otherwise) and returns the profile; the image is re-encoded to a 512px WebP without metadata. `DELETE` is 204. Limited by `THROTTLE_UPLOADS` (default `30/hour`) |
| PUT | `goals/` | `{goals: [...]}` replaces the list. Goals only order Home shortcuts and never grant roles |
| POST | `onboarding/complete/` | 204. Repeat calls keep the first completion time |
| GET | `memberships/` | Active memberships with their organization, roles held and effective `permissions` (basis for the club switcher and for which staff actions the app shows); paginated |
| POST | `memberships/{mid}/leave/` | 204; drops the player's roles. 409 `last_admin` if they are the organization's only admin |
| GET, PATCH | `memberships/{mid}/fields/` | The player's own member-visible custom fields here, each as `{field, value}`. PATCH `{values: {field id: value}}` changes the ones named (null clears an optional one). Staff-only and retired fields are never listed and their ids are a 400, the same as unknown ids |
| GET | `join-requests/` | The player's own join requests with the organization (name, town, kind), newest first; paginated |
| GET | `invitations/` | Open invitations addressed to the player's verified email; paginated |
| POST | `invitations/{iid}/accept/` or `decline/` | Accepting joins as a member (an existing member keeps their roles) and withdraws the player's open join request to that organization; 404 for anyone else's, answered, revoked or expired invitation |

## Organizations and directory

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/organizations/?search=` | Matches name or town; paginated |
| POST | `/api/v1/organizations/` | `{name, town, kind}`; the creator becomes the first admin |
| GET | `/api/v1/organizations/{id}/` | |
| POST | `/api/v1/organizations/{id}/join-requests/` | 201 new, 200 if one is already pending, 409 `already_member` |
| GET | `/api/v1/organizations/{id}/join-requests/` | Pending requests, paginated; needs `members.manage` (403 `permission_denied`) |
| POST | `/api/v1/organizations/{id}/join-requests/{rid}/approve/` or `reject/` | Needs `members.manage`; 409 `already_decided` |
| POST | `/api/v1/organizations/{id}/invitations/` | `{email}`, needs `members.manage`. 201 new, 200 if already pending (renews a lapsed one and resends). Same reply and email whether or not the address has an account or belongs to a member. Expires after 14 days; throttled per sender (`THROTTLE_INVITATIONS`, default 30/hour) |
| GET | `/api/v1/organizations/{id}/invitations/` | Open (pending, unexpired) invitations, needs `members.manage`; paginated |
| POST | `/api/v1/organizations/{id}/invitations/{iid}/revoke/` | Needs `members.manage`; 409 `already_decided` |
| GET | `/api/v1/organizations/permissions/` | The permission catalog: `{code, label}` for every permission a role can hold |
| GET | `/api/v1/organizations/{id}/roles/` | Roles with permissions and active `member_count`, not paginated (an organization has a handful); needs `roles.manage` or `members.manage` |
| POST | `/api/v1/organizations/{id}/roles/` | `{name, permissions}`; needs `roles.manage`. 403 `beyond_your_authority` for permissions the actor lacks; 400 on a duplicate name (case-insensitive) |
| PATCH | `/api/v1/organizations/{id}/roles/{rid}/` | Rename or change permissions; the actor must hold every permission the role has, before and after. Admin can only be renamed (409 `admin_role_locked`) |
| DELETE | `/api/v1/organizations/{id}/roles/{rid}/` | 204; Admin and Member can't be deleted (409 `role_required`) |
| GET | `/api/v1/organizations/{id}/members/?search=` | Active members (display name and roles, never email); needs `members.manage` or `roles.manage`; paginated |
| PUT | `/api/v1/organizations/{id}/members/{mid}/roles/` | `{roles: [ids]}` replaces the member's roles; needs `roles.manage`. Every role added or removed must be within the actor's authority; role IDs from another organization or the Member role are a 400; 409 `last_admin` |
| POST | `/api/v1/organizations/{id}/members/{mid}/remove/` | 204; needs `members.manage` and every permission the member holds; 409 `last_admin` |
| GET | `/api/v1/organizations/{id}/member-fields/` | Custom member fields, not paginated (at most 30 active). Holders of `members.manage` get every field, retired ones included; other members get only active member-visible fields; non-members 403 |
| POST | `/api/v1/organizations/{id}/member-fields/` | `{label, kind, options, required, visibility}`; needs `members.manage`. `kind` is text, number, date, boolean or choice; `options` (2 to 30) only for choice; `visibility` is member or staff (default). 400 on a duplicate active label; 409 `too_many_fields` |
| PATCH | `/api/v1/organizations/{id}/member-fields/{fid}/` | Change label, options, required or visibility. `kind` can't change (400); a retired field is 409 `field_retired` |
| POST | `/api/v1/organizations/{id}/member-fields/{fid}/retire/` or `restore/` | Retiring hides the field everywhere and keeps its values; restoring brings both back. 409 `label_taken` if an active field now uses the label |
| GET, PATCH | `/api/v1/organizations/{id}/members/{mid}/fields/` | A member's values for every active field, staff-only ones included; needs `members.manage`. Same body and rules as the player's own endpoint |
| GET | `/api/v1/players/?search=` | Opted-in players only; at least 2 characters. Shows name, nickname, photo link (`avatar`) and clubs, never email or bio |
| GET | `/api/v1/players/{id}/` | One opted-in player: the directory card plus only the details they published (others null); 404 once they opt out |
| GET | `/api/v1/attachments/{id}/url/` | A fresh signed link `{id, url, expires_at}` to a private file; 404 for a missing file and for one the caller may not see |
| GET | `/api/v1/attachments/{id}/content/?token=` | The file. Needs no session, only the token from a signed link; 403 `link_expired` when the token is expired, altered or for another file |
| GET | `/api/v1/organizations/{id}/venues/` | Venues with their tables, not paginated. Members get the venues and tables in use; holders of `facilities.manage` get them all; non-members 403 |
| POST | `/api/v1/organizations/{id}/venues/` | `{name, town, address}`; needs `facilities.manage`. 400 when a venue in use has the name; 409 `too_many_venues` (20 in use) |
| PATCH | `/api/v1/organizations/{id}/venues/{vid}/` | Change name, town, address or `active`. Venues are switched off, never deleted |
| POST | `/api/v1/organizations/{id}/venues/{vid}/tables/` | `{label}` adds a table at the end of the playing order; replies with the venue. 409 `too_many_tables` (60 in use) |
| PATCH | `/api/v1/organizations/{id}/venues/{vid}/tables/{tid}/` | Change `label` or `active`; replies with the venue |
| GET | `/api/v1/tournaments/?search=&organization=&when=` | Published tournaments (never drafts) with their events, for every signed-in player. `when=upcoming` soonest first, `when=past` latest first |
| GET | `/api/v1/tournaments/{id}/` | One tournament. A draft is 404 unless the caller holds `competitions.manage` in the host organization |
| GET, POST | `/api/v1/organizations/{id}/tournaments/` | Everything the organization hosts, drafts included, and creating a draft `{name, starts_on, ends_on, venue_id, timezone, description}`; needs `competitions.manage`. `timezone` defaults to the organization's |
| PATCH, DELETE | `/api/v1/tournaments/{id}/` | Staff of the host. 409 `tournament_closed` once completed or cancelled; the timezone is fixed once started (`structure_frozen`); only a draft can be deleted (`already_published`) |
| POST | `/api/v1/tournaments/{id}/publish/`, `start/`, `complete/` | draft → published → in progress → completed. 409 `invalid_transition`, `not_ready` (publishing needs a venue and an event) or `events_unfinished` |
| POST | `/api/v1/tournaments/{id}/cancel/` | `{reason}`, from published or in progress; terminal. Unfinished events are cancelled with it. The reason is public |
| GET | `/api/v1/tournaments/{id}/history/` | Staff only: who published, started, completed or cancelled what, with the configuration at that moment |
| POST | `/api/v1/tournaments/{id}/events/` | `{name, kind, format, capacity, best_of, rest_minutes, registration_opens_at, registration_closes_at, entry_fee: {amount_minor, currency}, seeding, group_count, qualifiers_per_group}`. Event calls reply with the whole tournament |
| PATCH, DELETE | `/api/v1/tournaments/{id}/events/{eid}/` | Each change adds one to `revision`. After the event starts, changing kind, format, best of, seeding, groups or qualifiers is 409 `structure_frozen`. Delete only in a draft |
| POST | `/api/v1/tournaments/{id}/events/{eid}/start/`, `complete/`, `cancel/` | scheduled → in progress → completed; start needs the tournament in progress (`tournament_not_started`); cancel takes `{reason}` and needs a published tournament (`not_published`: delete the event of a draft instead) |
| GET | `/api/v1/tournaments/{id}/events/{eid}/entries/` | Paginated. Accepted entries for every signed-in player, plus the caller's own in any status; competition staff get all. `?status=` filters. An entry carries players (id and name), team name, captain, status, check-in time and `mine`; nothing about payment |
| POST | `/api/v1/tournaments/{id}/events/{eid}/entries/` | `{player_ids?, team_name?, captain_id?}`. A player's own entry includes them (singles: just them; doubles: two different players; team: a name, 2–10 players and a captain from the roster), is made inside the registration window (`registration_not_open`, `registration_closed`) and starts `pending`. Staff enter anybody until the event starts: `accepted` if there is a place, else `waitlisted`. 409 `already_entered` for a player already in a standing entry of the event, `team_name_taken`, `not_published`, `entries_closed`. Other players in the entry get an email |
| POST | `/api/v1/tournaments/{id}/events/{eid}/entries/{entry}/accept/`, `waitlist/`, `reject/`, `staff-withdraw/` | Competition staff, before the event starts. `accept` works from pending or the waiting list and rechecks capacity every time (409 `event_full`); nobody is promoted automatically. `reject` and `staff-withdraw` take an optional `{reason}` shown to the entry's players. The players are emailed |
| POST | `/api/v1/tournaments/{id}/events/{eid}/entries/{entry}/check-in/`, `undo-check-in/` | Competition staff, accepted entries only (`not_accepted`), until the event ends. Independent of the entry fee |
| POST | `/api/v1/tournaments/{id}/events/{eid}/entries/{entry}/withdraw/` | One of the entry's own players, before the event starts; 404 for anybody else |
| GET | `/api/v1/me/entries/` | Paginated. Every entry the caller plays in, newest first, with its event and tournament |

Roles (REQ-005, `organizations/permissions.py`): every organization starts with Admin, Captain, Assistant captain,
Committee and Member, and can add custom roles. Effective permissions are the union of a member's roles plus the
Member role, which applies to every active member. Admin always holds every permission. Nobody grants, removes or
deletes a permission they don't hold. Role changes, removals and leaving lock the organization row, so concurrent
changes can't remove the last admin; deactivated accounts don't count as admins (`organizations/access.py`).

Custom member fields (REQ-005, `organizations/member_fields.py`): definitions belong to an organization, values to a
membership. A member-visible field is shown to, and filled in by, the member it describes and by staff; a staff-only
field and its values exist only for holders of `members.manage`. Other members never see anyone's values. Both
audiences read and write values through `visible_fields`, so there is one place that decides what a viewer gets. Values are
checked against the field type; a required field can't be saved blank. Fields are retired, never deleted, and values
stay in the database when a field is retired or a member leaves.

List endpoints share `core.pagination.StandardPagination` (`page`, `page_size` up to 100) and return `{count, next, previous, results}`.
