"""
Storage abstraction layer.

One interface (Storage), two backends:
  - LocalStorage: pathlib-backed, for dev. presign() returns a Flask route URL.
  - S3Storage:    boto3-backed, for prod. presign() returns a real signed URL.

Selected at startup by make_storage():
  STORAGE_BACKEND env var ("local" | "s3") is the primary switch.
  If unset, infer from whether S3_BUCKET + AWS creds are present.
  If "s3" is requested but config is missing, raise loudly (don't degrade).

KEY CONVENTION
--------------
Everything is addressed by a string `key`, never a Path. "/" is just a
character. Example keys:
    <user_id>/reports/Job_Listing_Brief_2026-06-03.pdf
    <user_id>/crawler/<filename>
LocalStorage interprets a key as a path relative to its base_dir.
S3Storage uses the key verbatim as the object key.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
import mimetypes
import logging
import asyncio

logger = logging.getLogger(__name__)

PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent

class Storage(ABC):
    """Contract every backend must satisfy. Speak in string keys + bytes."""

    @abstractmethod
    async def save(self, key: str, data: bytes) -> None:
        """Write `data` at `key`, overwriting if it exists."""
        ...

    @abstractmethod
    async def read(self, key: str) -> bytes:
        """Return the bytes stored at `key`. Raise if missing."""
        ...

    @abstractmethod
    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """Return the text stored at `key`. Raise if missing."""
        ...

    @abstractmethod
    async def save_text(self, key: str, text: str, encoding: str = "utf-8") -> None:
        """Write `data` at `key`, overwriting if it exists."""
        ...

    @abstractmethod
    async def list(self, prefix: str, check_child_dir: bool = False) -> list[str]:
        """Return all keys beginning with `prefix`. Empty list if none."""
        ...

    @abstractmethod
    async def presign(self, key: str, filename: str, run_id: int, expires_in: int = 3600) -> str:
        """Return a URL the browser can use to download `key`."""
        ...


class LocalStorage(Storage):
    """Dev backend. Keys map to files under base_dir."""

    def __init__(self, base_dir: Path | str):
        self.base_dir = Path(base_dir)

    def _path(self, key: str) -> Path:
        return self.base_dir / key

    async def save(self, key: str, data: bytes) -> None:
        """
        PLEASE REMEMBER TO ENCODE YOUR DATA\n
        It will parse the key into a path object, and store the data in that path\n
        Input: 
            `key` -> the path to a file as a string
            `data` -> the raw encoded `bytes` to be stored
        Output:
            `None`
        """
        def _do():
            path = self._path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        await asyncio.to_thread(_do)

    async def read(self, key: str) -> bytes:
        """
        PLEASE REMEMBER TO DECODE THE RETURN DATA\n
        It will parse the key into a path object, and read the file from that path as `bytes`\n
        Input: 
            `key` -> the path to a file as a string
        Output:
            `Bytes` -> the file content read as bytes, must be decoded before used
        """
        def _do():
            path = self._path(key)
            try:
                return path.read_bytes()
            except FileNotFoundError:
                raise FileNotFoundError(f"❌ File: {path} NOT FOUND")
        return await asyncio.to_thread(_do)

    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """
        Reads text without having to decode\n
        It will parse the key into a path object, and read the file from that path as `string`\n
        Input: 
            `key` -> the path to a file as a string
        Output:
            `string` -> the string stored in said file
        """
        data = await self.read(key)
        return data.decode(encoding)

    async def save_text(self, key: str, text: str, encoding: str = "utf-8") -> None:
        await self.save(key, text.encode(encoding))

    async def list(self, prefix: str, check_child_dir : bool = False) -> list[str]:
        """
        It will first check if `prefix` EXISTS and IS A DIRECTORY
        Then it will list all its content as a list of string\n
        Can be set to check child directories, `False` by default\n
        Input:
            `prefix` -> the path to the target directory as a string
            `check_child_dir` -> check child directories toggle, default `False`
        Output:
            `list[str]` -> the list of paths to files inside `key` relative to `base_dir`
        """
        def _do():
            out_list = []

            directory_path = self._path(prefix)
            if not (directory_path.exists() and directory_path.is_dir()):
                return []

            if check_child_dir:
                list_of_file_paths = directory_path.rglob("*")
            else:
                list_of_file_paths = directory_path.iterdir()

            for path_obj in list_of_file_paths:
                if path_obj.is_file():
                    out_list.append(str(path_obj.relative_to(self.base_dir)))

            return out_list

        return await asyncio.to_thread(_do)

    async def presign(self, key: str, filename: str, run_id: int, expires_in: int = 3600) -> str:
        """
        Returns a URL the browser can use to download the file at `key`.

        Dev backend: there is no S3 to sign against, so this returns the
        Django `download_report` route URL instead, giving the same
        navigate-to-download behaviour as the S3 signed URL in prod.

        `filename` and `expires_in` are unused locally — the route looks the
        row up by `run_id` and derives the filename itself.

        Input:
            `key` -> the storage key of the file to download
            `filename` -> unused in local backend
            `run_id` -> the Report_runs row id to download
            `expires_in` -> ignored in local backend

        Output:
            `str` -> a Django route URL pointing at `download_report`
        """
        from django.urls import reverse
        return reverse("download_report", kwargs={"run_id": run_id})


class S3Storage(Storage):
    """Prod backend. Keys are S3 object keys verbatim."""

    def __init__(self, bucket: str, client=None):
        self.bucket = bucket
        # boto3 resolves creds from env/role automatically -- never pass keys.
        if client is None:
            import boto3
            client = boto3.client("s3")
        self.client = client

    async def save(self, key: str, data: bytes) -> None:
        """
        PLEASE REMEMBER TO ENCODE YOUR DATA\n
        It will parse the key into a path object, and store the data in that path\n
        Input: 
            `key` -> the path to a file as a string
            `data` -> the raw encoded `bytes` to be stored
        Output:
            `None`
        """
        content_type, encoding = mimetypes.guess_type(key)
        kwargs = {
            "Bucket" : self.bucket,
            "Key" : key,
            "Body" : data
        }

        if content_type is not None:
            kwargs["ContentType"] = content_type
        
        await asyncio.to_thread(self.client.put_object, **kwargs)

    async def read(self, key: str) -> bytes:
        """
        PLEASE REMEMBER TO DECODE THE RETURN DATA\n
        It will parse the key into a path object, and read the file from that path as `bytes`\n
        Input: 
            `key` -> the path to a file as a string
        Output:
            `Bytes` -> the file content read as bytes, must be decoded before used
        """
        resp = await asyncio.to_thread(self.client.get_object, Bucket=self.bucket, Key=key)

        return await asyncio.to_thread(resp["Body"].read)

    async def read_text(self, key: str, encoding: str = "utf-8") -> str:
        """
        Reads text without having to decode\n
        It will parse the key into a path object, and read the file from that path as `string`\n
        Input: 
            `key` -> the path to a file as a string
        Output:
            `string` -> the string stored in said file
        """
        data = await self.read(key)
        return data.decode(encoding)

    async def save_text(self, key: str, text: str, encoding: str = "utf-8") -> None:
        await self.save(key, text.encode(encoding))

    async def list(self, prefix: str, check_child_dir: bool = False) -> list[str]:
        """
        It will list all its content as a list of string\n
        Can be set to check child directories, `False` by default\n
        Input: 
            `prefix` -> the path to the target directory as a string
            `check_child_dir` -> check child directories toggle, default `False` 
        Output:
            `list[str]` -> the list of paths to files inside `key` relative to `base_dir`
        """
        def _do():
            keys = []
            paginator = self.client.get_paginator("list_objects_v2")
            kwargs = {"Bucket": self.bucket, "Prefix": prefix}
            if not check_child_dir:
                kwargs["Delimiter"] = "/"          # one level: stop at each "/"
            for page in paginator.paginate(**kwargs):
                keys.extend(obj["Key"] for obj in page.get("Contents", []))
            return keys

        return await asyncio.to_thread(_do)

    async def presign(self, key: str, filename: str, run_id: int, expires_in: int = 3600) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, 
                    "Key": key, 
                    "ResponseContentDisposition": f'attachment; filename="{filename}"'},
            ExpiresIn=expires_in,
        )
    
def get_user_subdirectory(user_id : int) -> Path:
    """
    Returns Path to users' subdirectory: ROOT/File_Output/<user_id>
    """
    return PROJECT_ROOT_DIR / "File_Outputs" / str(user_id)

def make_storage() -> Storage:
    """
    Factory. Explicit STORAGE_BACKEND wins; otherwise infer.

    Resolution order:
      1. STORAGE_BACKEND == "local"  -> LocalStorage
      2. STORAGE_BACKEND == "s3"     -> S3Storage (error if bucket missing)
      3. unset                       -> infer: bucket present -> s3, else local
    """
    logger.info("🏁 Start making storage_obj...")
    backend = os.getenv("STORAGE_BACKEND", "").strip().lower()
    bucket = os.getenv("S3_BUCKET")

    logger.info("🟢 backend: %s, bucket: %s", backend, bucket)

    local_base = PROJECT_ROOT_DIR / "File_Outputs"

    if backend == "local":
        logger.warning("⚠️ USING LOCAL STORAGE BACKEND")
        return LocalStorage(local_base)

    if backend == "s3":
        logger.info("⚠️ USING S3 AS STORAGE BACKEND")
        if not bucket:
            raise RuntimeError(
                "STORAGE_BACKEND=s3 but S3_BUCKET is not set."
            )
        return S3Storage(bucket)

    # backend unset -> infer
    if bucket:
        return S3Storage(bucket)
    return LocalStorage(local_base)


if __name__ == "__main__":
    storage_obj : Storage = make_storage()
    print(storage_obj._path("abc"))