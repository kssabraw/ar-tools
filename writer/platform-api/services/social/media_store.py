"""Social Media module — the media store (ADR-0004).

One store for ALL of the social module's media: user-uploaded images + videos,
and AI-generated social images. **Cloudflare R2** is the v1 impl — chosen for
**zero egress fees** (each asset is fetched by PostPeer and then the platform,
so video egress adds up) and because Cloudflare is already provisioned in the
suite (Website Builder Workers). R2 speaks the S3 API, so this uses ``boto3``.

Behind a small interface so the module isn't welded to R2 (mirrors the posting
adapter, ADR-0001): a **Supabase** fallback keeps images working when R2 creds
aren't set (video may exceed Supabase's limits — that's the degraded path).

- ``put_bytes`` — server-side write (AI-generated images: bytes produced on the
  server).
- ``presigned_put_url`` — a short-lived URL the browser PUTs a big video/user
  file straight to, so large bytes never route through the API.

Both yield a public URL (PostPeer fetches media by URL). Pure helpers
(``media_key``, ``resolve_media_type``, ``select_store``) are unit-tested; the
SDK calls are lazy-imported so the pure layer needs neither boto3 nor supabase.

Scope: the SOCIAL module only. GBP post images, article illustrations, website
heroes, and client logos stay on Supabase, unchanged.
"""

from __future__ import annotations

import abc
from typing import Optional
from uuid import uuid4

from config import settings

# Accepted upload types → (extension, media_type). Shared by the validator.
IMAGE_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}
VIDEO_TYPES = {"video/mp4": "mp4", "video/quicktime": "mov"}


# ── pure helpers (no SDK — unit-tested) ──────────────────────────────────────

def resolve_media_type(content_type: str) -> tuple[str, str]:
    """(extension, media_type) for a supported content type, else ValueError."""
    ct = (content_type or "").lower().split(";")[0].strip()
    if ct in IMAGE_TYPES:
        return IMAGE_TYPES[ct], "image"
    if ct in VIDEO_TYPES:
        return VIDEO_TYPES[ct], "video"
    raise ValueError(f"unsupported_media_type:{ct}")


def media_key(ext: str, kind: str = "upload") -> str:
    """Object key under the social/ prefix, grouped by kind (upload | generated)."""
    safe_kind = kind if kind in ("upload", "generated") else "upload"
    return f"social/{safe_kind}/{uuid4()}.{ext}"


def r2_configured() -> bool:
    """True only when every R2 setting needed to talk to a bucket is present."""
    return all([
        settings.r2_account_id, settings.r2_access_key_id, settings.r2_secret_access_key,
        settings.r2_bucket, settings.r2_public_base_url,
    ])


# ── interface ────────────────────────────────────────────────────────────────

class MediaStore(abc.ABC):
    name = "abstract"

    @abc.abstractmethod
    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        """Write bytes server-side; return the public URL."""

    @abc.abstractmethod
    def presigned_put_url(self, key: str, content_type: str, expires: int = 3600) -> dict:
        """Return {"upload_url", "public_url", "headers"} for a direct browser PUT."""

    @abc.abstractmethod
    def public_url(self, key: str) -> str:
        """Public URL for an already-stored key."""


# ── R2 (S3 API via boto3) ────────────────────────────────────────────────────

class R2Store(MediaStore):
    name = "r2"

    def __init__(self):
        self._bucket = settings.r2_bucket
        self._base = settings.r2_public_base_url.rstrip("/")
        self._client = None

    def _s3(self):
        if self._client is None:
            import boto3  # lazy
            from botocore.config import Config

            self._client = boto3.client(
                "s3",
                endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=settings.r2_access_key_id,
                aws_secret_access_key=settings.r2_secret_access_key,
                region_name="auto",
                config=Config(signature_version="s3v4"),
            )
        return self._client

    def public_url(self, key: str) -> str:
        return f"{self._base}/{key.lstrip('/')}"

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._s3().put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return self.public_url(key)

    def presigned_put_url(self, key: str, content_type: str, expires: int = 3600) -> dict:
        url = self._s3().generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires,
        )
        return {"upload_url": url, "public_url": self.public_url(key),
                "headers": {"Content-Type": content_type}}


# ── Supabase fallback (images; video may exceed limits) ──────────────────────

class SupabaseStore(MediaStore):
    name = "supabase"
    _BUCKET = "wordpress_images"  # public; PostPeer fetches media by URL

    def _sb(self):
        from db.supabase_client import get_supabase

        return get_supabase()

    def public_url(self, key: str) -> str:
        return self._sb().storage.from_(self._BUCKET).get_public_url(key).rstrip("?")

    def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        self._sb().storage.from_(self._BUCKET).upload(
            key, data, {"content-type": content_type, "upsert": "true"}
        )
        return self.public_url(key)

    def presigned_put_url(self, key: str, content_type: str, expires: int = 3600) -> dict:
        signed = self._sb().storage.from_(self._BUCKET).create_signed_upload_url(key)
        return {"upload_url": signed.get("signed_url") or signed.get("signedUrl"),
                "public_url": self.public_url(key),
                "headers": {"Content-Type": content_type}}


def select_store(prefer_r2: Optional[bool] = None) -> str:
    """Which store the factory would return: 'r2' when R2 is configured, else
    'supabase'. Pure (reads config)."""
    use_r2 = r2_configured() if prefer_r2 is None else prefer_r2
    return "r2" if use_r2 else "supabase"


def get_media_store() -> MediaStore:
    """The configured media store (R2 when its creds are set, else Supabase)."""
    return R2Store() if select_store() == "r2" else SupabaseStore()
