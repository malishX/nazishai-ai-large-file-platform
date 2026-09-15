import hashlib
import math
import uuid
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import get_db
from app.models import Upload, UploadChunk, IdempotencyKey, UploadStatus
from app.schemas.upload import UploadCreate, UploadResponse, ChunkState, CompleteResponse
from app.services.storage import storage
from app.tasks.upload_tasks import assemble_upload

router = APIRouter(prefix="/uploads", tags=["uploads"])
settings = get_settings()


def to_response(u: Upload) -> UploadResponse:
    return UploadResponse(
        id=u.id,
        filename=u.original_filename,
        file_size=u.file_size,
        chunk_size=u.chunk_size,
        total_chunks=u.total_chunks,
        uploaded_chunks=u.uploaded_chunks,
        status=u.status,
    )


@router.post("", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
def create_upload(
    payload: UploadCreate,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_user_id: str = Header(default="demo-user", alias="X-User-Id"),
    x_tenant_id: str = Header(default="demo-tenant", alias="X-Tenant-Id"),
):
    chunk_size = payload.chunk_size or settings.chunk_size_default
    total_chunks = math.ceil(payload.file_size / chunk_size)
    request_hash = hashlib.sha256(payload.model_dump_json().encode()).hexdigest()

    if idempotency_key:
        existing_key = db.scalar(select(IdempotencyKey).where(IdempotencyKey.user_id == x_user_id, IdempotencyKey.key == idempotency_key))
        if existing_key:
            if existing_key.request_hash != request_hash:
                raise HTTPException(409, "idempotency key reused with different payload")
            existing_upload = db.get(Upload, existing_key.upload_id)
            return to_response(existing_upload)

    upload = Upload(
        user_id=x_user_id,
        tenant_id=x_tenant_id,
        original_filename=payload.filename,
        content_type=payload.content_type,
        file_size=payload.file_size,
        chunk_size=chunk_size,
        total_chunks=total_chunks,
        expected_checksum=payload.expected_checksum,
        status=UploadStatus.created,
    )
    db.add(upload)
    db.flush()

    if idempotency_key:
        db.add(IdempotencyKey(user_id=x_user_id, key=idempotency_key, upload_id=upload.id, request_hash=request_hash))
    db.commit()
    db.refresh(upload)
    return to_response(upload)


@router.get("/{upload_id}", response_model=UploadResponse)
def get_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "upload not found")
    return to_response(upload)


@router.get("/{upload_id}/chunks", response_model=ChunkState)
def get_chunks(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "upload not found")
    completed = list(db.scalars(select(UploadChunk.chunk_number).where(UploadChunk.upload_id == upload_id).order_by(UploadChunk.chunk_number)))
    completed_set = set(completed)
    missing = [i for i in range(upload.total_chunks) if i not in completed_set]
    return ChunkState(completed=completed, missing=missing)


@router.put("/{upload_id}/chunks/{chunk_number}")
async def put_chunk(
    upload_id: uuid.UUID,
    chunk_number: int,
    request: Request,
    db: Session = Depends(get_db),
    x_chunk_checksum: str = Header(alias="X-Chunk-Checksum"),
):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "upload not found")
    if upload.status in {UploadStatus.cancelled, UploadStatus.completed, UploadStatus.failed}:
        raise HTTPException(409, f"upload status is {upload.status}")
    if chunk_number < 0 or chunk_number >= upload.total_chunks:
        raise HTTPException(400, "invalid chunk number")

    existing = db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id, UploadChunk.chunk_number == chunk_number))
    if existing:
        if existing.checksum == x_chunk_checksum:
            return {"status": "already_uploaded", "chunk_number": chunk_number}
        raise HTTPException(409, "chunk already exists with different checksum")

    max_expected = upload.chunk_size
    if chunk_number == upload.total_chunks - 1:
        max_expected = upload.file_size - upload.chunk_size * (upload.total_chunks - 1)

    body = bytearray()
    sha = hashlib.sha256()
    async for part in request.stream():
        body.extend(part)
        sha.update(part)
        if len(body) > max_expected:
            raise HTTPException(413, "chunk too large")

    if len(body) != max_expected:
        raise HTTPException(400, f"unexpected chunk size: expected {max_expected}, got {len(body)}")
    digest = sha.hexdigest()
    if digest != x_chunk_checksum:
        raise HTTPException(400, "checksum mismatch")

    key = f"{upload.tenant_id}/{upload.id}/chunks/{chunk_number:08d}.part"
    storage.put_chunk(key, bytes(body))

    chunk = UploadChunk(upload_id=upload.id, chunk_number=chunk_number, chunk_size=len(body), checksum=digest, storage_key=key)
    db.add(chunk)
    upload.status = UploadStatus.uploading
    upload.uploaded_chunks += 1
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "already_uploaded", "chunk_number": chunk_number}
    return {"status": "uploaded", "chunk_number": chunk_number, "checksum": digest}


@router.post("/{upload_id}/complete", response_model=CompleteResponse, status_code=status.HTTP_202_ACCEPTED)
def complete_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "upload not found")
    count = len(list(db.scalars(select(UploadChunk.id).where(UploadChunk.upload_id == upload_id))))
    if count != upload.total_chunks:
        raise HTTPException(409, f"upload incomplete: {count}/{upload.total_chunks} chunks")
    upload.status = UploadStatus.assembling
    db.commit()
    assemble_upload.delay(str(upload.id))
    return CompleteResponse(upload_id=upload.id, status=upload.status, message="assembly queued")


@router.delete("/{upload_id}")
def cancel_upload(upload_id: uuid.UUID, db: Session = Depends(get_db)):
    upload = db.get(Upload, upload_id)
    if not upload:
        raise HTTPException(404, "upload not found")
    upload.status = UploadStatus.cancelled
    db.commit()
    return {"status": "cancelled"}
