"""
Tests for filesystem operations.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from swiftlabel.filesystem import (
    ALLOWED_EXTENSIONS,
    is_valid_extension,
    normalize_image_id,
    resolve_image_path,
    scan_images,
    validate_image_path,
)


class TestFilesystem:
    """Tests for filesystem module."""

    def test_is_valid_extension(self) -> None:
        """Test extension validation."""
        assert is_valid_extension(Path("test.jpg")) is True
        assert is_valid_extension(Path("test.JPEG")) is True
        assert is_valid_extension(Path("test.png")) is True
        assert is_valid_extension(Path("test.webp")) is True
        assert is_valid_extension(Path("test.txt")) is False
        assert is_valid_extension(Path("test.py")) is False

    def test_normalize_image_id(self) -> None:
        """Test path to image ID conversion."""
        base = Path("/home/user/images")
        path = Path("/home/user/images/photo.jpg")

        image_id = normalize_image_id(path, base)

        assert image_id == "photo.jpg"

    def test_normalize_image_id_subdirectory(self) -> None:
        """Test path normalization with subdirectory."""
        base = Path("/home/user/images")
        path = Path("/home/user/images/batch1/photo.jpg")

        image_id = normalize_image_id(path, base)

        assert image_id == "batch1/photo.jpg"

    def test_resolve_image_path(self) -> None:
        """Test image ID to path conversion."""
        base = Path("/home/user/images")
        image_id = "batch1/photo.jpg"

        path = resolve_image_path(image_id, base)

        assert path == Path("/home/user/images/batch1/photo.jpg")

    def test_validate_image_path_traversal(self, temp_image_dir: Path) -> None:
        """Test path traversal detection."""
        is_valid, error = validate_image_path("../etc/passwd", temp_image_dir)

        assert is_valid is False
        assert "traversal" in error.lower()

    def test_validate_image_path_null_byte(self, temp_image_dir: Path) -> None:
        """Test null byte detection."""
        is_valid, error = validate_image_path("test\x00.jpg", temp_image_dir)

        assert is_valid is False
        assert "null" in error.lower()

    def test_validate_image_path_bad_extension(self, temp_image_dir: Path) -> None:
        """Test invalid extension detection."""
        is_valid, error = validate_image_path("test.txt", temp_image_dir)

        assert is_valid is False
        assert "extension" in error.lower()

    def test_validate_image_path_valid(self, temp_image_dir: Path) -> None:
        """Test valid path validation."""
        is_valid, error = validate_image_path("image000.png", temp_image_dir)

        assert is_valid is True
        assert error == ""

    @pytest.mark.asyncio
    async def test_scan_images(self, temp_image_dir: Path) -> None:
        """Test image scanning."""
        images = await scan_images(temp_image_dir)

        assert len(images) == 8
        assert all(is_valid_extension(Path(img)) for img in images)
        # Should be sorted
        assert images == sorted(images)

    @pytest.mark.asyncio
    async def test_scan_images_ignores_swiftlabel(self, temp_image_dir: Path) -> None:
        """Test that .swiftlabel directory is ignored."""
        # Create .swiftlabel directory with an image
        swiftlabel_dir = temp_image_dir / ".swiftlabel"
        swiftlabel_dir.mkdir()
        (swiftlabel_dir / "should_ignore.png").write_bytes(b"fake png")

        images = await scan_images(temp_image_dir)

        # Should not include images from .swiftlabel
        assert not any(".swiftlabel" in img for img in images)

    def test_allowed_extensions(self) -> None:
        """Test that all expected extensions are allowed."""
        expected = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tiff", ".tif"}
        assert ALLOWED_EXTENSIONS == expected

    def test_validate_image_path_with_spaces(self, temp_image_dir: Path) -> None:
        """Test path validation with spaces in filename."""
        # Create a file with spaces
        test_file = temp_image_dir / "test image.png"
        test_file.write_bytes(b"fake png")

        is_valid, error = validate_image_path("test image.png", temp_image_dir)

        assert is_valid is True
        assert error == ""

    def test_validate_subdirectory_path(self, temp_image_dir: Path) -> None:
        """Test validation of paths in subdirectories."""
        is_valid, error = validate_image_path("batch1/sub_image000.png", temp_image_dir)

        assert is_valid is True
        assert error == ""
