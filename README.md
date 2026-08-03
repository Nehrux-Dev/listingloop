# Real Estate

Full-stack skeleton and local development environment.

| Layer          | Stack                                                |
| -------------- | ---------------------------------------------------- |
| Backend        | Python 3.12, Django 5.2, Django REST Framework       |
| Auth           | JWT (simplejwt), httpOnly refresh cookie, 3 roles    |
| Database       | PostgreSQL 16                                        |
| Background     | Celery 5.6 + Redis 7 (connection only, no tasks)     |
| Frontend       | React 19, TypeScript, Vite, Tailwind v4, React Router|
| Orchestration  | Docker Compose                                       |

Authentication and role-based access control are in place. There is no domain
model or business logic yet.

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

The frontend dashboard calls this endpoint, so green dots after signing in
mean the whole stack is wired up.

### Log in

Seed one account per role (refuses to run unless `DEBUG=True`):

```bash
docker compose exec backend python manage.py seed_dev_users
```

| Email                 | Role            |
| --------------------- | --------------- |
| `agent@nehrux.test`   | Agent           |
| `broker@nehrux.test`  | Brokerage Admin |
| `admin@nehrux.test`   | Nehrux Admin    |

Password for all three: `Passw0rd-Local-2026`. Sign in at
http://localhost:5173/login. The nav bar changes by role, and an Agent who
types `/platform` into the address bar lands on `/forbidden`.

---

## Authentication

### Roles

Three roles, ordered by privilege — see `ROLE_LEVELS` in
[backend/apps/accounts/models.py](backend/apps/accounts/models.py):

| Role              | Value              | Level |
| ----------------- | ------------------ | ----- |
| Agent             | `agent`            | 10    |
| Brokerage Admin   | `brokerage_admin`  | 20    |
| Nehrux Admin      | `nehrux_admin`     | 30    |

Registration can only ever create an Agent (`SELF_ASSIGNABLE_ROLES`); elevated
roles are granted by an admin through the Django admin.

### Endpoints

| Method | Path                              | Access                     |
| ------ | --------------------------------- | -------------------------- |
| POST   | `/api/auth/register/`             | public                     |
| POST   | `/api/auth/login/`                | public                     |
| POST   | `/api/auth/refresh/`              | refresh cookie             |
| POST   | `/api/auth/logout/`               | refresh cookie             |
| GET    | `/api/auth/me/`                   | any authenticated user     |
| GET    | `/api/admin/brokerage-overview/`  | Brokerage Admin **and above** |
| GET    | `/api/admin/platform-overview/`   | Nehrux Admin **only**      |

The last two are example endpoints demonstrating the two permission styles.
DRF defaults to `IsAuthenticated`, so anything new is private until it opts
out explicitly.

### Token storage — the important part

Full reasoning lives in
[backend/apps/accounts/cookies.py](backend/apps/accounts/cookies.py); the
short version:

- **Access token** (5 min): returned in the JSON body, held **in a JavaScript
  variable** in the browser ([frontend/src/auth/tokenStore.ts](frontend/src/auth/tokenStore.ts)).
  Never in `localStorage` or `sessionStorage` — anything there is readable by
  any script on the origin, so one XSS bug hands the attacker a token they can
  reuse from their own machine.
- **Refresh token** (7 days): only ever sent as a cookie with `HttpOnly`,
  `Secure` (outside DEBUG), `SameSite=Lax` and `Path=/api/auth/`. It never
  appears in a response body and JavaScript cannot read it. `SameSite=Lax` is
  the CSRF defence for the refresh endpoint; the path scoping keeps the
  browser from attaching a long-lived credential to every API call.
- Refresh tokens **rotate** on every use and the presented one is
  **blacklisted**, so a captured refresh token works at most once.
- A page reload loses the in-memory access token by design. The auth provider
  calls `/api/auth/refresh/` once on boot and the session is restored
  silently — or the user is sent to `/login`.

Because the access token lives in memory, logout is server-side too: the
refresh token is blacklisted and the cookie expired. The access token stays
cryptographically valid until it expires, which is why its lifetime is
minutes.

