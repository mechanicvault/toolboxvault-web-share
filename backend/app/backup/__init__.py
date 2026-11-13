"""Disaster Vault — the platform backup service (owner spec 2026-10-18).

Runs as its own container (see docker-compose `backup` service and
backend/Dockerfile.backup), sharing the API's code, config, and
.env. Contents:

  job.py       — the nightly bundle job + weekly digest job
  reports.py   — digest / failure-alert email content (pure builders)
  restore.py   — put a bundle's objects back into a bucket (drills
                 and the RESTORE.md runbook call this)
  scheduler.py — the service's loop: nightly bundle + weekly digest

The ledger is the backup_runs table (modules/core/models.py
BackupRun; migration 0013). Every run writes its row up front and
completes it with the outcome — a dead job leaves a visible
"running" row, never a silent gap.
"""
