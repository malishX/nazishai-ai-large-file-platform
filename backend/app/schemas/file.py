import uuid
from pydantic import BaseModel


class FileResponse(BaseModel):
    id: uuid.UUID
    filename: str
    size_bytes: int
    content_type: str | None
    checksum: str | None
    summary: str | None
    metadata_json: dict


class SearchRequest(BaseModel):
    query: str
    limit: int = 5


class SearchHit(BaseModel):
    score: float
    content: str
    metadata: dict
