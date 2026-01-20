"""
SwiftLabel Filesystem Operations

Async file scanning, validation, and operations using aiofiles.
All file I/O MUST go through this module.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import aiofiles
import aiofiles.os

logger = logging.getLogger(__name__)

# Allowed image extensions (case-insensitive)
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({
    ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"
})

# MIME types for serving
MIME_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
}


def is_valid_extension(path: Path) -> bool:
    """Check if file has a valid image extension."""
    return path.suffix.lower() in ALLOWED_EXTENSIONS


def get_mime_type(path: Path) -> str:
    """Get MIME type for an image file."""
    return MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def normalize_image_id(path: Path, base_dir: Path) -> str:
    """Convert absolute path to relative image ID."""
    return str(path.relative_to(base_dir))


def resolve_image_path(image_id: str, base_dir: Path) -> Path:
    """Convert image ID back to absolute path."""
    return base_dir / image_id


def validate_image_path(path: str, base_dir: Path) -> tuple[bool, str]:
    """
    Validate image path for security and correctness.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for path traversal attacks
    if ".." in path:
        return False, "Path traversal (..) not allowed"

    # Check for null bytes
    if "\x00" in path:
        return False, "Null bytes not allowed in path"

    # Check extension
    ext = Path(path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Unsupported image extension: {ext}"

    # Resolve full path
    full_path = base_dir / path

    # Security: Ensure resolved path is within base directory
    try:
        full_path.resolve().relative_to(base_dir.resolve())
    except ValueError:
        return False, "Path escapes working directory"

    return True, ""


def sanitize_image_id(image_id: str) -> str:
    """Remove dangerous characters from image ID."""
    return re.sub(r'[^a-zA-Z0-9_\-./]', '_', image_id)


async def scan_images(directory: Path) -> list[str]:
    """
    Async scan directory for image files.

    Args:
        directory: Path to scan for images

    Returns:
        List of image IDs (relative paths) sorted alphabetically
    """
    images: list[str] = []

    # Use sync os.walk but yield to event loop periodically
    for root, _dirs, files in os.walk(directory):
        root_path = Path(root)

        # Skip .swiftlabel directory
        if ".swiftlabel" in root_path.parts:
            continue

        for filename in files:
            file_path = root_path / filename

            if is_valid_extension(file_path):
                image_id = normalize_image_id(file_path, directory)
                images.append(image_id)

        # Yield to event loop every batch
        await asyncio.sleep(0)

    # Sort alphabetically for consistent ordering
    images.sort()
    return images


async def file_exists(path: Path) -> bool:
    """Async check if file exists."""
    try:
        await aiofiles.os.stat(path)
        return True
    except FileNotFoundError:
        return False


async def read_file(path: Path) -> bytes:
    """Async read file contents."""
    async with aiofiles.open(path, "rb") as f:
        return await f.read()


async def write_file(path: Path, content: bytes | str) -> None:
    """Async write file contents."""
    if isinstance(content, str):
        async with aiofiles.open(path, "w") as f:
            await f.write(content)
    else:
        async with aiofiles.open(path, "wb") as f:
            await f.write(content)


async def read_json(path: Path) -> dict[str, Any]:
    """Async read JSON file."""
    content = await read_file(path)
    result: dict[str, Any] = json.loads(content.decode("utf-8"))
    return result


async def write_json(path: Path, data: dict[str, Any]) -> None:
    """Async write JSON file with pretty formatting."""
    content = json.dumps(data, indent=2, default=str)
    await write_file(path, content)


async def append_line(path: Path, line: str) -> None:
    """Async append a line to a file."""
    async with aiofiles.open(path, "a") as f:
        await f.write(line)


async def ensure_directory(path: Path) -> None:
    """Async create directory if it doesn't exist."""
    await aiofiles.os.makedirs(path, exist_ok=True)


async def move_file(source: Path, destination: Path) -> None:
    """
    Async move file to new location.
    Creates destination directory if needed.
    """
    # Ensure destination directory exists
    await ensure_directory(destination.parent)

    # Use rename for same-filesystem move (fast)
    try:
        await aiofiles.os.rename(source, destination)
    except OSError:
        # Cross-filesystem: copy then delete
        content = await read_file(source)
        await write_file(destination, content)
        await aiofiles.os.remove(source)


async def delete_file(path: Path) -> None:
    """Async delete file."""
    await aiofiles.os.remove(path)


async def get_file_size(path: Path) -> int:
    """Async get file size in bytes."""
    stat = await aiofiles.os.stat(path)
    return stat.st_size


class FileSystemError(Exception):
    """Custom exception for filesystem operations."""

    def __init__(self, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.path = path


async def validate_working_directory(directory: Path) -> tuple[bool, list[str]]:
    """
    Validate working directory has required permissions.

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues: list[str] = []

    if not directory.exists():
        return False, [f"Directory does not exist: {directory}"]

    if not directory.is_dir():
        return False, [f"Path is not a directory: {directory}"]

    if not os.access(directory, os.R_OK):
        issues.append(f"No read permission: {directory}")

    if not os.access(directory, os.W_OK):
        issues.append(f"No write permission: {directory}")

    if not os.access(directory, os.X_OK):
        issues.append(f"No execute permission: {directory}")

    return len(issues) == 0, issues
