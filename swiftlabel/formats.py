"""
SwiftLabel Annotation Format Handlers (v2)

Detects folder-based image classification format.
"""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AnnotationFormat(str, Enum):
    """Supported annotation format types."""
    FOLDER = "folder"
    UNKNOWN = "unknown"


FORMAT_LABELS = {
    AnnotationFormat.FOLDER: "Folder Classification",
    AnnotationFormat.UNKNOWN: "Unknown",
}


class FormatDetector:
    """Detects annotation format from dataset structure."""

    def __init__(self, root: Path):
        self.root = root.resolve()

    async def detect(self) -> tuple[AnnotationFormat, float, dict[str, Any]]:
        """
        Detect annotation format from directory structure.

        Returns:
            Tuple of (format, confidence 0.0-1.0, detected_paths)
        """
        # Check Folder format: subdirectories with images
        folder_result = await self._check_folder()
        if folder_result[0]:
            return AnnotationFormat.FOLDER, 0.95, folder_result[1]

        return AnnotationFormat.UNKNOWN, 1.0, {}

    async def _check_folder(self) -> tuple[bool, dict[str, Any]]:
        """Check for folder-based format (class_name/images)."""
        # Recursively find all folders containing images
        image_folders: list[str] = []

        def scan_for_image_folders(path: Path, depth: int = 0) -> None:
            """Recursively scan for folders containing images."""
            if depth > 5:  # Limit depth to prevent infinite recursion
                return

            try:
                for item in path.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        # Check if this folder has images
                        images = (
                            list(item.glob("*.jpg")) +
                            list(item.glob("*.png")) +
                            list(item.glob("*.webp")) +
                            list(item.glob("*.jpeg"))
                        )
                        if images:
                            image_folders.append(item.name)
                        # Also check subfolders
                        scan_for_image_folders(item, depth + 1)
            except PermissionError:
                pass

        scan_for_image_folders(self.root)

        if image_folders:
            # Deduplicate folder names
            unique_folders = list(set(image_folders))
            return True, {"class_folders": unique_folders}
        return False, {}
