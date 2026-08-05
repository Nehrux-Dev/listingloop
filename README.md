# Real Estate

Full-stack skeleton and local development environment.

| Layer          | Stack                                                |
| -------------- | ---------------------------------------------------- |
| Backend        | Python 3.12, Django 5.2, Django REST Framework       |
| Auth           | JWT (simplejwt), httpOnly refresh cookie, 3 roles    |
| Uploads        | Django storage API, local filesystem (swappable)     |
| Rendering      | Playwright/Chromium in its own container, warm browser |
| AI content     | OpenAI, one call → six validated variants, via Celery |
| Compliance     | Data-driven rules, editable in the Django admin      |
| Database       | PostgreSQL 16                                        |
| Background     | Celery 5.6 + Redis 7 (connection only, no tasks)     |
| Frontend       | React 19, TypeScript, Vite, Tailwind v4, React Router|
| Orchestration  | Docker Compose                                       |

All five domains are in place: accounts, listings (manual entry, URL import,
verification), templates/designs (controlled editing, multi-dimension export),
AI content (validated, async, six variants per call) and a data-driven
compliance rules engine.

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
docker compose exec backend python manage.py seed_templates
docker compose exec backend python manage.py seed_compliance_rules   # PLACEHOLDERS
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

---

## Listings

### Models

| Model | Notes |
| ----- | ----- |
| `Listing` | address + structured location, price, bedrooms, bathrooms, square footage, property type, features (JSON list), status, verification status, provenance. Owned by one `AgentProfile`. |
| `ListingPhoto` | image, caption, `order`, and `source_url` when imported. |

Every attribute is nullable on purpose: an import that cannot establish a value
has to be able to leave it blank rather than write a plausible guess.

### Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| CRUD | `/api/listings/` | filter with `?verification_status=` / `?status=` |
| GET | `/api/listings/summary/` | counts for the caller's scope |
| POST | `/api/listings/{id}/verify/` | requires `{"confirmed": true}` |
| POST | `/api/listings/{id}/unverify/` | withdraw verification |
| POST | `/api/listings/import-url/` | one-off fetch of a public listing page |
| CRUD | `/api/listing-photos/` | multipart upload, `?listing=` filter |

### Scoping

Listings are **per agent**, not per brokerage: an agent sees only their own,
even from a colleague at the same brokerage whose *profile* they can see. A
Brokerage Admin sees every listing under the brokerages they administer; a
Nehrux Admin sees all of them. The rule lives in `Listing.objects.for_user`
rather than in the viewset, so every future caller — a Celery task, a
management command — inherits it instead of reimplementing it.

### Verification

This is the gate that protects everything downstream. Two rules, both on the
model so they hold for the admin and the shell as well as the API:

1. A listing starts **unverified** and becomes verified *only* through
   `POST /api/listings/{id}/verify/` with `{"confirmed": true}`.
   `verification_status` is read-only on the serializer, so it cannot be set in
   an ordinary PATCH, and the endpoint refuses while any of `address`, `city`,
   `price` or `property_type` is blank.
2. **Editing the data undoes it.** Change the price, address, bed count or
   features and the listing drops back to unverified. Without this, an agent
   could verify a listing and then quietly change the price while everything
   downstream still treated it as reviewed. Changing only the *sales* status
   (draft → active → sold) does not reset it, because that does not change what
   the listing claims.

Later features must fetch listings through
[`get_listing_for_content`](backend/apps/listings/services.py), which applies
scoping and the verified check together, rather than calling
`Listing.objects.get()` directly.

### URL import

`POST /api/listings/import-url/` fetches one page, once, when an agent asks.
Nothing is scheduled and nothing is re-fetched.

