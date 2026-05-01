"""POST /files/upload — file upload and text extraction endpoint."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from middleware.auth import require_auth
from models.files import FileUploadResponse
from services.file_parser import FileParseError, parse_uploaded_file

logger = logging.getLogger(__name__)

router = APIRouter(tags=["files"])

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/files/upload", response_model=FileUploadResponse, status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    field: str = Form(..., pattern="^(brand_guide|icp)$"),
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
            extra={"filename": filename, "code": exc.code, "error": exc.message},
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
