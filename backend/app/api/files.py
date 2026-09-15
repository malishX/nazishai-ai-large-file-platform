import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models import FileRecord
from app.schemas.file import FileResponse, SearchRequest, SearchHit
from app.services.storage import storage
from app.services.vector import vector_service

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}", response_model=FileResponse)
def get_file(file_id: uuid.UUID, db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    return FileResponse(
        id=f.id,
        filename=f.filename,
        size_bytes=f.size_bytes,
        content_type=f.content_type,
        checksum=f.checksum,
        summary=f.summary,
        metadata_json=f.metadata_json or {},
    )


@router.get("/{file_id}/download-url")
def download_url(file_id: uuid.UUID, db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    return {"url": storage.presigned_download(f.storage_key)}


@router.post("/{file_id}/search", response_model=list[SearchHit])
def search_file(file_id: uuid.UUID, req: SearchRequest, db: Session = Depends(get_db)):
    f = db.get(FileRecord, file_id)
    if not f:
        raise HTTPException(404, "file not found")
    points = vector_service.search(req.query, req.limit * 3)
    hits = []
    for p in points:
        payload = p.payload or {}
        if payload.get("file_id") == str(file_id):
            hits.append(SearchHit(score=float(p.score), content=payload.get("content", ""), metadata=payload))
        if len(hits) >= req.limit:
            break
    return hits
