# NazishAI AI-Enhanced Large File Transfer Platform

Production-oriented reference implementation for resumable, chunked large-file upload, background assembly, metadata extraction, embeddings/vector search, and chat/search over uploaded files.

This repository implements the architecture from the NazishAI 6-slide design:
- Client-side chunking with resume/retry/progress
- Upload/control plane with idempotency and persistent state
- Data plane with chunk validation, queue workers, assembly, object storage
- Reliability/observability hooks
- AI processing pipeline and vector search

## Stack
- FastAPI
- PostgreSQL
- Redis + Celery
- MinIO (S3-compatible)
- Qdrant
- React + Vite
- Docker Compose

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

Then open:
- Web UI: http://localhost:5173
- API docs: http://localhost:8000/docs
- MinIO console: http://localhost:9001
- Qdrant: http://localhost:6333/dashboard

Default MinIO credentials in `.env.example` are for local development only.

## Main API flow

1. `POST /api/v1/uploads` creates an upload session.
2. Client splits file into chunks and calls `PUT /api/v1/uploads/{upload_id}/chunks/{chunk_number}`.
3. Each chunk is SHA-256 checked and stored in MinIO.
4. `POST /api/v1/uploads/{upload_id}/complete` verifies all chunks exist and queues assembly.
5. Celery assembles the file by streaming chunks into a multipart upload to MinIO.
6. AI processing extracts text/metadata, creates vector chunks, and indexes them in Qdrant.
7. `POST /api/v1/files/{file_id}/search` runs semantic search.

## Security notes

The sample includes tenant/user fields and request validation but intentionally leaves enterprise identity integration pluggable. Before production, connect OIDC/SSO, enforce RBAC, enable WAF/rate limits, rotate secrets, use TLS, configure malware scanning, and deploy managed PostgreSQL/Redis/object storage.

## Scaling notes

The reference app keeps chunk files directly in object storage and never loads the completed file into application memory. Chunk assembly is streamed. For very high scale, move upload paths to direct signed multipart upload URLs and use Kafka/SQS/RabbitMQ as your durable event bus.