**Making the server fetch a user-supplied URL is SSRF by construction**, so
[fetching.py](backend/apps/listings/fetching.py) is deliberately restrictive:
http/https only; the hostname is resolved and *every* address it maps to must
be publicly routable (loopback, private, link-local — including the
`169.254.169.254` cloud-metadata address — reserved and multicast are all
refused); redirects are followed one hop at a time and re-validated; the
response is size- and time-limited; content types are allowlisted; and no
cookies, auth or proxy configuration are inherited. The endpoint is throttled.
The module documents the one residual gap honestly — DNS rebinding — and says
where the real fix belongs (egress control at the network edge).

Extraction ([extraction.py](backend/apps/listings/extraction.py)) works in
three tiers and **never guesses**:

1. **JSON-LD** (schema.org) — the site stating what its numbers mean. Trusted.
2. **Open Graph / meta** — images and description.
3. **Labelled text** — bedrooms, bathrooms and floor area only, and only where
   a number sits against an unambiguous label. If the page yields *conflicting*
   values, the field is left blank with a warning. Picking one would be a coin
   flip.

Price is never read from page text at all — a listing page is full of numbers
that look like prices (price history, comparables, mortgage estimates).

The result is always a DRAFT, UNVERIFIED listing plus `imported_fields` (what
was actually populated) and `import_warnings` (what could not be read, in plain
language). If the page cannot be fetched at all the API returns 502 and creates
nothing. Remote photos are downloaded through the same guarded fetcher and the
same image validation as a browser upload; one bad image is skipped with a
warning rather than losing the import.

### React

| Route | File |
| ----- | ---- |
| `/listings` | [ListingsPage.tsx](frontend/src/pages/ListingsPage.tsx) — list, filter by verification |
| `/listings/new`, `/listings/:id` | [ListingFormPage.tsx](frontend/src/pages/ListingFormPage.tsx) — all fields, features editor, multi-photo upload, verification panel |
| `/listings/import` | [ListingImportPage.tsx](frontend/src/pages/ListingImportPage.tsx) — paste a URL, see exactly what was and was not extracted |

Blank numeric inputs are sent as `null`, never `0` — a blank field means "not
known".

---

## Templates and designs

Built on **Approach A** from the [Step 4 prototype](prototypes/render-comparison/):
Playwright/Chromium, running in its own `renderer` container with a warm
browser.

### Models

| Model | Notes |
| ----- | ----- |
| `Template` | name, category (10), style (6), canvas-level `layout_definition`, and a `permission_map` derived from its elements. |
| `TemplateElement` | `key`, element type, **permission**, fractional `geometry`, `style_properties`, `content_source`, and `constraints`. |
| `Design` | a saved instance: template + agent + (verified) listing + `overrides`. |
| `DesignExport` | one rendered image at one dimension and format. |

### The permission model

Four levels, declared per element:

| Permission | May change |
| ---------- | ---------- |
| `locked` | nothing — brokerage logos, compliance disclaimers |
| `content_only` | text / image swap; geometry and styling fixed |
| `styled` | content, plus colour and size within an explicit allowlist |
| `free` | content, styling, and move/resize within declared `bounds` |

**Enforced server-side on every write**, in
[overrides.py](backend/apps/templates/overrides.py). The editor greys out
controls it should, but that is styling — the API assumes the client is hostile
and re-derives the rules from the template each time: unknown element keys are
rejected rather than stored, each field is checked against what the permission
allows, and each value against the element's constraints (colour allowlists,
font-size bounds, movement bounds, text length). One bad element rejects the
whole payload, so the client's model never silently diverges from the server's.

Two subtler rules worth knowing: an *empty* override on a locked element is
still rejected (a client that thinks it can edit should be told it cannot), and
image overrides name a **storage key, never a URL** — accepting a URL would let
a design make the renderer fetch it.

The API publishes `permission_map` and per-element `editable_fields` so the UI
builds the right controls from the server's rules rather than its own copy.

### Rendering pipeline

```
Listing + Template + BrandKit  →  Django composes HTML  →  renderer  →  PNG/JPG
     (render_context.py)          (html_builder.py)     (Playwright)   (storage)
```

