# Toolbox Vault Website

The web platform for Toolbox Vault: tool/asset inventory for mechanics first,
architected for other asset-heavy communities later. The website is the primary
client; a future native mobile app talks to the same API.

**Status:** Phase 1 skeleton. Structure + minimal working code, not full features.

## Stack

| Layer    | Choice                        |
|----------|-------------------------------|
| Backend  | Python + FastAPI, SQLAlchemy 2.0 (sync), Alembic, Pydantic v2 |
| Database | PostgreSQL 16 (full-text search built in) |
| Frontend | React + TypeScript + Vite, nginx serving static files |
| Storage  | MinIO (S3-compatible; photos/documents live here, never in the DB) |
| Auth     | Email + argon2 password hashing, JWT sessions |
| Deploy   | `docker compose up --build` — one command rebuilds everything |

## Run it

```bash
cp .env.example .env   # then fill in real secrets
docker compose up --build
```

- Website: http://localhost
- API docs: http://localhost/api/docs (via nginx proxy)
- API health: http://localhost/api/health

## Architecture: modules, not god files

The single binding rule of this codebase: **no god files.** The old app's
3,614-line `server.py` must never happen again.

- `backend/app/main.py` is an app factory **only** — it creates the FastAPI
  app and includes routers from the module registry. It must stay small.
- `backend/app/core/` holds universal concerns, exactly once: config, password
  hashing/JWT (`security.py`), DB engine/session (`db.py`), shared dependencies
  (`deps.py`). Modules consume these; modules never reimplement them.
- `backend/app/modules/<name>/` is one feature: `manifest.py` (what it is,
  what it needs), `routes.py` (HTTP layer only), `service.py` (business logic),
  `models.py` (tables), `schemas.py` (request/response shapes).
- **Cross-module access goes through `service.py` functions only.** Nothing
  imports another module's models, routes, or internals. A module declares its
  dependencies in its manifest; the registry refuses to load it without them.
- `frontend/src/components/` is the shared component library — the **only**
  way modules render common visuals. All styling flows through CSS variables
  from theme tokens; a hard-coded color in module code is a bug.
- `frontend/src/modules/` mirrors the backend: each module lazy-loads its own
  routes and registers them in `modules/registry.ts`.

**Adding a module:** copy `backend/app/modules/_template/` → your module,
fill in the manifest, write routes/services, add frontend pages under
`frontend/src/modules/<name>/`, register one line in each registry.

## Docs

- Build spec: `~/workspace/goals/toolbox-vault-website/files/architecture-blueprint.md`
- Goal notes: `~/workspace/goals/toolbox-vault-website/GOAL.md`
