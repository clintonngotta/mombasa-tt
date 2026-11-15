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
