import hashlib
import uuid
from datetime import datetime, timezone
from sqlalchemy import select
from app.tasks.celery_app import celery_app
from app.db.session import SessionLocal
from app.models import Upload, UploadChunk, UploadStatus, FileRecord, DocumentChunk
from app.services.storage import storage
from app.services.extraction import extract_text, split_text
from app.services.vector import vector_service


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def assemble_upload(self, upload_id: str):
    db = SessionLocal()
    multipart_id = None
    final_key = None
    try:
        upload = db.get(Upload, uuid.UUID(upload_id))
        if not upload:
            raise ValueError("upload not found")

        upload.status = UploadStatus.assembling
        upload.last_error = None
        db.commit()

        chunks = list(db.scalars(select(UploadChunk).where(UploadChunk.upload_id == upload.id).order_by(UploadChunk.chunk_number)))
        if len(chunks) != upload.total_chunks:
            raise ValueError(f"expected {upload.total_chunks} chunks, got {len(chunks)}")
        expected_numbers = list(range(upload.total_chunks))
        actual_numbers = [c.chunk_number for c in chunks]
        if actual_numbers != expected_numbers:
            raise ValueError("missing or unordered chunks")

        final_key = f"{upload.tenant_id}/{upload.id}/{upload.original_filename}"
        multipart_id = storage.multipart_start(final_key, upload.content_type)
        parts = []
        sha = hashlib.sha256()

        for idx, chunk in enumerate(chunks, start=1):
            stream = storage.get_chunk_stream(chunk.storage_key)
            body = stream.read()
            sha.update(body)
            etag = storage.multipart_upload_part(final_key, multipart_id, idx, body)
            parts.append({"ETag": etag, "PartNumber": idx})

        storage.multipart_complete(final_key, multipart_id, parts)
        multipart_id = None
        final_checksum = sha.hexdigest()
        if upload.expected_checksum and final_checksum != upload.expected_checksum:
            raise ValueError("final checksum mismatch")

        file_record = FileRecord(
            upload_id=upload.id,
            tenant_id=upload.tenant_id,
            filename=upload.original_filename,
            content_type=upload.content_type,
            size_bytes=upload.file_size,
            checksum=final_checksum,
            storage_key=final_key,
            metadata_json={},
        )
        db.add(file_record)
        upload.storage_key = final_key
        upload.status = UploadStatus.processing
        db.commit()
        db.refresh(file_record)

        process_file.delay(str(file_record.id))
        return {"file_id": str(file_record.id), "checksum": final_checksum}
    except Exception as exc:
        if multipart_id and final_key:
            try:
                storage.multipart_abort(final_key, multipart_id)
            except Exception:
                pass
        upload = db.get(Upload, uuid.UUID(upload_id)) if upload_id else None
        if upload:
            upload.status = UploadStatus.failed
            upload.last_error = str(exc)
            db.commit()
        raise
    finally:
        db.close()


@celery_app.task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_file(self, file_id: str):
    db = SessionLocal()
    try:
        file_record = db.get(FileRecord, uuid.UUID(file_id))
        if not file_record:
            raise ValueError("file not found")
        upload = db.get(Upload, file_record.upload_id)

        if file_record.size_bytes <= 100 * 1024 * 1024:
            data = storage.get_file_bytes(file_record.storage_key)
            text, metadata = extract_text(file_record.filename, file_record.content_type, data)
        else:
            text = ""
            metadata = {"extraction_skipped": "file exceeds 100MB starter extraction limit"}

        file_record.extracted_text = text or None
        file_record.metadata_json = metadata
        file_record.summary = (text[:1000] + "...") if len(text) > 1000 else (text or None)

        for ordinal, content in enumerate(split_text(text)):
            dc = DocumentChunk(file_id=file_record.id, ordinal=ordinal, content=content, metadata_json={"filename": file_record.filename})
            db.add(dc)
            db.flush()
            vector_service.upsert(
                point_id=str(dc.id),
                vector=vector_service.embed_fallback(content),
                payload={"file_id": str(file_record.id), "filename": file_record.filename, "ordinal": ordinal, "content": content},
            )

        if upload:
            upload.status = UploadStatus.completed
            upload.completed_at = datetime.now(timezone.utc)
        db.commit()
        return {"status": "completed", "file_id": file_id}
    except Exception as exc:
        file_record = db.get(FileRecord, uuid.UUID(file_id)) if file_id else None
        if file_record:
            upload = db.get(Upload, file_record.upload_id)
            if upload:
                upload.status = UploadStatus.failed
                upload.last_error = str(exc)
                db.commit()
        raise
    finally:
        db.close()