Django owns the HTML; the renderer is a dumb "HTML in, image out" service. That
split means template logic is testable in Python without a browser, and the
renderer can be scaled or replaced independently.

The renderer container is **not published to the host** — it renders arbitrary
HTML, so only the backend reaches it over the compose network, with a shared
token. Its browser contexts run with **JavaScript disabled and all network
requests blocked**; every image arrives inlined as a data URI, resolved through
the storage API by Django. It keeps a small bounded pool of pages, because
Chromium's memory grows with live pages.

### One template, four dimensions

Element geometry is **fractional** (0..1 of the canvas), so Instagram Post,
Story, Facebook and LinkedIn come from one layout rather than four:

| Dimension | Size | Notes |
| --------- | ---- | ----- |
| Instagram Post | 1080×1080 | |
| Instagram Story | 1080×1920 | content inset from top/bottom for platform chrome |
| Facebook | 1200×630 | |
| LinkedIn | 1200×627 | |

Type scales with the **smaller side** of the canvas, not the height. Scaling
with height looked right at 1:1 and broke at 9:16 — a Story is 1.8× taller but
no wider, so height-scaled type grew while the text box did not and long
headings wrapped into the element below.

Exports are saved through the same storage abstraction as every upload
(`designs/exports/...`), so generated images follow user uploads to object
storage — there is no separate output path to migrate.

### Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| GET | `/api/templates/` | `?category=` `?style=` `?search=` |
| GET | `/api/templates/facets/` | filter options with counts |
| CRUD | `/api/designs/` | scoped like listings |
| GET | `/api/designs/{id}/resolved/` | every element resolved, with its permission |
| POST | `/api/designs/{id}/rename/` `duplicate/` | |
| POST | `/api/designs/{id}/preview/` | renders inline, saves nothing |
| POST | `/api/designs/{id}/export/` | one or more dimensions, PNG or JPG |
| GET | `/api/render-dimensions/` | the supported sizes |

Templates are **read-only over the API** — they are product content, authored
in the Django admin (`manage.py seed_templates` creates a starting library).
Designs may only be built on **verified** listings, honouring the Step 4 gate.

### React

| Route | File |
| ----- | ---- |
| `/templates` | [TemplateLibraryPage.tsx](frontend/src/pages/TemplateLibraryPage.tsx) — browse, filter by category and style |
| `/designs` | [DesignsPage.tsx](frontend/src/pages/DesignsPage.tsx) — save/reopen/rename/duplicate/delete |
| `/designs/:id` | [DesignEditorPage.tsx](frontend/src/pages/DesignEditorPage.tsx) — controlled editing, preview, export |

Controls come from [ElementControls.tsx](frontend/src/components/ElementControls.tsx),
which renders from the API's `editable_fields`: locked elements show their value
with no affordance, colour allowlists render as swatches rather than a picker
(offering values the server will reject is worse than not offering them), and
`free` elements get sliders clamped to their bounds.

---

## AI content generation

Set `OPENAI_API_KEY` in `.env` and restart the backend **and the worker**.
Without it the API fails cleanly rather than silently.

### Six formats, one API call

Each generation produces a full content pack:

| Variant | Shape |
| ------- | ----- |
| Instagram caption | 2–3 short sentences, punchy |
| Facebook caption | 3–5 sentences, conversational |
| LinkedIn caption | 2–4 sentences, professional and factual |
| Sharing message | one or two lines, as if texting it to someone |
| Property page description | 4–8 sentences, the longest format |
| Hashtags | 4–10, one shared set |

**One request, not six.** The facts block is most of the prompt, so six calls
would cost roughly six times as much and let the variants drift — each
independently picking a different fact to lead with. The response is a single
strict-schema JSON object; cost is recorded once for the whole pack.

The system prompt states that every rule applies to *every* field, and that
longer formats are longer because they use more of the given facts, never
because they add new ones — the property description is the longest variant and
therefore has the most room to invent.

### The key never reaches the browser

