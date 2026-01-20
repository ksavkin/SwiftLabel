"""
Tests for SessionManager state management.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from swiftlabel.state import SessionManager


class TestSessionManager:
    """Tests for SessionManager."""

    @pytest.mark.asyncio
    async def test_initialization(
        self,
        temp_image_dir: Path,
        test_classes: list[str],
    ) -> None:
        """Test session initialization scans images."""
        from swiftlabel.state import SessionManager

        manager = SessionManager(temp_image_dir, test_classes)
        await manager.initialize()

        assert len(manager.images) == 8  # 5 + 3 in subdirectory
        assert manager.classes == test_classes
        assert manager.current_index == 0

    @pytest.mark.asyncio
    async def test_label_image(self, session_manager: "SessionManager") -> None:
        """Test labeling an image."""
        image_id = session_manager.images[0].id

        success, message, class_name = await session_manager.label_image(image_id, 0)

        assert success is True
        assert class_name == "cat"
        assert session_manager.labels[image_id] == 0
        assert session_manager.images[0].label == 0
        assert session_manager.images[0].class_name == "cat"

    @pytest.mark.asyncio
    async def test_label_invalid_class(self, session_manager: "SessionManager") -> None:
        """Test labeling with invalid class index."""
        image_id = session_manager.images[0].id

        success, message, _ = await session_manager.label_image(image_id, 99)

        assert success is False
        assert "Invalid class index" in message

    @pytest.mark.asyncio
    async def test_delete_image(self, session_manager: "SessionManager") -> None:
        """Test marking image for deletion."""
        image_id = session_manager.images[0].id

        success, message = await session_manager.delete_image(image_id)

        assert success is True
        assert image_id in session_manager.deleted
        assert session_manager.images[0].marked_for_deletion is True

    @pytest.mark.asyncio
    async def test_undo_label(self, session_manager: "SessionManager") -> None:
        """Test undoing a label action."""
        image_id = session_manager.images[0].id

        # Label then undo
        await session_manager.label_image(image_id, 1)
        success, message, undone_action, _ = await session_manager.undo()

        assert success is True
        assert undone_action == "label"
        assert image_id not in session_manager.labels
        assert session_manager.images[0].label is None

    @pytest.mark.asyncio
    async def test_undo_delete(self, session_manager: "SessionManager") -> None:
        """Test undoing a delete action."""
        image_id = session_manager.images[0].id

        # Delete then undo
        await session_manager.delete_image(image_id)
        success, message, undone_action, _ = await session_manager.undo()

        assert success is True
        assert undone_action == "delete"
        assert image_id not in session_manager.deleted
        assert session_manager.images[0].marked_for_deletion is False

    @pytest.mark.asyncio
    async def test_undo_empty_stack(self, session_manager: "SessionManager") -> None:
        """Test undo with empty stack."""
        success, message, _, _ = await session_manager.undo()

        assert success is False
        assert "Nothing to undo" in message

    def test_navigate(self, session_manager: "SessionManager") -> None:
        """Test navigation between images."""
        assert session_manager.current_index == 0

        session_manager.navigate("next")
        assert session_manager.current_index == 1

        session_manager.navigate("previous")
        assert session_manager.current_index == 0

        session_manager.navigate("last")
        assert session_manager.current_index == len(session_manager.images) - 1

        session_manager.navigate("first")
        assert session_manager.current_index == 0

        session_manager.navigate("index", 3)
        assert session_manager.current_index == 3

    @pytest.mark.asyncio
    async def test_get_stats(self, session_manager: "SessionManager") -> None:
        """Test statistics calculation."""
        # Label some images
        await session_manager.label_image(session_manager.images[0].id, 0)
        await session_manager.label_image(session_manager.images[1].id, 0)
        await session_manager.label_image(session_manager.images[2].id, 1)
        await session_manager.delete_image(session_manager.images[3].id)

        stats = session_manager.get_stats()

        assert stats.total_images == 8
        assert stats.labeled_count == 3
        assert stats.deleted_count == 1
        assert stats.unlabeled_count == 4
        assert stats.per_class["cat"] == 2
        assert stats.per_class["dog"] == 1

    @pytest.mark.asyncio
    async def test_preview(self, session_manager: "SessionManager") -> None:
        """Test change preview."""
        # Stage some changes
        await session_manager.label_image(session_manager.images[0].id, 0)
        await session_manager.label_image(session_manager.images[1].id, 1)
        await session_manager.delete_image(session_manager.images[2].id)

        preview = session_manager.get_preview()

        assert preview.total_changes == 3
        assert len(preview.moves) == 2
        assert len(preview.deletes) == 1

    @pytest.mark.asyncio
    async def test_relabel_image(self, session_manager: "SessionManager") -> None:
        """Test relabeling an already labeled image."""
        image_id = session_manager.images[0].id

        # Label as cat
        await session_manager.label_image(image_id, 0)
        assert session_manager.images[0].class_name == "cat"

        # Relabel as dog
        success, message, class_name = await session_manager.label_image(image_id, 1)

        assert success is True
        assert class_name == "dog"
        assert session_manager.images[0].class_name == "dog"

    @pytest.mark.asyncio
    async def test_undo_restores_previous_label(
        self, session_manager: "SessionManager"
    ) -> None:
        """Test that undo restores previous label when relabeling."""
        image_id = session_manager.images[0].id

        # Label as cat, then dog
        await session_manager.label_image(image_id, 0)
        await session_manager.label_image(image_id, 1)

        # Undo should restore cat
        await session_manager.undo()

        assert session_manager.images[0].label == 0
        assert session_manager.images[0].class_name == "cat"

    @pytest.mark.asyncio
    async def test_delete_removes_label(self, session_manager: "SessionManager") -> None:
        """Test that deleting a labeled image removes its label."""
        image_id = session_manager.images[0].id

        await session_manager.label_image(image_id, 0)
        assert image_id in session_manager.labels

        await session_manager.delete_image(image_id)

        assert image_id not in session_manager.labels
        assert session_manager.images[0].label is None

    @pytest.mark.asyncio
    async def test_label_removes_deletion(self, session_manager: "SessionManager") -> None:
        """Test that labeling a deleted image unmarks it for deletion."""
        image_id = session_manager.images[0].id

        await session_manager.delete_image(image_id)
        assert image_id in session_manager.deleted

        await session_manager.label_image(image_id, 0)

        assert image_id not in session_manager.deleted
        assert session_manager.images[0].marked_for_deletion is False

    def test_get_current_image(self, session_manager: "SessionManager") -> None:
        """Test getting current image."""
        img = session_manager.get_current_image()

        assert img is not None
        assert img.id == session_manager.images[0].id

    def test_get_image_by_id(self, session_manager: "SessionManager") -> None:
        """Test getting image by ID."""
        image_id = session_manager.images[2].id
        img = session_manager.get_image_by_id(image_id)

        assert img is not None
        assert img.id == image_id

    def test_get_image_by_id_not_found(self, session_manager: "SessionManager") -> None:
        """Test getting non-existent image returns None."""
        img = session_manager.get_image_by_id("nonexistent.jpg")
        assert img is None
