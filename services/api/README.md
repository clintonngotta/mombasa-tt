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

Override the password with `DEV_LOGIN_PASSWORD`. The command refuses to run when `DJANGO_DEBUG` is off. Club roles
arrive with organizations (TASK-012/013); until then these are plain verified users.

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
| GET, PATCH | `profile/` | Display name (stored on the user), nickname, hand, grip, style, experience, bio, `directory_opt_in` (off by default) |
| PUT | `goals/` | `{goals: [...]}` replaces the list. Goals only order Home shortcuts and never grant roles |
| POST | `onboarding/complete/` | 204. Repeat calls keep the first completion time |
| GET | `memberships/` | Active memberships with their organization (basis for the club switcher); paginated |
| GET | `join-requests/` | The player's own join requests, newest first; paginated |
| GET | `invitations/` | Open invitations addressed to the player's verified email; paginated |
| POST | `invitations/{iid}/accept/` or `decline/` | Accepting joins as a member (an existing admin keeps their role) and withdraws the player's open join request to that organization; 404 for anyone else's, answered, revoked or expired invitation |

## Organizations and directory

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/organizations/?search=` | Matches name or town; paginated |
| POST | `/api/v1/organizations/` | `{name, town, kind}`; the creator becomes the first admin |
| GET | `/api/v1/organizations/{id}/` | |
| POST | `/api/v1/organizations/{id}/join-requests/` | 201 new, 200 if one is already pending, 409 `already_member` |
| GET | `/api/v1/organizations/{id}/join-requests/` | Pending requests, paginated; organization admins only (403 `not_organization_admin`) |
| POST | `/api/v1/organizations/{id}/join-requests/{rid}/approve/` or `reject/` | Admins only; 409 `already_decided` |
| POST | `/api/v1/organizations/{id}/invitations/` | `{email}`, admins only. 201 new, 200 if already pending (renews a lapsed one and resends). Same reply and email whether or not the address has an account or belongs to a member. Expires after 14 days; throttled per admin (`THROTTLE_INVITATIONS`, default 30/hour) |
| GET | `/api/v1/organizations/{id}/invitations/` | Open (pending, unexpired) invitations, admins only; paginated |
| POST | `/api/v1/organizations/{id}/invitations/{iid}/revoke/` | Admins only; 409 `already_decided` |
| GET | `/api/v1/players/?search=` | Opted-in players only; at least 2 characters. Shows name, nickname and clubs, never email or bio |

The admin/member role pair is a stand-in until the permission catalog and role templates arrive (TASK-013).
Invitations, leaving an organization and the last-admin rule also come later.
List endpoints share `core.pagination.StandardPagination` (`page`, `page_size` up to 100) and return `{count, next, previous, results}`.
