"""Local-filesystem object storage, behind an S3-shaped interface.

This originally wrapped MinIO, but MinIO's container image is no longer
freely pullable from Docker Hub or Quay.io (confirmed as of 2026-10-21 — both
deny every tag, including `latest`), so there's no way to run it locally
right now. Buckets become subdirectories under `app_config.OBJECT_STORAGE_DIR`.

The function signatures (`ensure_bucket`/`upload_bytes`/`get_bytes`) are kept
S3-shaped on purpose — swapping back to a real object store later (MinIO,
S3, etc.) only needs a new implementation of these three functions, not a
rewrite of the callers.
"""

import asyncio
from pathlib import Path

from app.core.config.app_config import app_config


def _bucket_dir(bucket: str) -> Path:
    return Path(app_config.OBJECT_STORAGE_DIR) / bucket


def _ensure_bucket_sync(bucket: str) -> None:
    _bucket_dir(bucket).mkdir(parents=True, exist_ok=True)


async def ensure_bucket(bucket: str) -> None:
    await asyncio.to_thread(_ensure_bucket_sync, bucket)


def _upload_bytes_sync(bucket: str, object_name: str, data: bytes, content_type: str) -> None:
    path = _bucket_dir(bucket) / object_name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


async def upload_bytes(bucket: str, object_name: str, data: bytes, content_type: str) -> None:
    await asyncio.to_thread(_upload_bytes_sync, bucket, object_name, data, content_type)


def _get_bytes_sync(bucket: str, object_name: str) -> bytes:
    return (_bucket_dir(bucket) / object_name).read_bytes()


async def get_bytes(bucket: str, object_name: str) -> bytes:
    return await asyncio.to_thread(_get_bytes_sync, bucket, object_name)
