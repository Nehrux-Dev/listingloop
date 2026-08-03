# Real Estate

Full-stack skeleton and local development environment.

| Layer          | Stack                                                |
| -------------- | ---------------------------------------------------- |
| Backend        | Python 3.12, Django 5.2, Django REST Framework       |
| Auth           | JWT (simplejwt), httpOnly refresh cookie, 3 roles    |
| Uploads        | Django storage API, local filesystem (swappable)     |
| Database       | PostgreSQL 16                                        |
| Background     | Celery 5.6 + Redis 7 (connection only, no tasks)     |
| Frontend       | React 19, TypeScript, Vite, Tailwind v4, React Router|
| Orchestration  | Docker Compose                                       |

Authentication, role-based access control, and agent/brokerage/brand-kit
profile management are in place. Listings, templates, AI content and compliance
are still empty scaffolds.

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
| `agent2@nehrux.test`  | Agent           |
| `broker@nehrux.test`  | Brokerage Admin |
| `admin@nehrux.test`   | Nehrux Admin    |

Password for all of them: `Passw0rd-Local-2026`. It also creates a brokerage
("Harbour & Co Realty") with both agents as members and `broker@` as its
administrator, so every screen has something to show.

Sign in at http://localhost:5173/login. The nav bar changes by role, and an
Agent who types `/platform` into the address bar lands on `/forbidden`.

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

---

## Profiles, brokerages and brand kits

### Models

| Model          | Notes |
| -------------- | ----- |
| `Brokerage`    | name, logo, required disclaimer, website, phone. `admins` (M2M to users) decides who may manage it. |
| `AgentProfile` | one per user, created automatically when an Agent registers. Name, photo, phone, public email, job title, tagline, and a FK to `Brokerage` (`brokerage.agents` in reverse). |
| `BrandKit`     | three colours, heading/body fonts, design style. Belongs to **exactly one** agent or brokerage, enforced by a database `CheckConstraint`. |

They live in [backend/apps/accounts/profiles.py](backend/apps/accounts/profiles.py)
and are re-exported from `apps.accounts.models`.

Two relationships are deliberately kept separate: `AgentProfile.brokerage` is
*membership*, `Brokerage.admins` is *administration*. A Brokerage Admin needs
no agent profile, and an agent is not an admin of their own brokerage.

### Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| CRUD | `/api/brokerages/` | create/delete: Nehrux Admin only |
| CRUD | `/api/agents/` | create/delete: Brokerage Admin and above |
| GET/PATCH | `/api/agents/me/` | the caller's own profile |
| CRUD | `/api/brand-kits/` | |
| GET | `/api/brand-kits/mine/` | the caller's own kit, created on first call |

### Who can do what

| | Agent | Brokerage Admin | Nehrux Admin |
| --- | --- | --- | --- |
| Own profile | edit | — | edit any |
| Colleagues' profiles | read | edit (own brokerage) | edit any |
| Own brokerage | read | edit | edit any |
| Create/delete a brokerage | no | no | yes |
| Own brand kit | edit | edit their agents' | edit any |
| Brokerage brand kit | read | edit | edit any |

Two things an agent explicitly cannot do, both covered by tests: reassign
themselves to another brokerage by PATCHing their own profile, and reach any
record belonging to a different brokerage.

The API distinguishes the two failure modes on purpose:

- **404** — the record is outside the caller's queryset. The API does not
  confirm it exists.
- **403** — the record is visible (a colleague, the brokerage they belong to)
  but the caller may not change it.

### Uploads and storage

Files go through Django's storage API only — no `open()`, no `os.path`, no
hardcoded directories. Swapping backends is a settings change:

```python
# now, in settings.py
STORAGES["default"] = {"BACKEND": "django.core.files.storage.FileSystemStorage"}

# later — pip install "django-storages[s3]", then:
STORAGES["default"] = {
    "BACKEND": "storages.backends.s3.S3Storage",
    "OPTIONS": {"bucket_name": ..., "endpoint_url": ...},
}
```

Nothing in the models, serializers, views or React app changes, because
`ImageField` and `.url` are backend-agnostic.
[backend/apps/core/storage.py](backend/apps/core/storage.py) explains the
design; the short version:

- `upload_to` callables return **keys**, not paths — forward-slash separated,
  valid as both a filesystem path and an S3 object key.