It is read from the environment by the backend, used in
[client.py](backend/apps/ai_content/client.py), and appears in no serializer, no
response body and no error message. The frontend calls *our* API; our API calls
OpenAI. Configuration failures return "not configured on this server" and put
the detail in the log — naming internal environment variables in a response is
a habit that eventually leaks something that matters.

### Only verified fields, and only those

[prompts.py](backend/apps/ai_content/prompts.py) builds a numbered, id-tagged
list of verified fields and tells the model that list is the entire universe of
things it may assert. Note what is *not* sent: internal notes, the source URL,
import warnings, other listings — and deliberately not the **street address**,
because a caption naming an occupied home's exact address is a privacy problem.
An optional agent tone note is fenced and explicitly demoted below the rules, so
it cannot talk the model out of them.

Output is requested as **structured JSON** against a strict schema, so it is
parsed rather than scraped.

### Nothing the model returns is trusted

The prompt asks for all of this; [validation.py](backend/apps/ai_content/validation.py)
checks that it happened. Models mostly comply, and "mostly" is not a standard
you can publish under a real estate licence — the dangerous failure is copy that
reads perfectly and contains one plausible invented number.

| Check | Severity |
| ----- | -------- |
| Numbers that trace to no listing field (prices, distances, percentages) | error |
| Features not in the listing (a pool, a cellar, a view) | error |
| Investment / financial claims (yield, ROI, "will appreciate", gearing) | error |
| Legal / planning claims (zoning, approvals, title, heritage) | error |
| Comparative superlatives ("best in the street") | warning |
| Place names that are not the listing's own | warning |
| Malformed or excessive hashtags | warning |

Errors are reserved for the unambiguous; heuristics that can misfire produce
warnings, because a validator that cries wolf gets switched off. Shorthand is
understood — `$1.85m` is the same fact as `$1,850,000` — and numbers appearing
in the agent's own verified description count as verified.

**Every variant is validated separately, by the same function.** A rule
enforced on the Instagram caption and quietly forgotten on the property
description would be worse than no rule, because it reads as covered. Hashtags
get an extra pass: `#7percentyield` has no word boundary before "yield", so the
sentence-level patterns miss it entirely and high-risk words are also matched as
bare substrings inside a tag.

**On rejection the copy never lands in the usable field.** It goes to
`rejected_text` / `rejected_items`, so an invented claim is not sitting where
the UI renders publishable text. It is kept, because debugging the prompt needs
it.

Variants fail independently — one bad LinkedIn caption does not spoil a good
Instagram one, which is exactly why they are reviewed one at a time.

### Three independent statuses

`job_status` (queued/running/ready/failed) · `validation_status`
(pending/passed/flagged/rejected) · `review_status` (draft/approved/rejected).

A generation can be *ready* and validation-*rejected*, and it starts as a
*draft* either way. Collapsing these would make "the model returned something"
indistinguishable from "a person approved it". Content that failed the fact
check **cannot be approved** at all.

Validation and review live on each **variant**; the generation's own status is
the worst of its variants, so a list can show "needs attention" without loading
all six.

### Editing

An agent can rewrite any variant. The edit is re-validated and the issues are
shown, but they **do not block** — the validator exists to stop the *model*
inventing, not to stop a licensed agent writing a sentence they can stand
behind, and they may well know something the listing does not record. The
variant is marked `is_edited`, the original is kept for comparison, and it
returns to *draft*: an approval that referred to different words than the ones
now on screen would be worthless.

### Generation is never a side effect

`POST /api/ai-content/generate/` is the only code path that starts a job. No
read endpoint creates one — opening a listing a hundred times costs nothing.
That is asserted directly in `test_opening_a_listing_does_not_trigger_generation`,
because an expensive external call that fires on render is a bill that grows
with page views.

Regenerating creates a **new** record rather than overwriting, so the history
survives for prompt comparison and audit.

### Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| POST | `/api/ai-content/generate/` | 202 with a job id; throttled per user |
| GET | `/api/ai-content/?listing=N` | history for a listing |
| GET | `/api/ai-content/{id}/` | full record, including the facts used |
| GET | `/api/ai-content/{id}/status/` | small payload, for polling |
| POST | `/api/ai-content/{id}/review-all/` | one decision across variants; skips what failed |
| GET | `/api/ai-content/usage/` | token and cost totals, scoped |
| GET | `/api/ai-content-variants/?generation=N` | the individual variants |
| POST | `/api/ai-content-variants/{id}/edit/` | rewrite one variant, re-validated |
| POST | `/api/ai-content-variants/{id}/review/` | approve or discard one variant |

Cost is recorded per generation — including for rejected ones, since they were
still billed. Prices are configured in settings and overridable by env, because
a stored cost computed from a stale hardcoded rate is quietly wrong. An unknown
model records 0 rather than a plausible guess.

### Judging caption quality

The tests prove the pipeline works; they cannot tell you whether the captions
are any good. For that:

```bash
docker compose exec backend python manage.py ai_sample_run
docker compose exec backend python manage.py ai_sample_run --offline   # harness only
```

Runs 15 sample listings — chosen to probe the edges, including several
deliberately sparse ones where a model is most tempted to invent — and writes
`backend/ai_sample_run.md` for you to read: all six variants per listing, with
their validation results. 90 pieces of copy in one file.

Worth checking as you read: whether the six formats actually read differently
from each other. If they are near-identical, the prompt is not earning its
variants and the extra output tokens are wasted.

---

## Compliance

A **data-driven rules engine**, not business logic. The actual requirements are
not settled and will be decided by people who do not write Python, so this app
ships generic *check types* and the rules themselves live in the database.

**Adding a rule never needs a deployment.** Adding a new *kind* of check does,
and that is the line: if a requirement can be expressed as "this phrase must
not appear" or "this field must be filled in", it is data.

### ⚠ The seeded rules are placeholders

`manage.py seed_compliance_rules` creates eight rules, every one of them marked
`PENDING LEGAL REVIEW` with a note saying so. They exist to demonstrate the
pipeline, not because anyone has approved the wording. Nothing should be
treated as final until someone with the authority sets a rule to **Approved**.

Re-seeding will not revert a rule that has been approved — so signed-off
wording cannot be silently overwritten by a redeploy.

If you do not want provisional rules blocking real work yet, set
`COMPLIANCE_BLOCK_EXPORTS=False` for advisory-only behaviour without
deactivating anything.

### Check types

| Type | `rule_data` |
| ---- | ----------- |
| `required_field_present` | `{"field": "brokerage_name", "label": "Brokerage name"}` |
| `disclaimer_present` | `{"text": "...", "match": "normalised｜exact｜all_words"}` |
| `prohibited_phrase` | `{"phrases": ["guaranteed return"], "whole_word": true}` |
| `required_phrase` | `{"phrases": [...], "mode": "any｜all"}` |
| `prohibited_pattern` | `{"pattern": "regex", "flags": "i"}` |
| `length_limit` | `{"field": "caption", "max": 2200}` |
| `custom` | `{"handler": "name_registered_in_code"}` |

Matching is deliberately tolerant of how copy travels: case, whitespace runs
and smart quotes are normalised, because a curly apostrophe is not a compliance
failure. `all_words` mode exists for disclaimers split across design elements.

**`custom` never imports anything from the database.** The obvious
implementation — `import_string(rule_data["handler"])` — would be remote code
execution by configuration, since a non-engineer edits these rows by design.
Handlers resolve against a registry populated in code; an unregistered name is
reported as a rule problem, never imported.

### A broken rule never blocks an agent

Rules are edited by non-engineers, so a malformed regex will happen. Each rule
is evaluated in its own try/except and a rule that raises is reported as
`rule_error` — a problem *with the rule*, attributed to the rule, and never
counted as a compliance failure by the content. The direction matters: a broken
rule cannot invent a failure against an agent, and cannot silently pass content
either.

