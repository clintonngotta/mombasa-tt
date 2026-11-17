# Coast TT

Table-tennis club and tournament PWA: a React/Vite web app (`apps/web`) and a Django/DRF API (`services/api`).
Product docs: `spec.md`, `tasks.md`, `test.md`, `intent.md`, `deployment.md`.

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

Test logins (also shown as one-tap buttons on the login page):

| Email | Password |
|---|---|
| `player@mombasa-tt.test` | `mombasa-tt-dev` |
| `umpire@mombasa-tt.test` | `mombasa-tt-dev` |
| `admin@mombasa-tt.test` | `mombasa-tt-dev` |

Useful commands:

```sh
docker compose up --build -d          # in the background
docker compose exec api python manage.py createsuperuser   # Django admin at http://localhost:8020/admin/
docker compose exec api pytest       # API tests against the compose database
docker compose up --build -V          # after web dependencies change (fresh node_modules volume)
docker compose down                   # stop; add -v to also delete the database volume
```

Ports bind to `127.0.0.1` only. If 8080 or 8020 is taken, pick others: `WEB_PORT=3000 API_PORT=8030 docker compose up`.
This setup is for local development only (debug on, dev-only password, seeded logins); production is planned in
`deployment.md` (TASK-058).

To run the API and web app directly on your machine instead, see `services/api/README.md` (database only:
`docker compose -f infra/compose.dev.yml up -d`).
