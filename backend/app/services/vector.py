import hashlib
import math
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from app.core.config import get_settings

settings = get_settings()


class VectorService:
    def __init__(self):
        self.client = QdrantClient(url=settings.qdrant_url)
        self.size = 256
        self.ensure_collection()

    def ensure_collection(self):
        existing = {c.name for c in self.client.get_collections().collections}
        if settings.qdrant_collection not in existing:
            self.client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=VectorParams(size=self.size, distance=Distance.COSINE),
            )

    def embed_fallback(self, text: str) -> list[float]:
        vec = [0.0] * self.size
        for token in text.lower().split():
            h = hashlib.sha256(token.encode()).digest()
            idx = int.from_bytes(h[:2], "big") % self.size
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def upsert(self, point_id: str, vector: list[float], payload: dict):
        self.client.upsert(
            collection_name=settings.qdrant_collection,
            points=[PointStruct(id=point_id, vector=vector, payload=payload)],
        )

    def search(self, query: str, limit: int = 5):
        vector = self.embed_fallback(query)
        result = self.client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=limit,
            with_payload=True,
        )
        return result.points


vector_service = VectorService()
