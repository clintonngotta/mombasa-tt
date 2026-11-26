# Coast TT

Table-tennis club and tournament PWA: a React/Vite web app (`apps/web`) and a Django/DRF API (`services/api`).
Product docs: `spec.md`, `tasks.md`, `test.md`, `intent.md`, `deployment.md`.

Open events accept eligible registrations automatically while space remains. Closed events require organizer approval. See [the registration rules](spec.md#req-008).

## Run everything with Docker

```sh
docker compose up --build
```

Then open <http://localhost:8080>. The first start builds the images, runs migrations and seeds the test logins.

| What | Where |
|---|---|
| Web app (Vite, live reload) | <http://localhost:8080> |
| API (Django runserver, live reload) | <http://localhost:8020/api/v1/> (the web app proxies `/api`) |
| OpenAPI schema | <http://localhost:8020/api/v1/schema/> |
| Emails (verification, password reset links) | `docker compose logs -f api` |

Test logins (type them in: the login page no longer lists them):

| Email | Password |
|---|---|
| `player@mombasa-tt.test` | `mombasa-tt-dev` |
| `umpire@mombasa-tt.test` | `mombasa-tt-dev` |
| `admin@mombasa-tt.test` | `mombasa-tt-dev` |

For a super admin (everything, and Django admin at <http://localhost:8020/admin/>), put these in a `.env` file beside `compose.yml` (git-ignored) and restart the API. The account is made at start, the same way as in production; the password needs 10 characters or more and is only used to create the account:

```sh
OWNER_EMAIL=you@example.com
OWNER_PASSWORD=a-long-local-passphrase
```

Useful commands:

```sh
docker compose up --build -d          # in the background
docker compose exec api pytest       # API tests against the compose database
(cd apps/web && pnpm test:e2e)        # browser tests (Playwright) against the running stack: apps/web/e2e/README.md
docker compose up --build -V          # after web dependencies change (fresh node_modules volume)
docker compose down                   # stop; add -v to also delete the database volume
```

Ports bind to `127.0.0.1` only. If 8080 or 8020 is taken, pick others: `WEB_PORT=3000 API_PORT=8030 docker compose up`.
This setup is for local development only (debug on, dev-only password, seeded logins).

### Production images

`infra/compose.production.yml` runs the production images: Caddy (HTTPS, the PWA build, Django's static files,
proxying `/api/` with WebSockets, `/admin/` and `/health/`), the API under Daphne, the Celery worker and beat,
PostgreSQL and Redis. Only Caddy publishes ports. Copy `infra/production.env.example` to `.env.production`, fill
it in, then:

```bash
docker compose --env-file .env.production -f infra/compose.production.yml build
docker compose --env-file .env.production -f infra/compose.production.yml run --rm api python manage.py migrate --noinput
docker compose --env-file .env.production -f infra/compose.production.yml up -d --wait
```

To try it on your machine set `APP_DOMAIN=localhost`, `HTTP_PORT=8081`, `HTTPS_PORT=8443` and
`DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:8443`, and give it its own `COMPOSE_PROJECT_NAME`; Caddy serves
`https://localhost:8443` with its local certificate. The release and rollback procedure is in `deployment.md`.

To run the API and web app directly on your machine instead, see `services/api/README.md` (database only:
`docker compose -f infra/compose.dev.yml up -d`).
