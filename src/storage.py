"""
MoAudit MEL - Storage Backend
=============================
Abstraction layer for file storage supporting local, S3, and Scaleway Object Storage.
"""

import os
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, List, Dict, Any, Union
from datetime import datetime
import mimetypes

from .config import config, load_config_from_env

# Load configuration
load_config_from_env()


class StorageBackend(ABC):
    """Abstract base class for storage backends"""

    @abstractmethod
    def upload(self, source: Union[str, bytes, BinaryIO], destination: str, **kwargs) -> str:
        """
        Upload a file to storage.

        Args:
            source: Local file path, bytes, or file-like object
            destination: Destination key/path
            **kwargs: Additional options (content_type, metadata, etc.)

        Returns:
            The final storage path/URL
        """
        pass

    @abstractmethod
    def download(self, source: str, destination: str) -> str:
        """
        Download a file from storage.

        Args:
            source: Storage key/path
            destination: Local destination path

        Returns:
            Local file path
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> bool:
        """
        Delete a file from storage.

        Args:
            path: Storage key/path

        Returns:
            True if deleted, False otherwise
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            path: Storage key/path

        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    def list_files(self, prefix: str = "", **kwargs) -> List[Dict[str, Any]]:
        """
        List files in storage.

        Args:
            prefix: Path prefix to filter by
            **kwargs: Additional options (limit, delimiter, etc.)

        Returns:
            List of file metadata dicts
        """
        pass

    @abstractmethod
    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """
        Get a (signed) URL for a file.

        Args:
            path: Storage key/path
            expires_in: URL expiration in seconds (for signed URLs)

        Returns:
            URL string
        """
        pass

    def get_content_type(self, filename: str) -> str:
        """Determine content type from filename"""
        content_type, _ = mimetypes.guess_type(filename)
        return content_type or "application/octet-stream"


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend"""

    def __init__(self, base_path: Optional[str] = None):
        self.base_path = Path(base_path or config.storage.local_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, path: str) -> Path:
        """Resolve a path relative to base path, preventing path traversal"""
        # Remove leading slashes and normalize
        clean_path = path.lstrip("/").replace("..", "")
        full_path = self.base_path / clean_path

        # Ensure path is within base_path
        try:
            full_path.resolve().relative_to(self.base_path.resolve())
        except ValueError:
            raise ValueError(f"Path traversal attempt detected: {path}")

        return full_path

    def upload(self, source: Union[str, bytes, BinaryIO], destination: str, **kwargs) -> str:
        """Upload file to local storage"""
        dest_path = self._resolve_path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        if isinstance(source, bytes):
            dest_path.write_bytes(source)
        elif isinstance(source, str):
            if os.path.isfile(source):
                shutil.copy2(source, dest_path)
            else:
                dest_path.write_text(source)
        else:
            # File-like object
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(source, f)

        return str(dest_path)

    def download(self, source: str, destination: str) -> str:
        """Download file from local storage"""
        source_path = self._resolve_path(source)

        if not source_path.exists():
            raise FileNotFoundError(f"File not found: {source}")

        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, dest_path)

        return str(dest_path)

    def delete(self, path: str) -> bool:
        """Delete file from local storage"""
        file_path = self._resolve_path(path)

        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def exists(self, path: str) -> bool:
        """Check if file exists in local storage"""
        return self._resolve_path(path).exists()

    def list_files(self, prefix: str = "", **kwargs) -> List[Dict[str, Any]]:
        """List files in local storage"""
        limit = kwargs.get("limit", 1000)

        search_path = self._resolve_path(prefix) if prefix else self.base_path
        files = []

        if search_path.is_file():
            files = [search_path]
        elif search_path.exists():
            files = list(search_path.rglob("*"))[:limit]

        result = []
        for f in files:
            if f.is_file():
                stat = f.stat()
                result.append({
                    "key": str(f.relative_to(self.base_path)),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    "content_type": self.get_content_type(f.name),
                })

        return result

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get local file path as URL"""
        file_path = self._resolve_path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return f"file://{file_path.absolute()}"

    def read_bytes(self, path: str) -> bytes:
        """Read file contents as bytes"""
        return self._resolve_path(path).read_bytes()

    def read_text(self, path: str, encoding: str = "utf-8") -> str:
        """Read file contents as text"""
        return self._resolve_path(path).read_text(encoding=encoding)


