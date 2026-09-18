import logging

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.object_storage_endpoint,
        aws_access_key_id=settings.object_storage_access_key,
        aws_secret_access_key=settings.object_storage_secret_key,
        config=Config(signature_version="s3v4"),
        region_name=settings.object_storage_region,
    )


def ensure_bucket_exists() -> None:
    """
    Idempotent — safe to call on every app startup. SeaweedFS (like S3)
    doesn't auto-create buckets, and unlike some setups there's no
    guaranteed pre-provisioning step, so the app owns this.
    """
    client = get_s3_client()
    try:
        client.head_bucket(Bucket=settings.object_storage_bucket)
    except ClientError:
        client.create_bucket(Bucket=settings.object_storage_bucket)
        logger.info("Created object storage bucket: %s", settings.object_storage_bucket)


def build_storage_key(user_id: str, document_id: str, filename: str) -> str:
    """
    user_id prefix isn't just organizational — it's what makes a future
    per-prefix IAM policy possible if this ever needs stricter isolation
    than "the app always filters by user_id in application code."
    """
    safe_filename = filename.replace("/", "_").replace("\\", "_")
    return f"{user_id}/{document_id}/{safe_filename}"


def upload_file(storage_key: str, file_obj, content_type: str) -> None:
    client = get_s3_client()
    client.put_object(
        Bucket=settings.object_storage_bucket,
        Key=storage_key,
        Body=file_obj,
        ContentType=content_type,
    )


def download_file(storage_key: str) -> bytes:
    """
    Pulls the original uploaded bytes back out of object storage so the
    Phase 2 pipeline can extract from them. The original document is
    always the source of truth (per the normalization-layer separation
    principle) — extraction never mutates or re-derives from anything
    other than this.
    """
    client = get_s3_client()
    response = client.get_object(Bucket=settings.object_storage_bucket, Key=storage_key)
    return response["Body"].read()


def delete_file(storage_key: str) -> None:
    client = get_s3_client()
    client.delete_object(Bucket=settings.object_storage_bucket, Key=storage_key)


def generate_download_url(storage_key: str, expires_in_seconds: int = 300) -> str:
    client = get_s3_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.object_storage_bucket, "Key": storage_key},
        ExpiresIn=expires_in_seconds,
    )
