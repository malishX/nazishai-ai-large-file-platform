import math
import uuid
from pydantic import BaseModel, Field, model_validator
from app.core.config import get_settings
from app.models.upload import UploadStatus

settings = get_settings()


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=1024)
    file_size: int = Field(gt=0)
    content_type: str | None = None
    chunk_size: int | None = None
    expected_checksum: str | None = None

    @model_validator(mode="after")
    def validate_size(self):
        if self.file_size > settings.max_file_size:
            raise ValueError("file exceeds configured maximum")
        if self.chunk_size is not None and self.chunk_size > settings.chunk_size_max:
            raise ValueError("chunk size exceeds configured maximum")
        return self


class UploadResponse(BaseModel):
    id: uuid.UUID
    filename: str
    file_size: int
    chunk_size: int
    total_chunks: int
    uploaded_chunks: int
    status: UploadStatus


class ChunkState(BaseModel):
    completed: list[int]
    missing: list[int]


class CompleteResponse(BaseModel):
    upload_id: uuid.UUID
    status: UploadStatus
    message: str
