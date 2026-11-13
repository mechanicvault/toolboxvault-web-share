FROM python:3.12-slim

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
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers ${API_WORKERS:-2}"]
