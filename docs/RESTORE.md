# Toolbox Vault — Restore Runbook

**Who this is for:** a competent operator (human or AI) starting from
zero, rebuilding the ENTIRE Toolbox Vault website from one Disaster
Vault bundle after a total loss (host gone, account closed, disk
dead). Everything needed is inside the bundle: source code, server
configuration, ALL secrets, the full database, and every stored
user file. Follow the steps in order; each step says how to know it
worked.

## What you have

A bundle file: `toolboxvault-YYYYMMDD.tar.zst.age`

- `.age` — encrypted with the **age** tool to the owner's public
  key. You need the matching **private key** to open it. The private
  key is NOT in the bundle and was NEVER on the server: the owner
  holds it (and a copy lives in the owner's Secure Vault). Ask the
  owner for it; do not proceed without it, and never store it in
  the repo or on the new server afterwards.
- Inside, after decrypting and unpacking, one folder
  `toolboxvault-YYYYMMDD/` containing:
  - `manifest.json` — the bundle's table of contents: creation
    time, git commit, row counts (users, tools), every stored
    file's name/size/SHA-256, the database dump's SHA-256.
    **Verify against this at the end.**
  - `database.dump` — the complete PostgreSQL database
    (pg_dump custom format).
  - `objects/` — every file from object storage, at its original
    storage key (e.g. `objects/<user-id>/tools/<tool-id>/photo/...`).
  - `source/` — the complete deployed source tree, INCLUDING the
    server `.env` with all live secrets (database password, JWT
    secret, storage credentials, OAuth + email keys). Treat this
    folder as toxic-waste sensitive until the site is up, then it
    is simply the server's own `.env` again.
  - `RESTORE.md` — this file.

Deliberately NOT in the bundle (anti-bloat law): `node_modules`,
`.venv`, built frontend `dist`, `.git`. They are regenerated from
the lockfiles during the Docker build in step 5 — that is why the
bundle stays small enough to upload reliably.

## Step 0 — Provision a host

Any Linux VPS with Docker works (the site ran on a 2 vCPU / 4 GB
Hetzner CX23; that class is plenty). You need: root SSH, ~10 GB
free disk beyond the bundle size, and ports 80/443 reachable.
Note the host's public IP for the DNS step at the end.

## Step 1 — Install Docker

On a fresh Ubuntu:

```sh
apt-get update && apt-get install -y docker.io docker-compose-v2 \
  age zstd postgresql-client
systemctl enable --now docker
```

(`age`/`zstd` are only needed on the host for step 2; the restore
itself uses the project's own containers.)

## Step 2 — Decrypt and unpack the bundle

```sh
age -d -i /path/to/private-key.txt -o bundle.tar.zst \
  toolboxvault-YYYYMMDD.tar.zst.age
mkdir restore && tar --zstd -xf bundle.tar.zst -C restore
cd restore/toolboxvault-YYYYMMDD
BUNDLE_DIR=$PWD   # steps 5 and 6 use this path — keep it
sha256sum database.dump   # compare with manifest.json: db_dump.sha256
```

If the checksum differs, STOP — the bundle is corrupt; get a
different day's bundle.

## Step 3 — Place the source tree

```sh
mkdir -p /opt/toolbox-vault
cp -a source/ /opt/toolbox-vault/app
cd /opt/toolbox-vault/app
ls -la .env docker-compose.yml   # both must exist
```

`source/.env` is the production environment, secrets included —
the stack below reads it as-is. No configuration step exists;
that is the point of the bundle.

## Step 4 — Start the database and storage

```sh
docker compose up -d postgres storage storage-config storage-init
docker compose ps   # postgres healthy; storage up; the two init jobs exited 0
```

## Step 5 — Restore the database

```sh
docker cp "$BUNDLE_DIR/database.dump" "$(docker compose ps -q postgres)":/tmp/database.dump
docker compose exec postgres sh -c \
  'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     --clean --if-exists --no-owner /tmp/database.dump'
docker compose exec postgres sh -c \
  'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from users;"'
```

The user count must equal `counts.users` in `manifest.json`.
(`--clean` drops the empty schema the API's migrations will have
created if the API started first — order in this runbook avoids
that, but the flag makes re-runs safe.)

## Step 6 — Restore the stored files

From the app directory, using the backup service's own image (it
is part of the source tree):

```sh
docker compose build backup
docker compose run --rm --no-deps \
  -v "$BUNDLE_DIR:/bundle:ro" \
  backup python -m app.backup.restore --bundle-dir /bundle
```

The tool uploads every file under `objects/` to the app bucket at
its original key and verifies each file's SHA-256 against
`manifest.json` as it goes. It prints `restored N object(s), all
hashes match the manifest` — anything else is a failure; do not
continue past a hash mismatch.

## Step 7 — Bring the whole site up

```sh
docker compose up --build -d
docker compose ps   # api healthy, web up on port 80
curl -s -o /dev/null -w '%{http_code}\n' http://localhost/   # 200
```

The API runs its migrations on boot (`alembic upgrade head`) —
against the restored database that is a no-op, because the dump
already carries the schema at the bundle's revision.

## Step 8 — Verify the replica

1. Row counts: `users` and `tools` counts (step 5) equal
   `manifest.json` counts.
2. Objects: step 6 reported every hash matching.
3. Sign in: open the site, log in with a real account. Passwords
   were restored with the database (they are hashes — nobody,
   including you, can or should read them).
4. Open a tool with photos: the photos must load (they come from
   the restored object storage).

## Step 9 — Point the world at it

DNS is at Cloudflare (owner's account): update the `A` records for
`toolboxvault.com` and `files.toolboxvault.com` to the new host's
IP (both were proxied; keep them proxied). The site's TLS
terminates at Cloudflare in Flexible mode, so no certificate work
exists on the host. If Cloudflare itself is unavailable, the site
answers directly on the host IP over HTTP meanwhile.

## Step 10 — Resume backups

The `backup` service is part of the stack you just started: it
resumes the nightly schedule on its own (default 03:30 UTC). Its
posture depends on the restored `.env`:

- `BACKUP_AGE_PUBLIC_KEY` set → bundles are encrypted again.
- `BACKUP_DRIVE_FOLDER_ID` set AND the backup Drive connection
  re-made (Admin → Settings → Backups → "Connect backup Drive",
  signing in as the backup account) → bundles upload to the Drive
  vault again. The connection's refresh token lives in the restored
  database (`platform_drive_connection`, encrypted at rest), so a
  restore that includes the database usually brings the connection
  back with it; if uploads show as not connected, just reconnect.
- Either missing → bundles stay on the server and runs are marked
  `local_only` / `encryption_not_configured` — safe, visible in
  Admin → Settings, and the weekly digest says so out loud.

**Then shred the private key copy you used** if you placed one on
the host — it must not stay on the server.

## If something's wrong

- **API unhealthy / migration errors:** the database restore
  (step 5) did not complete; check `docker compose logs api`.
- **Photos 404:** step 6 didn't finish, or the `files` DNS record
  points at the old host.
- **Nobody can log in:** if the database restored, logins work —
  suspect DNS/Cloudflare still routing to the old host.
- **A different day:** bundles are kept for 7 days both on the
  server and in Drive. Any day's bundle restores the same way;
  prefer the newest one whose step-2 checksum verifies.
