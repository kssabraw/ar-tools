"""POST /files/upload — file upload and text extraction endpoint."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from db.supabase_client import get_supabase
from middleware.auth import require_admin, require_auth
from models.files import FileUploadResponse, ImageUploadResponse, LogoUploadResponse
from services.file_parser import FileParseError, parse_uploaded_file

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB

_LOGO_BUCKET = "client-logos"
_LOGO_MAX_BYTES = 2 * 1024 * 1024  # 2 MB
# Maps accepted content types to the file extension used for the storage key.
_LOGO_CONTENT_TYPES = {"image/jpeg": "jpg", "image/png": "png"}

# Content images (featured/hero images for published articles + pages) go to the
# public wordpress_images bucket, from which they are sideloaded into the
# client's WordPress media library at publish time.
_IMAGE_BUCKET = "wordpress_images"
_IMAGE_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_IMAGE_CONTENT_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}


@router.post("/files/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    field: str = Form(..., pattern="^(brand_guide|icp|sop)$"),
    auth: dict = Depends(require_auth),
    request: Request = None,
) -> FileUploadResponse:
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    mime_type = file.content_type or ""
    filename = file.filename or "upload"

    logger.info(
        "file_uploaded",
        extra={
            "user_id": auth["user_id"],
            "filename": filename,
            "mime_type": mime_type,
            "size_bytes": len(data),
            "field": field,
        },
    )

    try:
        parsed_text, fmt, truncated = parse_uploaded_file(data, mime_type, filename)
    except FileParseError as exc:
        logger.error(
            "file_parse_failed",
            extra={"upload_filename": filename, "code": exc.code, "error": exc.message},
        )
        if exc.code == "file_too_large":
            raise HTTPException(status_code=413, detail=exc.code)
        if exc.code == "scanned_pdf":
            raise HTTPException(status_code=422, detail=exc.code)
        raise HTTPException(status_code=422, detail=exc.code)

    file_id = uuid.uuid4()
    return FileUploadResponse(
        file_id=file_id,
        original_filename=filename,
        parsed_text=parsed_text,
        truncated=truncated,
        format=fmt,
    )


@router.post("/files/logo", response_model=LogoUploadResponse, status_code=201)
async def upload_logo(
    file: UploadFile = File(...),
    auth: dict = Depends(require_admin),
) -> LogoUploadResponse:
    """Upload a client logo (JPG/PNG) to the public client-logos bucket.

    Returns the public URL, which the caller stores in clients.logo_url.
    Admin-gated to match client create/update.
    """
    content_type = (file.content_type or "").lower()
    ext = _LOGO_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(status_code=422, detail="unsupported_image_type")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty_file")
    if len(data) > _LOGO_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    path = f"{uuid.uuid4()}.{ext}"
    supabase = get_supabase()
    try:
        supabase.storage.from_(_LOGO_BUCKET).upload(
            path,
            data,
            {"content-type": content_type, "upsert": "true"},
        )
        public_url = supabase.storage.from_(_LOGO_BUCKET).get_public_url(path).rstrip("?")
    except Exception as exc:
        logger.error(
            "logo_upload_failed",
            extra={"user_id": auth["user_id"], "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail="logo_upload_failed")

    logger.info(
        "logo_uploaded",
        extra={"user_id": auth["user_id"], "path": path, "size_bytes": len(data)},
    )
    return LogoUploadResponse(logo_url=public_url)


@router.post("/files/image", response_model=ImageUploadResponse, status_code=201)
async def upload_image(
    file: UploadFile = File(...),
    auth: dict = Depends(require_auth),
) -> ImageUploadResponse:
    """Upload a content image (JPG/PNG/WebP/GIF) to the public wordpress_images
    bucket. Returns the public URL, which the caller stores as a run's/page's
    featured image. Auth-gated (any signed-in user) so VAs can attach images."""
    content_type = (file.content_type or "").lower()
    ext = _IMAGE_CONTENT_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(status_code=422, detail="unsupported_image_type")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="empty_file")
    if len(data) > _IMAGE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")

    path = f"{uuid.uuid4()}.{ext}"
    supabase = get_supabase()
    try:
        supabase.storage.from_(_IMAGE_BUCKET).upload(
            path,
            data,
            {"content-type": content_type, "upsert": "true"},
        )
        public_url = supabase.storage.from_(_IMAGE_BUCKET).get_public_url(path).rstrip("?")
    except Exception as exc:
        logger.error(
            "image_upload_failed",
            extra={"user_id": auth["user_id"], "error": str(exc)},
        )
        raise HTTPException(status_code=502, detail="image_upload_failed")

    logger.info(
        "image_uploaded",
        extra={"user_id": auth["user_id"], "path": path, "size_bytes": len(data)},
    )
    return ImageUploadResponse(url=public_url)