### Where it runs

| Moment | Behaviour |
| ------ | --------- |
| After AI generation | every variant evaluated and stored, so flags are waiting when the agent opens the panel |
| Design editor | `GET /api/designs/{id}/compliance/` — live, unstored |
| **Design export** | evaluated first; an `error`-severity failure returns **409** with the report and nothing is rendered |

Warnings never block, and are returned alongside a successful export rather
than passed over silently. Either way the attempt is written to
`ComplianceEvaluation` as an audit trail.

Compliance sees the design as the *renderer* resolves it — including locked
elements the agent never touched, which is exactly where a required disclaimer
lives.

### The admin is the product surface

`/admin/compliance/compliancerule/` is built for whoever owns the rules:

- the `rule_data` shape for every check type is shown inline with worked examples;
- bad `rule_data` is rejected on save with a readable message, because a rule
  that saves and then silently never fires is worse than an error;
- placeholder rules are visually flagged, with a banner counting them;
- a **"try this rule against some text"** box runs the rule on save and reports
  the verdict, so an author can see what it does before it starts blocking
  exports.

### Endpoints

| Method | Path | Notes |
| ------ | ---- | ----- |
| GET | `/api/compliance/rules/` | read-only — agents are checked against rules, not in charge of them |
| GET | `/api/compliance/rules/summary/` | counts, including how much is still provisional |
| POST | `/api/compliance/evaluate/` | check a design, variant, listing or raw text now |
| GET | `/api/compliance/evaluations/` | the stored audit trail, scoped |

The sample listings are created in a transaction that is rolled back, so a
review run leaves no rows behind. `--offline` uses a canned response to check
the harness without a key or a bill; it tells you nothing about quality.

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
├── docker-compose.yml       # Postgres, Redis, Django, Celery, renderer, Vite
├── renderer/                # HTML -> image service (Playwright, warm Chromium)
├── prototypes/              # Step 4 rendering comparison (not part of the app)
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
│       ├── listings/        # property listings
│       │   ├── models.py        # Listing (+ verification rules), ListingPhoto
│       │   ├── fetching.py      # SSRF-guarded outbound fetch (read this)
│       │   ├── extraction.py    # conservative parsing; never guesses
│       │   ├── importing.py     # one-off URL import -> unverified draft
│       │   ├── services.py      # get_listing_for_content (the verified gate)
│       │   └── tests/
│       ├── templates/       # template library, controlled editing, rendering
│       │   ├── models.py        # Template, TemplateElement, Design, DesignExport
│       │   ├── overrides.py     # permission enforcement (read this)
│       │   ├── html_builder.py  # design -> HTML, fractional geometry
│       │   ├── render_context.py# listing/agent/brand data for a design
│       │   ├── rendering.py     # renderer client, export + storage
│       │   ├── dimensions.py    # the four social sizes
│       │   └── tests/
│       ├── ai_content/      # AI caption generation
│       │   ├── models.py        # GeneratedContent (job/validation/review)
│       │   ├── prompts.py       # the facts contract with the model
│       │   ├── validation.py    # fact-check the response (read this)
│       │   ├── client.py        # OpenAI wrapper; key is backend-only
│       │   ├── services.py      # synchronous pipeline (Part A)
│       │   ├── tasks.py         # Celery wrapper (Part B)
│       │   └── management/      # ai_sample_run, for judging quality
│       └── compliance/      # data-driven rules engine
│           ├── models.py        # ComplianceRule, ComplianceEvaluation
│           ├── checks.py        # the generic check types (read this)
│           ├── subjects.py      # adapters: design / AI content / listing
│           ├── engine.py        # the evaluator
│           ├── admin.py         # the non-engineer's interface
│           └── management/      # seed_compliance_rules (PLACEHOLDERS)
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

Every domain app is wired up in
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
docker compose exec backend python manage.py seed_templates  # the template library
docker compose exec backend python manage.py shell

docker compose logs -f backend
docker compose logs -f celery_worker
docker compose restart backend

