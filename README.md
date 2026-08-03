# Real Estate

Full-stack skeleton and local development environment.

| Layer          | Stack                                            |
| -------------- | ------------------------------------------------ |
| Backend        | Python 3.12, Django 5.2, Django REST Framework   |
| Database       | PostgreSQL 16                                    |
| Background     | Celery 5.6 + Redis 7 (connection only, no tasks) |
| Frontend       | React 19, TypeScript, Vite, Tailwind CSS v4      |
| Orchestration  | Docker Compose                                   |

There is no authentication, no domain model and no business logic yet — this is
the skeleton only.

---

## Quick start

Requires Docker Desktop (or Docker Engine + Compose v2).

```bash
cp .env.example .env      # Windows PowerShell: Copy-Item .env.example .env
docker compose up --build
```

That single command starts Postgres, Redis, the Django API, a Celery worker and
the Vite dev server, and applies migrations automatically.

| Service        | URL                                  |
| -------------- | ------------------------------------ |
| Frontend       | http://localhost:5173                |
| API            | http://localhost:8000/api/           |
| Health check   | http://localhost:8000/api/health/    |
| Django admin   | http://localhost:8000/admin/         |
| Postgres       | localhost:5432                       |
| Redis          | localhost:6379                       |

Stop with `Ctrl+C`, or `docker compose down`. Add `-v` to also drop the
Postgres and Redis volumes.

### Health check

`GET /api/health/` verifies that Django can actually reach both backing
services — it runs `SELECT 1` against Postgres and `PING` against Redis.
It returns `200` when everything is reachable and `503` otherwise:

```json
{
  "status": "ok",
  "checks": {
    "database": { "status": "ok" },
    "redis": { "status": "ok" }
  }
}
```

The frontend home page calls this endpoint, so a green dashboard at
http://localhost:5173 means the whole stack is wired up.

---

## Configuration

All configuration comes from environment variables. `.env` is git-ignored;
`.env.example` is the checked-in reference for every variable the stack reads.
Copy it and edit as needed — the defaults work out of the box for local dev.

Notes:

- Compose overrides the host-facing values (`POSTGRES_HOST`, `REDIS_URL`, …)
  with the internal service names, so the same `.env` works whether you run
  through Docker or directly on your machine.
- `DATABASE_URL`, when set, takes precedence over the discrete `POSTGRES_*`
  variables.
- Only `VITE_`-prefixed variables reach the frontend bundle. Never put secrets
  behind that prefix — they are shipped to the browser.
- Ports are configurable (`BACKEND_HOST_PORT`, `FRONTEND_HOST_PORT`,
  `POSTGRES_HOST_PORT`, `REDIS_HOST_PORT`) if something already occupies them.
- Generate a real `DJANGO_SECRET_KEY` for anything beyond local dev:
  `python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"`

---

## Project layout

```
.
├── docker-compose.yml       # Postgres, Redis, Django, Celery worker, Vite
├── .env.example             # every variable the stack reads
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── manage.py
│   ├── config/              # project package
│   │   ├── settings.py      # single env-driven settings module
│   │   ├── urls.py          # root URLconf
│   │   ├── celery.py        # Celery app (broker/backend on Redis)
│   │   ├── wsgi.py
│   │   └── asgi.py
│   └── apps/                # one Django app per domain
│       ├── core/            # health check, cross-cutting infrastructure
│       ├── accounts/        # users, organisations, agent profiles
│       ├── listings/        # property listings
│       ├── templates/       # reusable content templates
│       ├── ai_content/      # AI-generated copy
│       └── compliance/      # regulatory rules and audit trails
└── frontend/
    ├── Dockerfile
    ├── vite.config.ts       # React + Tailwind plugins, /api dev proxy
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx          # health dashboard
        ├── index.css        # @import "tailwindcss"
        └── api/health.ts
```

Every domain app is an empty scaffold (`apps.py`, `models.py`, `admin.py`,
`migrations/`) registered in `INSTALLED_APPS`. Wire a new app's routes up by
uncommenting its line in [backend/config/urls.py](backend/config/urls.py).

---

## Common commands

All of these run against the live stack:

```bash
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser
docker compose exec backend python manage.py shell

docker compose logs -f backend
docker compose logs -f celery_worker
docker compose restart backend

docker compose exec frontend npm install <package>
docker compose exec frontend npm run typecheck
```

Rebuild after changing `requirements.txt` or `package.json`:

```bash
docker compose up --build
```

Both source trees are bind-mounted, so Django's autoreloader and Vite's HMR
pick up code changes without a rebuild.

### Celery

The worker starts with no registered tasks — that is expected. When tasks are
added, put them in `apps/<domain>/tasks.py`; `autodiscover_tasks()` in
[backend/config/celery.py](backend/config/celery.py) finds them, and
`@shared_task` works because `config/__init__.py` imports the Celery app.

---

## Running without Docker

Postgres and Redis still need to be running somewhere; point `.env` at them
(`POSTGRES_HOST=localhost`, `REDIS_URL=redis://localhost:6379/0`,
`VITE_API_PROXY_TARGET=http://localhost:8000`).

```bash
# backend
cd backend
python -m venv .venv && .venv\Scripts\activate   # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver

# frontend (second terminal)
cd frontend
npm install
npm run dev

# celery worker (third terminal)
cd backend
celery -A config worker --loglevel=info
```

---

## Next steps

Deliberately not included yet: authentication, domain models, serializers,
business logic, tests, CI and production settings.
