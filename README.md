# Toolbox Vault Website

The web platform for Toolbox Vault: tool and asset inventory for
mechanics first, built to serve other asset-heavy communities later.
The website is the full-featured companion to the Toolbox Vault
mobile app — accounts, inventory, dealers, claims, sharing, 3D
print files, reports and admin tooling all live here.

**Status:** live in production at https://toolboxvault.com. This
repository is the production codebase, not a skeleton.

## Stack

| Layer    | Choice |
|----------|--------|
| Backend  | Python + FastAPI, SQLAlchemy 2.0 (sync), Alembic, Pydantic v2 |
| Database | PostgreSQL 16 (pinned image; full-text search built in) |
| Frontend | React + TypeScript + Vite, nginx serving the built files |
| Storage  | SeaweedFS (S3-compatible; photos/documents live here, never in the DB) |
| Auth     | Email + argon2 password hashing, JWT access tokens + database refresh tokens |
| Payments | Stripe (dark unless keys are configured — see `.env.example`) |
| Deploy   | `docker compose up --build` locally; pushes to `main` deploy production |

Storage notes: the environment still uses legacy `MINIO_*`
variable names (see `.env.example`) — the server behind them is
SeaweedFS, reached inside the stack at `http://storage:8333`.

## Run it

```bash
cp .env.example .env   # then fill in real secrets
docker compose up --build
```

The compose stack starts seven services: `postgres`, `storage`
(SeaweedFS) plus its one-shot `storage-config` / `storage-init`
provisioning jobs, `api` (which applies `alembic upgrade head`
before serving), `web` (nginx), `jobs` (the scheduler:
`python -m app.scripts.scheduler`) and `backup`.

- Website: http://localhost
- API health: http://localhost/api/core/health
- API docs are **not** served through the website's nginx —
  `/api/docs` returns 404 by design. To browse the OpenAPI
  docs, run the API directly (below) and open
  http://localhost:8000/docs.

## Working on it

Backend (from `backend/`):

```bash
python -m pytest tests/            # suite (SQLite + in-memory fake storage)
tests/run_pg_tests.sh              # the same suite against real PostgreSQL
uvicorn app.main:app --port 8000   # run the API directly (docs at /docs)
```

Frontend (from `frontend/`):

```bash
npm run dev    # Vite dev server
npm run build  # inline-style check + tsc + production build
```

## Architecture: modules, not god files

The single binding rule of this codebase: **no god files.** The
old app's 3,614-line `server.py` must never happen again.

- `backend/app/main.py` is an app factory **only** — it creates
  the FastAPI app and includes routers from the module registry.
  It must stay small.
- `backend/app/core/` holds universal concerns, exactly once:
  config, password hashing/JWT (`security.py`), DB
  engine/session (`db.py`), shared dependencies (`deps.py`),
  and shared helpers such as `business_time.py` (the
  America/Chicago business-day framing the admin numbers use).
  Modules consume these; modules never reimplement them.
- `backend/app/modules/<name>/` is one feature: `manifest.py`
  (what it is, what it needs), `routes.py` (HTTP layer only),
  `service.py` (business logic), `models.py` (tables),
  `schemas.py` (request/response shapes).
- **Cross-module access goes through `service.py` functions
  only.** Nothing imports another module's models, routes, or
  internals. A module declares its dependencies in its
  manifest; the registry refuses to load it without them.
- `frontend/src/components/` is the shared component library —
  the **only** way modules render common visuals. All styling
  flows through CSS variables from theme tokens; a hard-coded
  color in module code is a bug.
- `frontend/src/modules/` mirrors the backend: each module
  lazy-loads its own routes and registers them in
  `modules/registry.ts`.

**Adding a module:** copy `backend/app/modules/_template/` →
your module, fill in the manifest, write routes/services, add
frontend pages under `frontend/src/modules/<name>/`, register
one line in each registry.

## Docs

- Disaster recovery: `docs/RESTORE.md` — rebuilding the whole
  site from a Disaster Vault bundle.
- `.env.example` documents every environment value the stack
  needs; nothing is hard-coded.