docker compose exec frontend npm install <package>
docker compose exec frontend npm run typecheck
```

Rebuild after changing `requirements.txt` or `package.json`:

```bash
docker compose up -d --build
```

If one service's build fails (a flaky pull, say), compose aborts the whole `up`
and the *other* services keep running their old images — which looks like your
change had no effect. Rebuild the ones you touched explicitly:

```bash
docker compose up -d --no-deps --build backend celery_worker
```

`backend` and `celery_worker` share an image on purpose, so the worker cannot
end up running older code than the API.

Both source trees are bind-mounted, so Django's autoreloader and Vite's HMR
pick up code changes without a rebuild.

### Tests

```bash
docker compose exec backend python manage.py test
```

453 tests. The suite runs against a throwaway database, uses an in-memory
cache instead of Redis, a fast password hasher and a temporary `MEDIA_ROOT`,
so it needs nothing beyond a running Postgres. The import tests stub the fetch
layer, the render tests stub the renderer service and the AI tests stub the
provider, so no test touches the network, needs a browser, or spends money.

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
- `listings/test_listings.py` — CRUD, photos, and scoping: agent A cannot see,
  edit, delete or verify agent B's listings, including as a colleague at the
  same brokerage.
- `listings/test_verification.py` — the transitions: explicit confirmation
  required, incomplete listings refused, editing data resets verification,
  changing sales status does not, and the content gate.
- `listings/test_import.py` — extraction from structured data, refusal to
  invent anything from a bare or ambiguous page, graceful fetch failure, photo
  handling, and the SSRF guard against loopback, private ranges, the cloud
  metadata address and non-HTTP schemes.
- `templates/test_element_permissions.py` — every permission level, both what
  it allows and what it refuses, including editing a locked element via the API.
- `templates/test_designs.py` — save/reopen round trip, rename, duplicate,
  delete, the verified-listing gate, and scoping.
- `templates/test_rendering.py` — HTML composition, all four export dimensions,
  PNG and JPG, storage, and useful failure when the renderer is down.
- `ai_content/test_generation.py` — successful generation and storage, the
  prompt's field discipline, cost estimation, and a deliberately poisoned
  response (invented pool, wrong price, fake yield, planning approval) being
  caught and kept out of the caption field.
- `ai_content/test_validation.py` — every validation rule, against both copy it
  should pass and copy it should catch.
- `ai_content/test_api.py` — job dispatch and polling, review, scoping, usage
  totals, and that reads never trigger generation.
- `ai_content/test_variants.py` — one call producing all six formats, each rule
  firing on the format it was poisoned in, per-variant review and editing, and
  that one rejected variant does not spoil a good one.
- `compliance/test_engine.py` — every check type against copy it should pass
  and copy it should catch, rule selection and scoping, `rule_data` validation,
  and that a broken rule is contained. Rules are constructed by the tests: the
  placeholder content is provisional and pinning it would fail the day someone
  rewrites it.
- `compliance/test_integration.py` — evaluation after generation, the export
  gate, and that the seeded set is labelled as pending review.

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

Deliberately not included yet: CI and production settings.

**The compliance rule content is the open item.** The engine is finished; the
rules are placeholders. Someone with the authority needs to work through
`/admin/compliance/compliancerule/`, replace or confirm each rule's wording and
severity, and set it to Approved. Until then every check reports itself as
provisional, and `COMPLIANCE_BLOCK_EXPORTS=False` keeps them advisory.

When the listing import needs to handle slow pages or bulk use, move
`import_listing_from_url` into a Celery task the same way `run_generation` was
— the service function is already self-contained.

The caption validator is rule-based and its feature vocabulary is a fixed list
([`FEATURE_VOCABULARY`](backend/apps/ai_content/validation.py)). It will not
catch a feature nobody has thought of yet. Read `ai_sample_run` output
periodically and grow the list from what you see; that is cheaper and more
predictable than checking one model's output with another model.
