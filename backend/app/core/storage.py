"""Universal object-storage service (S3-compatible, SeaweedFS in our stack).

Universal infrastructure: modules never talk to boto3 directly. The flow is
presigned URLs — bytes never pass through the API or the database:

  1. Client asks for an upload URL (module route -> service -> here).
  2. Client PUTs the file straight to storage with that URL.
  3. Client tells the API the upload finished; the API HEADs the object to
     verify size/type before attaching the *key* (never bytes) to a record.

Only storage keys are persisted. Read URLs are minted fresh at read time
because presigned URLs expire.
"""

import re
import uuid
from dataclasses import dataclass

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings

# What users may upload, by kind. Content-Type is checked at URL issuance
# and re-verified with a HEAD request before the key is attached to a record.
# Per-kind acceptance (owner clarification, 2026-10-18): photos are
# IMAGES ONLY. Documents and receipts accept images too (a photo of a
# calibration card / receipt) PLUS real document files — PDF, Word,
# Excel, plain text. Anything else (executables above all) is refused
# for every kind, at upload-URL issuance AND again at attach time
# against the stored object's real content type.
_DOCUMENT_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
    "image/jpeg",
    "image/png",
    "image/webp",
}

ALLOWED_CONTENT_TYPES: dict[str, set[str]] = {
    "photo": {"image/jpeg", "image/png", "image/webp"},
    "document": set(_DOCUMENT_TYPES),
    "receipt": set(_DOCUMENT_TYPES),
    # Manuals are their own attachment kind/area (owner ruling
    # 2026-11-03) with the same file types as documents.
    "manual": set(_DOCUMENT_TYPES),
}

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")

# -- presigned read lifetimes (deep audit F4-07) -------------------------
# A presigned URL is a bearer capability: anyone holding one can fetch
# the file with no account. The default is therefore ONE HOUR — every
# interactive surface (serializers, reports, dealer logos) mints fresh
# URLs on each read, so nothing legitimate notices. The single scoped
# exception is the data-export manifest: when a file's bytes could not
# be bundled into the owner's downloaded archive, the manifest carries
# a fallback link the owner may open later from the archive they keep,
# so that ONE call path passes the longer value explicitly.
PRESIGNED_GET_TTL_SECONDS = 3600
EXPORT_FALLBACK_TTL_SECONDS = 86400

# -- content sniffing (deep audit F4-06) ---------------------------------
# The content-type checks above trust the client's declaration (the
# PUT signature binds the DECLARED type, and HEAD reads it back) — but
# nothing verified the BYTES. An HTML file uploaded as "image/png"
# attached cleanly and was served as image/png from the files origin.
# At attach time the API now reads the object's leading bytes and
# checks them against the declared type's magic signature.
_SNIFF_BYTES = 512
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"
_PDF_MAGIC = b"%PDF-"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # legacy .doc/.xls
_ZIP_MAGICS = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")  # OOXML


