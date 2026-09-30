"""Receipt / invoice file storage on local disk.

Files are stored under random names; the original filename is kept only in
the database. The type is decided by sniffing the file's first bytes, never by
trusting the browser's Content-Type or the extension.
"""

import secrets
from pathlib import Path

from flask import current_app
from werkzeug.datastructures import FileStorage

EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}


class UploadError(ValueError):
    pass


def _sniff(head: bytes) -> str | None:
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"%PDF-"):
        return "application/pdf"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        return "image/heic"
    return None


def _max_mb() -> int:
    return current_app.config.get('EXPENSES_MAX_UPLOAD_MB', 10)


def upload_root() -> Path:
    """Private folder for receipts — deliberately NOT under static/."""
    root = Path(current_app.config.get('EXPENSES_UPLOAD_DIR')
                or Path(current_app.root_path) / 'private' / 'expense_receipts')
    root.mkdir(parents=True, exist_ok=True)
    return root


def path_for(stored_name: str) -> Path:
    return upload_root() / stored_name


def read_valid(upload: FileStorage) -> tuple[bytes, str]:
    """Read and validate an upload without storing it. Returns (data, content_type)."""
    limit = _max_mb() * 1024 * 1024
    data = upload.stream.read(limit + 1)
    if not data:
        raise UploadError(f"“{upload.filename}” is empty.")
    if len(data) > limit:
        raise UploadError(f"“{upload.filename}” is larger than {_max_mb()} MB.")
    content_type = _sniff(data[:16])
    if content_type is None:
        raise UploadError(f"“{upload.filename}” isn't a photo (JPEG, PNG, HEIC, WebP) or PDF.")
    return data, content_type


def save(upload: FileStorage) -> tuple[str, str, int]:
    """Validate and store an upload. Returns (stored_name, content_type, size)."""
    data, content_type = read_valid(upload)
    stored_name = secrets.token_hex(16) + EXTENSIONS[content_type]
    path_for(stored_name).write_bytes(data)
    return stored_name, content_type, len(data)


def delete(stored_name: str) -> None:
    path_for(stored_name).unlink(missing_ok=True)
