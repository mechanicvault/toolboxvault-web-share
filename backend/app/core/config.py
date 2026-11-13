"""Centralized configuration.

Every setting the app needs comes from environment variables, loaded once
here. Modules read settings from this module — they never read os.environ
directly and never define their own config for shared concerns.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


def env_value(name: str) -> str:
    """Read ONE environment variable by name. This is the single
    sanctioned os.environ read outside this module: the admin
    panel stores key REFERENCE NAMES (e.g. the AI provider key is
    configured as "the env var named OPENAI_API_KEY"), so the
    consumer must resolve a name it was handed at runtime. Never
    use this for a fixed setting — those are Settings fields."""
    import os

    return os.environ.get(name, "") or ""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://toolbox:change-me@postgres:5432/toolbox_vault"

    # Database connection pool (scale fix, 2026-10-26; audit
    # B2/F-04). SQLAlchemy's untouched defaults (5 + 10 overflow)
    # were the site's hard concurrency ceiling: one worker holding
    # 15 connections total, so ~15 slow in-flight requests queued
    # EVERYTHING behind 30 s pool timeouts. Sizing for the
    # production box (Hetzner CX23: 2 vCPU / 4 GB RAM, Postgres
    # max_connections = 100): 2 API workers x (20 + 10) = 60
    # connections worst case, leaving ~40 for the jobs + backup
    # containers and operator sessions. pool_recycle retires
    # connections hourly so a Postgres restart / failover never
    # strands the pool on dead sockets (pre_ping already guards
    # the checkout side). Env: DB_POOL_SIZE / DB_MAX_OVERFLOW /
    # DB_POOL_RECYCLE_SECONDS.
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_recycle_seconds: int = 1800

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    # Refresh tokens (long-lived, rotating) keep users signed in without
    # stretching the access token's lifetime. See modules/core/service.py.
    refresh_token_expire_days: int = 30
    email_verification_expire_hours: int = 24
    # Password-reset and email-change links: short-lived and
    # single-use (see modules/core/service.py). One hour is long
    # enough to fetch the email on another device, short enough
    # that a leaked link is a small window.
    password_reset_expire_hours: int = 1
    email_change_expire_hours: int = 1

    # Transactional email (provider: Resend, owner-approved
    # 2026-10-18). EMAIL_PROVIDER selects the transport:
    #   "dev"    — no network send; the message is logged and an
    #              email_outbox row is recorded (status "logged").
    #              This is the pre-launch default: the owner's
    #              Resend account/key don't exist yet, and every
    #              flow stays fully testable against the outbox.
    #   "resend" — POST https://api.resend.com/emails with
    #              RESEND_API_KEY; the outbox row records the real
    #              outcome ("sent" / "failed"). A failed send never
    #              raises into the request that triggered it.
    # Keys arrive via the server .env (the deploy workflow syncs
    # them from GitHub secrets, same as the OAuth credentials).
    email_provider: str = "dev"
    resend_api_key: str = ""
    email_from: str = "Toolbox Vault <noreply@toolboxvault.com>"
    # Request budget for the unauthenticated email-sending doors
    # (password-reset request, verification resend): per (IP, email)
    # AND per email, whichever fills first.
    password_reset_rate_limit_attempts: int = 5
    password_reset_rate_limit_window_seconds: int = 3600

    # Payments (Stripe, owner-approved 2026-10-18 for maximum
    # payment methods: cards, Apple/Google Pay, Cash App Pay, Link,
    # ACH). The account doesn't exist yet (it will be created under
    # MechanicVault@gmail.com), so all three values are EMPTY and
    # the wiring is completely dark: checkout/portal answer 503
    # {code: payments_not_configured}, the webhook route 404s, and
    # the UI hides purchase actions. No key = nothing chargeable,
    # by construction. Keys arrive via the server .env (the deploy
    # workflow syncs them from GitHub secrets). Price IDs are NOT
    # here — they're operator settings (Admin -> Settings), because
    # pricing is the owner's call and must not need a deploy.
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""

    # Brute-force protection on /login: after this many failed attempts for
    # one (IP, account) pair inside the window, further attempts get a 429.
    login_rate_limit_attempts: int = 5
    login_rate_limit_window_seconds: int = 60

    # Public origin of the website, used to build links in emails
    # (e.g. the verification link). Empty in local dev.
    app_base_url: str = ""

    # Social login (OAuth 2.0). A provider counts as "configured" only
    # when BOTH its id and secret are set; unconfigured providers are
    # hidden from the UI and their endpoints 404. Credentials arrive via
    # the server .env (the deploy workflow syncs them from GitHub
    # secrets — see .github/workflows/deploy.yml).
    google_client_id: str = ""
    google_client_secret: str = ""
    facebook_app_id: str = ""
    facebook_app_secret: str = ""
    # Lifetime of the signed `state` value guarding OAuth callbacks:
    # long enough for a provider round trip, too short to be worth
    # leaking. Enforced by app.core.security's state-token helpers.
    oauth_state_expire_minutes: int = 10

    # Object storage (SeaweedFS since Oct 2026). The MINIO_* names are
    # legacy from the MinIO era, kept so existing .env files keep working.
    minio_endpoint: str = "http://storage:8333"
    # Least-privilege app credentials, provisioned by the docker-compose
    # `storage-config` job. The storage ROOT credentials are used solely
    # by the provisioning jobs — the API never sees them.
    minio_app_user: str = "toolbox-app"
    minio_app_password: str = "change-me"
    minio_bucket: str = "toolbox-vault"
    # URL the *browser* uses for presigned links. Empty = same as minio_endpoint.
    # In production this is the public files URL (e.g. behind nginx).
    s3_public_endpoint: str = ""

    # Largest single photo/document/receipt upload, in megabytes.
    upload_max_mb: int = 10

    # Field-encryption key for secrets stored in the database
    # (wave 4: users' Google Drive refresh tokens). A Fernet key
    # (urlsafe base64, 32 bytes). EMPTY = derive one from the JWT
    # secret (see app/modules/core/cloud_crypto.py) — workable,
    # but rotating the JWT secret then strands stored tokens;
    # a dedicated key is the production posture.
    token_encryption_key: str = ""

    # Git commit the running code was deployed from, stamped into
    # the server .env by the deploy workflow (APP_GIT_COMMIT). The
    # backup job records it in each bundle's manifest so a restored
    # replica is traceable to an exact commit. Empty when unknown.
    app_git_commit: str = ""

    # -- Disaster Vault (platform backups, owner spec 2026-10-18) ----
    # Read by the backup service (app/backup/), which shares this
    # config and the server .env with the API. Fail-safe posture:
    # every leg is opt-in by the presence of its env values — with
    # nothing set, nightly bundles are still built and kept locally,
    # just never encrypted and never uploaded (see app/backup/job.py).
    # Nightly bundle time, UTC, "HH:MM".
    backup_time_utc: str = "03:30"
    # Weekly digest send time (UTC) and weekday (0 = Monday).
    backup_digest_time_utc: str = "14:00"
    backup_digest_weekday: int = 0
    # age RECIPIENT (public) key bundles are encrypted to. The
    # matching private key never lives on the server — it is held
    # by the owner and in the Secure Vault. Empty = encryption not
    # configured: bundles stay local-only, runs are marked so.
    backup_age_public_key: str = ""
    # Google Drive upload leg (2026-10-24): OAuth AS the
    # MechanicVault account — a service account has no storage
    # quota, so the old SA leg could never upload. The operator
    # connects once in Admin -> Settings; the refresh token lives
    # in the platform_drive_connection table (encrypted at rest).
    # This setting is only the vault folder's Drive id; uploads
    # happen only while a connection row exists.
    backup_drive_folder_id: str = ""
    # Where backup reports (weekly digest + failure alerts) go.
    backup_report_email: str = "MechanicVault@gmail.com"
    # Rolling retention: bundles kept locally and in Drive.
    backup_keep: int = 7
    # Inside the backup container: the deployed source tree (mounted
    # read-only) and the staging/retention directory (a volume).
    backup_source_dir: str = "/source"
    backup_dir: str = "/backups"


settings = Settings()