- Keys are random UUIDs under a namespace (`agents/photos/ab/abcd….png`). The
  client's filename never touches storage, so path traversal and filename
  collisions are structurally impossible, and replacing a photo produces a new
  URL rather than a stale cached one.
- Replaced and deleted files are cleaned up through `storage.delete()`.

Validation runs at the model layer, so it applies to the API, the Django admin
and any management command alike
([backend/apps/core/validators.py](backend/apps/core/validators.py)):

1. **Size** — `MAX_IMAGE_UPLOAD_MB`, default 5. Checked before the file is
   decoded, so an oversized upload is cheap to reject and reports the real
   reason.
2. **Extension** — allowlist: `.jpg`, `.jpeg`, `.png`, `.webp`. SVG is excluded
   because it can carry script.
3. **Content** — the bytes are decoded and the *real* format compared against
   the allowlist. Neither the filename nor the `Content-Type` header is
   evidence of anything; this is the check that stops a script renamed
   `photo.png`.

### React forms

| Route | Who | File |
| ----- | --- | ---- |
| `/profile` | agents | [ProfilePage.tsx](frontend/src/pages/ProfilePage.tsx) — details + photo upload |
| `/brand-kit` | agents | [BrandKitPage.tsx](frontend/src/pages/BrandKitPage.tsx) — colours, fonts, style |
| `/brokerage` | Brokerage Admin and above | [BrokeragePage.tsx](frontend/src/pages/BrokeragePage.tsx) — details, logo, disclaimer, agent list |

The agent forms address `/me/` and `/mine/`, which resolve the record from the
access token — there is no id in the URL or payload, so they structurally
cannot be pointed at someone else. Client-side file checks in
[FormControls.tsx](frontend/src/components/FormControls.tsx) are a courtesy for
fast feedback; the server validates independently.

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
│       ├── core/            # cross-cutting infrastructure
│       │   ├── storage.py       # upload keys, storage-backend indirection
│       │   ├── validators.py    # image size / extension / content checks
│       │   ├── fields.py        # ValidatedImageField (size before decode)
│       │   ├── models.py        # TimeStampedModel
│       │   └── management/      # seed_dev_users
│       ├── accounts/        # identity, auth, and profile domain
│       │   ├── models.py        # User + Role + ROLE_LEVELS
│       │   ├── profiles.py      # Brokerage, AgentProfile, BrandKit
│       │   ├── cookies.py       # httpOnly refresh-cookie handling (read this)
│       │   ├── permissions.py   # role + object-level permission classes
│       │   ├── serializers.py / profile_serializers.py
│       │   ├── views.py         # register / login / refresh / logout / me
│       │   ├── profile_views.py # brokerage / agent / brand-kit viewsets
│       │   ├── signals.py       # profile provisioning, stored-file cleanup
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
        ├── api/profiles.ts  # profile/brokerage/brand-kit calls and types
        ├── auth/            # provider, guards, token store, API calls
        ├── components/      # AppLayout, shared form controls
        ├── lib/apiClient.ts # fetch wrapper: refresh-and-retry, multipart
        └── pages/           # Login, Dashboard, Profile, BrandKit,
                             #   Brokerage, Platform, Forbidden
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

115 tests. The suite runs against a throwaway database, uses an in-memory
cache instead of Redis, a fast password hasher and a temporary `MEDIA_ROOT`,
so it needs nothing beyond a running Postgres.

- `test_auth.py` — login (success and failure), refresh and rotation replay,
  logout revocation, registration rules, the httpOnly cookie contract.
- `test_permissions.py` — access denied for the wrong role (403) and for no
  token (401), role hierarchy, immediate effect of a role change.
- `test_profiles.py` — CRUD for all three models, and the boundaries: an agent
  cannot edit a colleague, reach another brokerage, move themselves between
  brokerages, or delete their own profile.
- `test_uploads.py` — valid uploads, non-image content, disallowed extensions,
  oversized files, extension/content mismatch, storage-key shape, and cleanup
  of replaced files.

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
- Serve `MEDIA_ROOT` from nginx (or move `STORAGES["default"]` to an object
  store); Django's `static()` helper is DEBUG-only and does nothing in
  production. Whichever you choose, make sure the media location cannot
  execute anything it serves.
- Prune the blacklist periodically:
  `manage.py flushexpiredtokens` (from simplejwt).

## Next steps

Deliberately not included yet: domain models for listings/templates/AI
content/compliance, Celery tasks, CI, and production settings.
