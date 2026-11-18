"""Local-first object store with a MinIO/S3-shaped put/get/delete/list API.

Remote MinIO is optional via ``OBJECT_STORE_URI``. Until a remote client is
wired, a remote URI reports configured-but-unready instead of pretending
uploads succeeded.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path


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


def open_object_store(uri: str | None = None, *, default_root: str | Path = "runs/.object_store") -> dict:
    """Open a store or explain why enterprise object storage is not ready."""
    raw = (uri if uri is not None else os.getenv("OBJECT_STORE_URI", "")).strip()
    if not raw or raw.startswith("file:") or raw.startswith("local:"):
        root = default_root
        if raw.startswith("file:"):
            root = raw[5:] or default_root
        elif raw.startswith("local:"):
            root = raw[6:] or default_root
        store = LocalObjectStore(root)
        return {"ready": True, "backend": "local", "store": store, "reason": ""}
    if raw.startswith(("s3://", "minio://", "http://", "https://")):
        return {
            "ready": False,
            "backend": "remote",
            "store": None,
            "reason": "remote object storage URI is set but the MinIO/S3 client is not wired yet",
            "uri_scheme": raw.split(":", 1)[0],
        }
    return {"ready": False, "backend": "unknown", "store": None,
            "reason": "OBJECT_STORE_URI must be local:, file:, s3://, or minio://"}


def reset_local_store(root: str | Path) -> None:
    """Test helper: remove a local store directory."""
    path = Path(root)
    if path.is_dir():
        shutil.rmtree(path)
