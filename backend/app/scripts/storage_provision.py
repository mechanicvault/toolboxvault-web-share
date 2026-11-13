"""One-shot object-storage provisioning (docker-compose jobs).

SeaweedFS replaced MinIO in October 2026 after MinIO withdrew its
public images and binaries. Provisioning has two steps, run by two
compose one-shots before the API starts:

  write-config   render the S3 identity config (admin + app user)
  create-bucket  create the app bucket with the admin identity

The root (admin) credentials are used ONLY here; the API itself
connects with the least-privilege app identity (see core/storage.py).
The MINIO_* environment names are legacy from the MinIO era and are
kept so existing .env files keep working.
"""

import json
import os
import sys
import time

CONFIG_PATH = os.environ.get("S3_CONFIG_PATH", "/config/s3.json")
BUCKET = os.environ.get("MINIO_BUCKET", "toolbox-vault")
ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://storage:8333")


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"storage_provision: {name} is not set")
    return value


def write_config() -> None:
    app_user = os.environ.get("MINIO_APP_USER", "toolbox-app")
    config = {
        "identities": [
            {
                "name": "admin",
                "credentials": [
                    {
                        "accessKey": _required("MINIO_ROOT_USER"),
                        "secretKey": _required("MINIO_ROOT_PASSWORD"),
                    }
                ],
                "actions": ["Admin"],
            },
            {
                "name": app_user,
                "credentials": [
                    {
                        "accessKey": app_user,
                        "secretKey": _required("MINIO_APP_PASSWORD"),
                    }
                ],
                # Object-level access only: no bucket creation, no
                # identity/admin operations (audit I5, least privilege).
                "actions": ["Read", "Write", "List", "Delete", "Tagging"],
            },
        ]
    }
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(config, fh, indent=2)
    print(f"storage-config: wrote {CONFIG_PATH}", flush=True)


def create_bucket() -> None:
    import boto3
    from botocore.exceptions import ClientError, EndpointConnectionError

    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=_required("MINIO_ROOT_USER"),
        aws_secret_access_key=_required("MINIO_ROOT_PASSWORD"),
    )
    deadline = time.time() + 180
    while True:
        try:
            client.head_bucket(Bucket=BUCKET)
            print(f"storage-init: bucket '{BUCKET}' already exists", flush=True)
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchBucket", "404 Not Found"}:
                client.create_bucket(Bucket=BUCKET)
                print(f"storage-init: created bucket '{BUCKET}'", flush=True)
                return
            raise
        except EndpointConnectionError:
            if time.time() > deadline:
                raise
            print("storage-init: waiting for storage...", flush=True)
            time.sleep(3)


if __name__ == "__main__":
    commands = {"write-config": write_config, "create-bucket": create_bucket}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit("usage: storage_provision {write-config|create-bucket}")
    commands[sys.argv[1]]()
