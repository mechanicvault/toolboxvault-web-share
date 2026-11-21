FROM python:3.12.16-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ffmpeg: the prints module converts phone videos on upload —
# an iPhone .mov is normally HEVC, which most browsers cannot
# decode — into web-playable H.264 MP4 (bug lane 2026-11-09).
# The slim base carries no ffmpeg; this is the one system
# package the app shells out to.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Headless Chromium for the catalog lookup's rendered reader
# (sheet row 200, 2026-11-20): script-built product pages are
# read from the loaded page, not the raw HTML shell. The
# headless shell is the small build; --with-deps pulls its
# system libraries through apt in the same pattern as above.
RUN python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Migrate before serving: deploys are safe to run against an existing DB
# (alembic tracks applied revisions; `upgrade head` is a no-op when current).
# Workers (scale fix, 2026-10-26; audit B2/F-04): the API used to run
# ONE uvicorn worker for the whole site — the hard concurrency
# ceiling the load test collapsed against. API_WORKERS sizes the
# process count to the box (production CX23 = 2 vCPU → 2 workers);
# each worker carries its own DB pool (see app/core/config.py for
# the connection budget). The count stays an env dial so a bigger
# box is a settings change, never a rebuild.
# Proxy headers (sheet row 115, 2026-11-18): the API sits behind
# the web container's nginx, which appends X-Forwarded-For — without
# --proxy-headers every visitor's address read as the nginx
# container's. --forwarded-allow-ips "*" trusts the chain from any
# peer, which is safe here because the api service publishes NO
# ports (docker-compose.yml): the web container is the only process
# that can reach port 8000 at all. The app additionally prefers
# CF-Connecting-IP (app/core/rate_limit.client_ip).
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2} --proxy-headers --forwarded-allow-ips \"*\""]
