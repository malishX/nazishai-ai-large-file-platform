import io
import boto3
from botocore.exceptions import ClientError
from app.core.config import get_settings

settings = get_settings()


class StorageService:
    def __init__(self):
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
        )
        self.ensure_buckets()

    def ensure_buckets(self):
        for bucket in [settings.s3_bucket_chunks, settings.s3_bucket_files]:
            try:
                self.client.head_bucket(Bucket=bucket)
            except ClientError:
                self.client.create_bucket(Bucket=bucket)

    def put_chunk(self, key: str, body: bytes):
        self.client.put_object(Bucket=settings.s3_bucket_chunks, Key=key, Body=body)

    def get_chunk_stream(self, key: str):
        return self.client.get_object(Bucket=settings.s3_bucket_chunks, Key=key)["Body"]

    def delete_chunk(self, key: str):
        self.client.delete_object(Bucket=settings.s3_bucket_chunks, Key=key)

    def multipart_start(self, key: str, content_type: str | None):
        kwargs = {"Bucket": settings.s3_bucket_files, "Key": key}
        if content_type:
            kwargs["ContentType"] = content_type
        return self.client.create_multipart_upload(**kwargs)["UploadId"]

    def multipart_upload_part(self, key: str, upload_id: str, part_number: int, body):
        return self.client.upload_part(
            Bucket=settings.s3_bucket_files,
            Key=key,
            UploadId=upload_id,
            PartNumber=part_number,
            Body=body,
        )["ETag"]

    def multipart_complete(self, key: str, upload_id: str, parts: list[dict]):
        self.client.complete_multipart_upload(
            Bucket=settings.s3_bucket_files,
            Key=key,
            UploadId=upload_id,
            MultipartUpload={"Parts": parts},
        )

    def multipart_abort(self, key: str, upload_id: str):
        self.client.abort_multipart_upload(Bucket=settings.s3_bucket_files, Key=key, UploadId=upload_id)

    def get_file_bytes(self, key: str) -> bytes:
        return self.client.get_object(Bucket=settings.s3_bucket_files, Key=key)["Body"].read()

    def get_file_stream(self, key: str):
        return self.client.get_object(Bucket=settings.s3_bucket_files, Key=key)["Body"]

    def presigned_download(self, key: str, expires: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.s3_bucket_files, "Key": key},
            ExpiresIn=expires,
        )


storage = StorageService()
