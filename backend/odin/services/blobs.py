"""S3-compatible blob store client: content-addressed originals (AWS creds via env)."""

import asyncio
import hashlib
from functools import lru_cache
from typing import Any

import boto3
from botocore.exceptions import ClientError

from odin.config import get_settings
from odin.errors import NotFoundError

_bucket_ready = False


@lru_cache
def _client() -> Any:
    settings = get_settings()
    return boto3.client("s3", endpoint_url=settings.s3_endpoint_url, region_name=settings.s3_region)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _uri(key: str) -> str:
    return f"s3://{get_settings().s3_bucket}/{key}"


def _key(uri: str) -> str:
    prefix = f"s3://{get_settings().s3_bucket}/"
    return uri[len(prefix) :] if uri.startswith(prefix) else uri


def _ensure_bucket() -> None:
    global _bucket_ready
    if _bucket_ready:
        return
    try:
        _client().create_bucket(Bucket=get_settings().s3_bucket)
    except ClientError:
        pass
    _bucket_ready = True


def _put_sync(data: bytes) -> str:
    _ensure_bucket()
    bucket = get_settings().s3_bucket
    key = content_hash(data)
    try:
        _client().head_object(Bucket=bucket, Key=key)
    except ClientError:
        _client().put_object(Bucket=bucket, Key=key, Body=data)
    return _uri(key)


def _get_sync(uri: str) -> bytes:
    try:
        resp = _client().get_object(Bucket=get_settings().s3_bucket, Key=_key(uri))
    except ClientError as e:
        raise NotFoundError(f"blob not found: {uri}") from e
    body: bytes = resp["Body"].read()
    return body


def _exists_sync(uri: str) -> bool:
    try:
        _client().head_object(Bucket=get_settings().s3_bucket, Key=_key(uri))
    except ClientError:
        return False
    return True


async def put(data: bytes) -> str:
    return await asyncio.to_thread(_put_sync, data)


async def get(uri: str) -> bytes:
    return await asyncio.to_thread(_get_sync, uri)


async def exists(uri: str) -> bool:
    return await asyncio.to_thread(_exists_sync, uri)
