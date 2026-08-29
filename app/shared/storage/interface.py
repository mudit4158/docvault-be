from abc import ABC, abstractmethod

from app.config import settings


class StorageBackend(ABC):
    """Abstract file storage interface.

    The PRD requires the storage layer to support a future move to peer-to-peer
    storage (§5 NFR). All file I/O goes through this interface so the backend
    can be swapped without touching business logic.
    """

    @abstractmethod
    async def put(self, key: str, data: bytes, content_type: str) -> str:
        """Store bytes under `key`. Returns the storage key."""

    @abstractmethod
    async def get(self, key: str) -> bytes:
        """Retrieve bytes for `key`."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Permanently remove the file at `key`."""

    @abstractmethod
    async def presigned_url(self, key: str, expires_in: int = 300) -> str:
        """Return a time-limited URL for direct client download."""


class LocalStorage(StorageBackend):
    """Dev-only local filesystem storage."""

    def __init__(self, base_path: str) -> None:
        import os
        self.base_path = base_path
        os.makedirs(base_path, exist_ok=True)

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        import os
        path = os.path.join(self.base_path, key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return key

    async def get(self, key: str) -> bytes:
        import os
        with open(os.path.join(self.base_path, key), "rb") as f:
            return f.read()

    async def delete(self, key: str) -> None:
        import os
        path = os.path.join(self.base_path, key)
        if os.path.exists(path):
            os.remove(path)

    async def presigned_url(self, key: str, expires_in: int = 300) -> str:
        # Local dev: return a direct API download URL instead
        return f"/api/v1/documents/download-by-key/{key}"


class S3Storage(StorageBackend):
    """Production S3-compatible storage."""

    def __init__(self) -> None:
        import boto3
        self._client = boto3.client(
            "s3",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        self._bucket = settings.aws_bucket_name

    async def put(self, key: str, data: bytes, content_type: str) -> str:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)
        return key

    async def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    async def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    async def presigned_url(self, key: str, expires_in: int = 300) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )


def get_storage() -> StorageBackend:
    if settings.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(settings.local_storage_path)
