"""Local-filesystem object storage, behind an S3-shaped interface.

This originally wrapped MinIO, but MinIO's container image is no longer
freely pullable from Docker Hub or Quay.io (confirmed as of 2026-10-21 — both
deny every tag, including `latest`), so there's no way to run it locally
right now. Buckets become subdirectories under `app_config.OBJECT_STORAGE_DIR`.

The function signatures (`ensure_bucket`/`upload_bytes`/`get_bytes`/`delete_prefix`) are kept
S3-shaped on purpose — swapping back to a real object store later (MinIO,
S3, etc.) only needs a new implementation of these functions, not a
rewrite of the callers.
"""

import asyncio
import shutil
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


def _delete_prefix_sync(bucket: str, prefix: str) -> None:
    # Prefixes are "folder" names (e.g. a site id), never paths that leave the bucket.
    if not prefix or "/" in prefix or prefix in (".", ".."):
        raise ValueError(f"Invalid prefix: {prefix!r}")
    shutil.rmtree(_bucket_dir(bucket) / prefix, ignore_errors=True)


async def delete_prefix(bucket: str, prefix: str) -> None:
    """Delete every object under `prefix/`. Missing prefixes are fine."""
    await asyncio.to_thread(_delete_prefix_sync, bucket, prefix)