def _looks_like_text(prefix: bytes) -> bool:
    """Plain-text check for text/plain declarations: no NUL bytes and
    (nearly) everything printable or whitespace. Deliberately light —
    text/plain is served as text/plain with nosniff, so the residual
    risk is a mislabeled file, not script execution."""
    if not prefix or b"\x00" in prefix:
        return False
    try:
        text = prefix.decode("utf-8")
    except UnicodeDecodeError:
        text = prefix.decode("latin-1")
    bad = sum(1 for ch in text if not (ch.isprintable() or ch in "\r\n\t\f\v"))
    return bad <= max(1, len(text) // 100)


def content_matches_declared(content_type: str, prefix: bytes) -> bool:
    """True when the leading bytes are consistent with the declared
    content type. Types outside the table (shouldn't occur — attach
    runs the allowlist first) fail closed."""
    ct = (content_type or "").lower().strip()
    if ct == "image/jpeg":
        return prefix[:3] == _JPEG_MAGIC
    if ct == "image/png":
        return prefix[:8] == _PNG_MAGIC
    if ct == "image/webp":
        return len(prefix) >= 12 and prefix[:4] == b"RIFF" and prefix[8:12] == b"WEBP"
    if ct == "application/pdf":
        return prefix[:5] == _PDF_MAGIC
    if ct in (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ):
        return prefix[:4] in _ZIP_MAGICS
    if ct in ("application/msword", "application/vnd.ms-excel"):
        # Legacy Office is an OLE compound file; the same extension
        # also legitimately holds OOXML (ZIP) content in the wild.
        return prefix[:8] == _OLE_MAGIC or prefix[:4] in _ZIP_MAGICS
    if ct == "text/plain":
        return _looks_like_text(prefix)
    return False


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class StorageError(RuntimeError):
    """Raised for any storage problem the caller should turn into a 4xx/5xx."""


class S3Storage:
    """Thin wrapper around boto3. One shared instance below."""

    def __init__(self) -> None:
        # Presigned URLs must be reachable by the *browser*, which may not
        # resolve the in-docker hostname (e.g. "storage:8333"). SigV4 signs
        # the Host header, so URLs must be *generated* against the public
        # endpoint — signing with the internal host and swapping the
        # hostname afterwards produces signatures that never validate.
        # Two clients, then: internal for server-side operations (HEAD,
        # delete, bucket ops), public for presigned URL generation only.
        # Both use the least-privilege APP credentials (bucket-scoped,
        # created by the storage provisioning jobs) — never the MinIO root login.
        self.public_endpoint = settings.s3_public_endpoint or settings.minio_endpoint
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.minio_endpoint,
            aws_access_key_id=settings.minio_app_user,
            aws_secret_access_key=settings.minio_app_password,
        )
        self._public_client = boto3.client(
            "s3",
            endpoint_url=self.public_endpoint,
            aws_access_key_id=settings.minio_app_user,
            aws_secret_access_key=settings.minio_app_password,
        )
        self.bucket = settings.minio_bucket

    # -- buckets ---------------------------------------------------------
    def ensure_bucket(self) -> None:
        """Confirm the app bucket exists. The bucket itself is created by
        the storage provisioning jobs (the app credentials deliberately cannot create
        buckets); the create call below only helps local dev setups that
        grant broader rights."""
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                self._client.create_bucket(Bucket=self.bucket)
            else:
                raise StorageError(f"Cannot reach bucket: {exc}") from exc

    # -- keys ------------------------------------------------------------
    @staticmethod
    def safe_filename(filename: str) -> str:
        name = _SAFE_NAME.sub("_", filename.rsplit("/", 1)[-1]).strip("._")
        return name[:120] or "file"

    def object_key(
        self,
        owner_id: str,
        item_id: str,
        kind: str,
        filename: str,
        collection: str = "tools",
    ) -> str:
        """Keys are namespaced so a user can only ever attach their own
        files: {owner}/{collection}/{item}/{kind}/{uuid}-{filename}.
        `collection` is 'tools' (the original shape) or 'batteries'."""
        return (
            f"{owner_id}/{collection}/{item_id}/{kind}/"
            f"{uuid.uuid4().hex}-{self.safe_filename(filename)}"
        )

    # -- presigned URLs --------------------------------------------------
    def presigned_put_url(
        self, key: str, content_type: str, expires_in: int = 900
    ) -> str:
        """URL the client PUTs the file to. Short-lived by design."""
        self.ensure_bucket()
        return self._public_client.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=expires_in,
        )

    def presigned_get_url(
        self, key: str, expires_in: int = PRESIGNED_GET_TTL_SECONDS
    ) -> str:
        """Fresh read URL, minted at read time. Default lifetime is
        one hour (deep audit F4-07 — a presigned URL is a bearer
        capability); callers that genuinely need longer pass it
        explicitly (see EXPORT_FALLBACK_TTL_SECONDS)."""
        return self._public_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    # -- content verification (deep audit F4-06) -------------------------
    def fetch_prefix(self, key: str, length: int = _SNIFF_BYTES) -> bytes:
        """The object's first `length` bytes (range read — the whole
        file is never pulled for a sniff check)."""
        try:
            response = self._client.get_object(
                Bucket=self.bucket, Key=key, Range=f"bytes=0-{length - 1}"
            )
            return response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Could not read stored file: {exc}") from exc

    def verify_content_matches(self, key: str, content_type: str) -> None:
        """Raise StorageError when the stored bytes contradict the
        declared content type (magic-byte sniff at attach time)."""
        prefix = self.fetch_prefix(key)
        if not content_matches_declared(content_type, prefix):
            raise StorageError(
                "The uploaded file's contents don't match its declared "
                f"file type ('{content_type}')."
            )

    # -- verification ----------------------------------------------------
    def head(self, key: str) -> StoredObject:
        """Verify an uploaded object exists; return its real size and type."""
        try:
            meta = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            code = exc.response["ResponseMetadata"]["HTTPStatusCode"]
            if code == 404:
                raise StorageError("Uploaded file not found in storage") from exc
            raise StorageError(f"Storage error: {exc}") from exc
        return StoredObject(
            key=key,
            size_bytes=meta["ContentLength"],
            content_type=meta.get("ContentType", ""),
        )

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            raise StorageError(f"Could not delete stored file: {exc}") from exc

    def copy(self, source_key: str, dest_key: str) -> StoredObject:
        """Server-side copy within the bucket (the parts module's
        convert-to-tool flow moves a photo into the tool's namespace
        so each record's files live and die with that record).
        Returns the destination's verified metadata, like head()."""
        try:
            self._client.copy_object(
                Bucket=self.bucket,
                CopySource={"Bucket": self.bucket, "Key": source_key},
                Key=dest_key,
            )
        except ClientError as exc:
            raise StorageError(f"Could not copy stored file: {exc}") from exc
        return self.head(dest_key)

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject:
        """Store bytes the SERVER fetched itself (wave 4: a located
        user manual the backend downloaded on the owner's behalf).
        The client-upload flow stays presigned; this is only for
        server-originated files. Returns verified metadata, like
        head()."""
        self.ensure_bucket()
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except ClientError as exc:
            raise StorageError(f"Could not store file: {exc}") from exc
        return self.head(key)

    def fetch(self, key: str) -> bytes:
        """Download an object's bytes (server-side reads: the data
        export bundles a user's files into their archive). Raises
        StorageError on any failure — callers decide whether a
        missing file is fatal (export: it isn't; the manifest falls
        back to a presigned link)."""
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except Exception as exc:
            raise StorageError(f"Could not fetch stored file: {exc}") from exc

    def list_keys(self, prefix: str) -> list[str]:
        """Every object key under `prefix`, paginated. Exists
        for the backfill scripts that sweep a bounded platform
        prefix (platform/logos/) — application reads always
        name the exact key they want."""
        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    keys.append(obj["Key"])
        except ClientError as exc:
            raise StorageError(f"Could not list stored files: {exc}") from exc
        return keys


storage = S3Storage()
