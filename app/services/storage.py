import uuid

import boto3
from botocore.config import Config
from fastapi import UploadFile

from app.core.config import get_settings

settings = get_settings()

s3_client = boto3.client(
    "s3",
    endpoint_url=settings.S3_ENDPOINT,
    aws_access_key_id=settings.S3_ACCESS_KEY,
    aws_secret_access_key=settings.S3_SECRET_KEY,
    config=Config(signature_version="s3v4"),
    region_name="us-east-1",
)


def ensure_bucket(bucket_name: str):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
    except Exception:
        s3_client.create_bucket(Bucket=bucket_name)


async def upload_file(file: UploadFile, bucket: str, prefix: str = "") -> str:
    ensure_bucket(bucket)
    ext = file.filename.rsplit(".", 1)[-1] if file.filename else "bin"
    key = f"{prefix}/{uuid.uuid4()}.{ext}" if prefix else f"{uuid.uuid4()}.{ext}"
    content = await file.read()
    s3_client.put_object(Bucket=bucket, Key=key, Body=content, ContentType=file.content_type)
    return f"{bucket}/{key}"


def download_file(bucket: str, key: str) -> bytes:
    response = s3_client.get_object(Bucket=bucket, Key=key)
    return response["Body"].read()


def delete_file(file_path: str):
    parts = file_path.split("/", 1)
    if len(parts) == 2:
        s3_client.delete_object(Bucket=parts[0], Key=parts[1])
