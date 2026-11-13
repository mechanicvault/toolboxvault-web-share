"""Restore a bundle's stored objects into the app bucket.

Used by restore drills and by docs/RESTORE.md (step 6): given an
extracted bundle directory (the folder holding manifest.json +
objects/), upload every object at its original key and verify
each one's SHA-256 against the manifest — first from the local
bytes, then by reading the object back from the bucket. A restore
that cannot prove byte-equality has not restored anything.

Connection settings come from the environment via app.core.config
(MINIO_ENDPOINT / MINIO_APP_USER / MINIO_APP_PASSWORD /
MINIO_BUCKET) — in a drill those are the scratch stack's values,
in a real restore the new server's, both from the bundle's .env.

    python -m app.backup.restore --bundle-dir /path/to/toolboxvault-YYYYMMDD
    python -m app.backup.restore --objects-dir /path/to/objects \
        --manifest /path/to/manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import boto3

from app.core.config import settings


def restore_objects(bundle_dir: Path) -> int:
    """Upload + verify every object in the bundle. Returns the
    object count; raises RuntimeError on any mismatch."""
    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    objects_dir = bundle_dir / "objects"
    client = boto3.client(
        "s3",
        endpoint_url=settings.minio_endpoint,
        aws_access_key_id=settings.minio_app_user,
        aws_secret_access_key=settings.minio_app_password,
    )
    restored = 0
    for entry in manifest.get("objects", []):
        key = entry["key"]
        local = objects_dir / key
        data = local.read_bytes()
        local_hash = hashlib.sha256(data).hexdigest()
        if local_hash != entry["sha256"]:
            raise RuntimeError(
                f"bundle object {key} does not match its manifest hash "
                "— the bundle is corrupt; stop and use another day's bundle"
            )
        client.put_object(
            Bucket=settings.minio_bucket,
            Key=key,
            Body=data,
            ContentType=entry.get("content_type") or "application/octet-stream",
        )
        back = client.get_object(Bucket=settings.minio_bucket, Key=key)["Body"].read()
        if hashlib.sha256(back).hexdigest() != entry["sha256"]:
            raise RuntimeError(
                f"object {key} read back from storage with a different "
                "hash than the manifest — restore is NOT verified"
            )
        restored += 1
    return restored


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore bundle objects")
    parser.add_argument("--bundle-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    count = restore_objects(args.bundle_dir)
    print(f"restored {count} object(s), all hashes match the manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main())
