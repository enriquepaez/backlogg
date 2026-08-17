"""S3-compatible object storage adapter (via boto3).

Used to store user avatar images uploaded through
``POST /v1/users/me/avatar``. Not tied to any single provider: the endpoint
is selected at runtime via ``Settings.R2_ENDPOINT_URL`` (empty = real
Cloudflare R2 built from ``R2_ACCOUNT_ID``; set = any S3-compatible endpoint).
The two providers used in this project are:

- **Development**: MinIO running in Docker (``docker-compose.yml``), no
  external account needed.
- **Production**: Supabase Storage (S3-compatible, free tier, no card
  required) or real Cloudflare R2.

Credentials and bucket configuration live in ``Settings`` (``R2_ENDPOINT_URL``,
``R2_ACCOUNT_ID``, ``R2_ACCESS_KEY_ID``, ``R2_SECRET_ACCESS_KEY``,
``R2_BUCKET_NAME``, ``R2_PUBLIC_BASE_URL``). Callers are responsible for
checking those are sufficiently configured *before* using this adapter — see
``backlogg.users.service._require_r2_configured``, which raises the
controlled 503 described in ``docs/api.md``. This class assumes it is only
invoked when configured and does not implement that policy itself.

boto3 is synchronous, so every network call is run off the event loop via
``asyncio.to_thread`` — the same pattern used by ``SmtpEmailSender`` in
``backlogg/core/email.py``.
"""

import asyncio

import boto3
from botocore.config import Config

from backlogg.core.config import settings


class R2StorageAdapter:
    """Thin async wrapper around a boto3 S3 client pointed at any S3-compatible endpoint."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        """Lazily build (and cache) the underlying boto3 S3 client.

        Built lazily rather than in ``__init__`` so a module-level singleton
        can be constructed even when storage is not configured (e.g. dev/CI) —
        the resulting client is simply never used in that case.
        """
        if self._client is None:
            endpoint_url = (
                settings.R2_ENDPOINT_URL
                or f"https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
            )
            self._client = boto3.client(
                "s3",
                endpoint_url=endpoint_url,
                aws_access_key_id=settings.R2_ACCESS_KEY_ID,
                aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
                region_name="auto",
                # Path-style addressing (bucket in the URL path rather than as
                # a subdomain of the endpoint) is required by MinIO and
                # Supabase Storage, which don't support virtual-hosted-style
                # requests; R2 works fine with it too, so it's safe for all
                # three providers.
                config=Config(s3={"addressing_style": "path"}),
            )
        return self._client

    def _put_object_sync(self, *, key: str, content: bytes, content_type: str) -> None:
        self._get_client().put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=key,
            Body=content,
            ContentType=content_type,
        )

    def _delete_object_sync(self, *, key: str) -> None:
        self._get_client().delete_object(Bucket=settings.R2_BUCKET_NAME, Key=key)

    async def upload(self, *, key: str, content: bytes, content_type: str) -> str:
        """Upload ``content`` under ``key`` and return the resulting public URL."""
        await asyncio.to_thread(
            self._put_object_sync, key=key, content=content, content_type=content_type
        )
        return f"{settings.R2_PUBLIC_BASE_URL.rstrip('/')}/{key}"

    async def delete(self, *, key: str) -> None:
        """Delete the object at ``key``.

        Idempotent by nature of the S3 API: ``delete_object`` succeeds even
        when the key does not exist, so callers never need to check existence
        first.
        """
        await asyncio.to_thread(self._delete_object_sync, key=key)