### Frontend pieces

| File | Role |
| ---- | ---- |
| [src/auth/AuthContext.tsx](frontend/src/auth/AuthContext.tsx) | provider, `useAuth()`, session restore on boot |
| [src/auth/ProtectedRoute.tsx](frontend/src/auth/ProtectedRoute.tsx) | `<ProtectedRoute>`, `<RequireRole>`, `<RoleGate>` |
| [src/auth/tokenStore.ts](frontend/src/auth/tokenStore.ts) | in-memory access token |
| [src/lib/apiClient.ts](frontend/src/lib/apiClient.ts) | fetch wrapper: bearer header, refresh-and-retry on 401 |
| [src/pages/LoginPage.tsx](frontend/src/pages/LoginPage.tsx) | login form |

Route guards decide what to *render*. They are not a security boundary — the
server re-checks the role on every request.

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
│       ├── core/            # health check, seed_dev_users command
│       ├── accounts/        # user model, roles, JWT auth, permissions
│       │   ├── models.py        # User + Role + ROLE_LEVELS
│       │   ├── cookies.py       # httpOnly refresh-cookie handling (read this)
│       │   ├── permissions.py   # role-based DRF permission classes
│       │   ├── serializers.py
│       │   ├── views.py         # register / login / refresh / logout / me
│       │   └── tests/
│       ├── listings/        # property listings          (empty scaffold)
│       ├── templates/       # reusable content templates (empty scaffold)
│       ├── ai_content/      # AI-generated copy          (empty scaffold)
│       └── compliance/      # regulatory rules           (empty scaffold)
└── frontend/
    ├── Dockerfile
    ├── vite.config.ts       # React + Tailwind plugins, /api dev proxy
    ├── tsconfig.json
    └── src/
        ├── main.tsx
        ├── App.tsx          # router + guarded routes
        ├── index.css        # @import "tailwindcss"
        ├── auth/            # provider, guards, token store, API calls
        ├── components/      # AppLayout (role-aware nav)
        ├── lib/apiClient.ts # fetch wrapper with refresh-and-retry
        └── pages/           # Login, Dashboard, Brokerage, Platform, Forbidden
```

The remaining domain apps are empty scaffolds (`apps.py`, `models.py`,
`admin.py`, `migrations/`) registered in `INSTALLED_APPS`. Wire a new app's
routes up by uncommenting its line in
[backend/config/urls.py](backend/config/urls.py).

---

## Common commands

All of these run against the live stack:

```bash
docker compose exec backend python manage.py test            # full suite
docker compose exec backend python manage.py test apps.accounts
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py createsuperuser # becomes a Nehrux Admin
docker compose exec backend python manage.py seed_dev_users  # one user per role
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

### Tests

```bash
docker compose exec backend python manage.py test
```

The suite runs against a throwaway database, uses an in-memory cache instead
of Redis and a fast password hasher, so it needs nothing beyond a running
Postgres. It covers successful and failed login, token refresh and rotation,
logout revocation, registration, and access denied both for the wrong role
(403) and for no token at all (401).

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

## Before deploying

The defaults are tuned for local development. For anything public:

- Set a real `DJANGO_SECRET_KEY` (32+ bytes — it also signs the JWTs) and
  `DJANGO_DEBUG=False`.
- `AUTH_COOKIE_SECURE=True` — it already defaults to `not DEBUG`, so this
  happens automatically unless someone overrides it. Serve over HTTPS.
- Keep `AUTH_COOKIE_SAMESITE=Lax`. If the SPA and API end up on genuinely
  different sites you are forced to `None`, which requires `Secure=True` and
  reintroduces CSRF exposure on `/api/auth/refresh/` — add a double-submit
  CSRF token before doing that.
- Swap `runserver` for gunicorn (already in `requirements.txt`) and build the
  frontend to static files instead of running the Vite dev server.
- Prune the blacklist periodically:
  `manage.py flushexpiredtokens` (from simplejwt).

## Next steps

Deliberately not included yet: domain models for listings/templates/AI
content/compliance, Celery tasks, CI, and production settings.
