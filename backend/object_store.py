"""Local-first object store with a MinIO/S3-shaped put/get/delete/list API.

Remote MinIO is optional via ``OBJECT_STORE_URI`` plus ``MINIO_ACCESS_KEY`` /
``MINIO_SECRET_KEY`` (or ``AWS_ACCESS_KEY_ID`` / ``AWS_SECRET_ACCESS_KEY``).
Gate G stays incomplete until isolation drills + independent review.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from urllib.parse import urlparse


class ObjectStoreError(RuntimeError):
    pass


class LocalObjectStore:
    """Filesystem-backed artifact store under a root directory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.backend = "local"

    def put(self, key: str, data: bytes) -> dict:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"key": key, "bytes": len(data), "backend": self.backend}

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ObjectStoreError(f"object not found: {key}")
        return path.read_bytes()

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path.is_file():
            path.unlink()
            return True
        return False

    def list_keys(self, prefix: str = "") -> list[str]:
        out = []
        for path in self.root.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self.root).as_posix()
                if not prefix or rel.startswith(prefix):
                    out.append(rel)
        return sorted(out)

    def _path(self, key: str) -> Path:
        clean = (key or "").replace("\\", "/").lstrip("/")
        if not clean or ".." in clean.split("/"):
            raise ObjectStoreError("invalid object key")
        path = (self.root / clean).resolve()
        if not str(path).startswith(str(self.root)):
            raise ObjectStoreError("object key escapes store root")
        return path


class MinioObjectStore:
    """MinIO / S3-compatible object store via the optional ``minio`` package."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str, bucket: str,
                 *, secure: bool = False) -> None:
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("minio package is not installed") from exc
        self.backend = "minio"
        self.bucket = bucket
        host = endpoint.replace("http://", "").replace("https://", "")
        self._client = Minio(host, access_key=access_key, secret_key=secret_key, secure=secure)
        if not self._client.bucket_exists(bucket):
            self._client.make_bucket(bucket)

    def put(self, key: str, data: bytes) -> dict:
        from io import BytesIO
        clean = (key or "").lstrip("/")
        if not clean or ".." in clean.split("/"):
            raise ObjectStoreError("invalid object key")
        self._client.put_object(self.bucket, clean, BytesIO(data), length=len(data))
        return {"key": clean, "bytes": len(data), "backend": self.backend, "bucket": self.bucket}

    def get(self, key: str) -> bytes:
        clean = (key or "").lstrip("/")
        try:
            resp = self._client.get_object(self.bucket, clean)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()
        except Exception as exc:
            raise ObjectStoreError(f"object not found: {clean}") from exc

    def delete(self, key: str) -> bool:
        clean = (key or "").lstrip("/")
        try:
            self._client.remove_object(self.bucket, clean)
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str = "") -> list[str]:
        return sorted(
            obj.object_name
            for obj in self._client.list_objects(self.bucket, prefix=prefix or None, recursive=True)
            if obj.object_name
        )


def _minio_creds() -> tuple[str, str]:
    access = (
        os.getenv("MINIO_ACCESS_KEY")
        or os.getenv("AWS_ACCESS_KEY_ID")
        or os.getenv("MINIO_ROOT_USER")
        or ""
    ).strip()
    secret = (
        os.getenv("MINIO_SECRET_KEY")
        or os.getenv("AWS_SECRET_ACCESS_KEY")
        or os.getenv("MINIO_ROOT_PASSWORD")
        or ""
    ).strip()
    return access, secret


def open_object_store(uri: str | None = None, *, default_root: str | Path = "runs/.object_store") -> dict:
    """Open a store or explain why enterprise object storage is not ready."""
    raw = (uri if uri is not None else os.getenv("OBJECT_STORE_URI") or os.getenv("MINIO_URL") or "").strip()
    if not raw or raw.startswith("file:") or raw.startswith("local:"):
        root = default_root
        if raw.startswith("file:"):
            root = raw[5:] or default_root
        elif raw.startswith("local:"):
            root = raw[6:] or default_root
        store = LocalObjectStore(root)
        return {"ready": True, "backend": "local", "store": store, "reason": ""}
    if raw.startswith(("s3://", "minio://", "http://", "https://")):
        access, secret = _minio_creds()
        if not access or not secret:
            return {
                "ready": False,
                "backend": "remote",
                "store": None,
                "reason": "OBJECT_STORE_URI set but MINIO_ACCESS_KEY/MINIO_SECRET_KEY missing",
                "uri_scheme": raw.split(":", 1)[0],
            }
        parsed = urlparse(raw if "://" in raw else f"http://{raw}")
        # minio://host:port/bucket  or http://host:port/bucket
        host = parsed.netloc or parsed.path.split("/")[0]
        path_parts = [p for p in (parsed.path or "").split("/") if p]
        if parsed.scheme in {"minio", "s3"} and not parsed.netloc:
            # minio://bucket only — invalid without host
            host = "127.0.0.1:9000"
        bucket = path_parts[-1] if path_parts else "qpilot-evidence"
        if parsed.scheme == "minio" and parsed.netloc:
            host = parsed.netloc
            bucket = path_parts[0] if path_parts else "qpilot-evidence"
        secure = parsed.scheme == "https"
        try:
            store = MinioObjectStore(host, access, secret, bucket, secure=secure)
        except Exception as exc:
            return {
                "ready": False,
                "backend": "remote",
                "store": None,
                "reason": f"MinIO open failed: {exc}",
                "uri_scheme": raw.split(":", 1)[0],
            }
        return {"ready": True, "backend": "minio", "store": store, "reason": "", "bucket": bucket}
    return {"ready": False, "backend": "unknown", "store": None,
            "reason": "OBJECT_STORE_URI must be local:, file:, s3://, or minio://"}


def reset_local_store(root: str | Path) -> None:
    """Test helper: remove a local store directory."""
    path = Path(root)
    if path.is_dir():
        shutil.rmtree(path)
