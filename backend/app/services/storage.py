"""File storage for original uploads.

Files live under {STORAGE_DIR}/{user_id}/{document_id}/{filename}.
Originals are stored as-is, separated from vector data (Qdrant) and
metadata (PostgreSQL). Swapping this for S3 later only requires
reimplementing these functions.
"""

import hashlib
import shutil
import uuid
from pathlib import Path

from app.core.config import get_settings

settings = get_settings()

CHUNK_SIZE = 1024 * 1024  # 1 MB


class UploadTooLarge(Exception):
    pass


def document_dir(user_id: uuid.UUID, document_id: uuid.UUID) -> Path:
    return Path(settings.storage_dir) / str(user_id) / str(document_id)


def safe_filename(filename: str) -> str:
    """Strip any path components from a client-supplied filename."""
    name = Path(filename).name
    return name or "upload.bin"


def save_upload(
    user_id: uuid.UUID,
    document_id: uuid.UUID,
    filename: str,
    stream,  # file-like, read(size) -> bytes
) -> tuple[Path, str, int]:
    """Stream an upload to disk. Returns (path, sha256_hex, size_bytes).

    Raises UploadTooLarge if the file exceeds the configured limit.
    """
    directory = document_dir(user_id, document_id)
    directory.mkdir(parents=True, exist_ok=True)

    destination = directory / safe_filename(filename)
    hasher = hashlib.sha256()
    size = 0

    try:
        with destination.open("wb") as out:
            while True:
                data = stream.read(CHUNK_SIZE)
                if not data:
                    break
                size += len(data)
                if size > settings.max_upload_size_bytes:
                    raise UploadTooLarge
                hasher.update(data)
                out.write(data)
    except UploadTooLarge:
        shutil.rmtree(directory, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise

    return destination, hasher.hexdigest(), size


def open_document(path: Path):
    return path.open("rb")


def delete_document_files(user_id: uuid.UUID, document_id: uuid.UUID) -> None:
    shutil.rmtree(document_dir(user_id, document_id), ignore_errors=True)