class S3StorageBackend(StorageBackend):
    """S3-compatible storage backend (AWS S3, Scaleway Object Storage, MinIO, etc.)"""

    def __init__(
        self,
        endpoint_url: Optional[str] = None,
        access_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        bucket_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self.endpoint_url = endpoint_url or config.storage.s3_endpoint_url
        self.access_key = access_key or config.storage.s3_access_key
        self.secret_key = secret_key or config.storage.s3_secret_key
        self.bucket_name = bucket_name or config.storage.s3_bucket_name
        self.region = region or config.storage.s3_region

        self._client = None
        self._resource = None

    @property
    def client(self):
        """Lazy-load boto3 client"""
        if self._client is None:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url if self.endpoint_url else None,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._client

    @property
    def resource(self):
        """Lazy-load boto3 resource"""
        if self._resource is None:
            import boto3

            self._resource = boto3.resource(
                "s3",
                endpoint_url=self.endpoint_url if self.endpoint_url else None,
                aws_access_key_id=self.access_key,
                aws_secret_access_key=self.secret_key,
                region_name=self.region,
            )
        return self._resource

    def upload(self, source: Union[str, bytes, BinaryIO], destination: str, **kwargs) -> str:
        """Upload file to S3"""
        content_type = kwargs.get("content_type") or self.get_content_type(destination)
        metadata = kwargs.get("metadata", {})

        extra_args = {
            "ContentType": content_type,
            "Metadata": metadata,
        }

        if isinstance(source, bytes):
            self.client.put_object(
                Bucket=self.bucket_name,
                Key=destination,
                Body=source,
                **extra_args
            )
        elif isinstance(source, str) and os.path.isfile(source):
            self.client.upload_file(
                source,
                self.bucket_name,
                destination,
                ExtraArgs=extra_args
            )
        else:
            # File-like object
            self.client.upload_fileobj(
                source,
                self.bucket_name,
                destination,
                ExtraArgs=extra_args
            )

        return f"s3://{self.bucket_name}/{destination}"

    def download(self, source: str, destination: str) -> str:
        """Download file from S3"""
        # Handle s3:// prefix
        key = source
        if source.startswith("s3://"):
            parts = source[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)

        self.client.download_file(
            self.bucket_name,
            key,
            str(dest_path)
        )

        return str(dest_path)

    def delete(self, path: str) -> bool:
        """Delete file from S3"""
        key = path
        if path.startswith("s3://"):
            parts = path[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        try:
            self.client.delete_object(
                Bucket=self.bucket_name,
                Key=key
            )
            return True
        except Exception:
            return False

    def exists(self, path: str) -> bool:
        """Check if file exists in S3"""
        key = path
        if path.startswith("s3://"):
            parts = path[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        try:
            self.client.head_object(Bucket=self.bucket_name, Key=key)
            return True
        except Exception:
            return False

    def list_files(self, prefix: str = "", **kwargs) -> List[Dict[str, Any]]:
        """List files in S3"""
        limit = kwargs.get("limit", 1000)
        delimiter = kwargs.get("delimiter", "")

        paginator = self.client.get_paginator("list_objects_v2")

        params = {
            "Bucket": self.bucket_name,
            "Prefix": prefix,
            "MaxKeys": limit,
        }
        if delimiter:
            params["Delimiter"] = delimiter

        result = []
        for page in paginator.paginate(**params):
            for obj in page.get("Contents", []):
                result.append({
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "modified": obj["LastModified"].isoformat(),
                    "etag": obj.get("ETag", "").strip('"'),
                })
                if len(result) >= limit:
                    return result

        return result

    def get_url(self, path: str, expires_in: int = 3600) -> str:
        """Get a pre-signed URL for S3 object"""
        key = path
        if path.startswith("s3://"):
            parts = path[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        url = self.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket_name,
                "Key": key
            },
            ExpiresIn=expires_in
        )

        return url

    def read_bytes(self, path: str) -> bytes:
        """Read file contents as bytes from S3"""
        key = path
        if path.startswith("s3://"):
            parts = path[5:].split("/", 1)
            if len(parts) == 2:
                key = parts[1]

        response = self.client.get_object(Bucket=self.bucket_name, Key=key)
        return response["Body"].read()

    def create_bucket(self, bucket_name: Optional[str] = None) -> bool:
        """Create a bucket if it doesn't exist"""
        bucket = bucket_name or self.bucket_name

        try:
            if self.region and self.region != "us-east-1":
                self.client.create_bucket(
                    Bucket=bucket,
                    CreateBucketConfiguration={"LocationConstraint": self.region}
                )
            else:
                self.client.create_bucket(Bucket=bucket)
            return True
        except self.client.exceptions.BucketAlreadyOwnedByYou:
            return True
        except self.client.exceptions.BucketAlreadyExists:
            return True
        except Exception:
            return False


# Factory function
_storage_instance: Optional[StorageBackend] = None


def get_storage_backend(backend: Optional[str] = None) -> StorageBackend:
    """
    Get storage backend instance (singleton).

    Args:
        backend: Override backend type (local, s3, scaleway)

    Returns:
        StorageBackend instance
    """
    global _storage_instance

    backend_type = backend or config.storage.backend

    # Return cached instance if same backend
    if _storage_instance is not None:
        if backend_type == "local" and isinstance(_storage_instance, LocalStorageBackend):
            return _storage_instance
        if backend_type in ("s3", "scaleway") and isinstance(_storage_instance, S3StorageBackend):
            return _storage_instance

    # Create new instance
    if backend_type == "local":
        _storage_instance = LocalStorageBackend()
    elif backend_type in ("s3", "scaleway"):
        _storage_instance = S3StorageBackend()
    else:
        # Default to local
        _storage_instance = LocalStorageBackend()

    return _storage_instance


def reset_storage_backend():
    """Reset the storage backend singleton (useful for testing)"""
    global _storage_instance
    _storage_instance = None


# Convenience functions
def upload_file(source: Union[str, bytes, BinaryIO], destination: str, **kwargs) -> str:
    """Upload a file using the configured storage backend"""
    return get_storage_backend().upload(source, destination, **kwargs)


def download_file(source: str, destination: str) -> str:
    """Download a file using the configured storage backend"""
    return get_storage_backend().download(source, destination)


def delete_file(path: str) -> bool:
    """Delete a file using the configured storage backend"""
    return get_storage_backend().delete(path)


def file_exists(path: str) -> bool:
    """Check if a file exists using the configured storage backend"""
    return get_storage_backend().exists(path)


def list_files(prefix: str = "", **kwargs) -> List[Dict[str, Any]]:
    """List files using the configured storage backend"""
    return get_storage_backend().list_files(prefix, **kwargs)


def get_file_url(path: str, expires_in: int = 3600) -> str:
    """Get a URL for a file using the configured storage backend"""
    return get_storage_backend().get_url(path, expires_in)
