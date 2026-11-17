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

Emails (verification, password reset) print to the `runserver` console unless `SMTP_HOST` is set. Open the link from
there.

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
| GET | `/api/v1/players/?search=` | Opted-in players only; at least 2 characters. Shows name, nickname, photo link (`avatar`) and clubs, never email or bio |
| GET | `/api/v1/players/{id}/` | One opted-in player: the directory card plus only the details they published (others null); 404 once they opt out |
| GET | `/api/v1/attachments/{id}/url/` | A fresh signed link `{id, url, expires_at}` to a private file; 404 for a missing file and for one the caller may not see |
| GET | `/api/v1/attachments/{id}/content/?token=` | The file. Needs no session, only the token from a signed link; 403 `link_expired` when the token is expired, altered or for another file |

Roles (REQ-005, `organizations/permissions.py`): every organization starts with Admin, Captain, Assistant captain,
Committee and Member, and can add custom roles. Effective permissions are the union of a member's roles plus the
Member role, which applies to every active member. Admin always holds every permission. Nobody grants, removes or
deletes a permission they don't hold. Role changes, removals and leaving lock the organization row, so concurrent
changes can't remove the last admin; deactivated accounts don't count as admins (`organizations/access.py`).
List endpoints share `core.pagination.StandardPagination` (`page`, `page_size` up to 100) and return `{count, next, previous, results}`.
