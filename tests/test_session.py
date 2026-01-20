"""
Tests for session persistence.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from swiftlabel.models import UndoStackItem
from swiftlabel.session import SessionPersistence


class TestSessionPersistence:
    """Tests for SessionPersistence class."""

    @pytest.mark.asyncio
    async def test_ensure_directory_exists(self, temp_image_dir: Path) -> None:
        """Test that .swiftlabel directory is created."""
        persistence = SessionPersistence(temp_image_dir)
        await persistence.ensure_directory_exists()

        swiftlabel_dir = temp_image_dir / ".swiftlabel"
        assert swiftlabel_dir.exists()
        assert swiftlabel_dir.is_dir()

    @pytest.mark.asyncio
    async def test_session_exists_false(self, temp_image_dir: Path) -> None:
        """Test session_exists returns False when no session."""
        persistence = SessionPersistence(temp_image_dir)
        exists = await persistence.session_exists()

        assert exists is False

    @pytest.mark.asyncio
    async def test_save_and_load_session(self, temp_image_dir: Path) -> None:
        """Test saving and loading session."""
        persistence = SessionPersistence(temp_image_dir)

        # Save session
        await persistence.save_session(
            classes=["cat", "dog"],
            current_index=5,
            labels={"image1.jpg": 0, "image2.jpg": 1},
            deleted={"image3.jpg"},
            undo_stack=[],
        )

        # Verify file exists
        assert await persistence.session_exists()

        # Load session
        session = await persistence.load_session()

        assert session is not None
        assert session.classes == ["cat", "dog"]
        assert session.current_index == 5
        assert session.labels == {"image1.jpg": 0, "image2.jpg": 1}
        assert set(session.deleted) == {"image3.jpg"}

    @pytest.mark.asyncio
    async def test_save_session_with_undo_stack(self, temp_image_dir: Path) -> None:
        """Test saving session with undo stack."""
        persistence = SessionPersistence(temp_image_dir)

        undo_item = UndoStackItem(
            action="label",
            image_id="test.jpg",
            class_index=0,
            previous_label=None,
            timestamp=1234567890.0,
        )

        await persistence.save_session(
            classes=["cat"],
            current_index=0,
            labels={},
            deleted=set(),
            undo_stack=[undo_item],
        )

        session = await persistence.load_session()

        assert session is not None
        assert len(session.undo_stack) == 1
        assert session.undo_stack[0].action == "label"
        assert session.undo_stack[0].image_id == "test.jpg"

    @pytest.mark.asyncio
    async def test_log_history(self, temp_image_dir: Path) -> None:
        """Test appending to history file."""
        persistence = SessionPersistence(temp_image_dir)

        await persistence.log_history({"action": "test", "value": 42})
        await persistence.log_history({"action": "test2", "value": 43})

        # Verify history file exists and contains the records
        history_file = temp_image_dir / ".swiftlabel" / "history.jsonl"
        assert history_file.exists()

        lines = history_file.read_text().strip().split("\n")
        assert len(lines) == 2

    @pytest.mark.asyncio
    async def test_session_file_path(self, temp_image_dir: Path) -> None:
        """Test session file path property."""
        persistence = SessionPersistence(temp_image_dir)

        expected = temp_image_dir.resolve() / ".swiftlabel" / "session.json"
        assert persistence.session_file_path == expected

    @pytest.mark.asyncio
    async def test_history_file_path(self, temp_image_dir: Path) -> None:
        """Test history file path property."""
        persistence = SessionPersistence(temp_image_dir)

        expected = temp_image_dir.resolve() / ".swiftlabel" / "history.jsonl"
        assert persistence.history_file_path == expected

    @pytest.mark.asyncio
    async def test_clear_session(self, temp_image_dir: Path) -> None:
        """Test clearing session."""
        persistence = SessionPersistence(temp_image_dir)

        # Create a session
        await persistence.save_session(
            classes=["cat"],
            current_index=0,
            labels={},
            deleted=set(),
            undo_stack=[],
        )
        assert await persistence.session_exists()

        # Clear it
        await persistence.clear_session()
        assert not await persistence.session_exists()

    @pytest.mark.asyncio
    async def test_load_nonexistent_session(self, temp_image_dir: Path) -> None:
        """Test loading returns None when no session exists."""
        persistence = SessionPersistence(temp_image_dir)

        session = await persistence.load_session()
        assert session is None

    @pytest.mark.asyncio
    async def test_session_preserves_created_at(self, temp_image_dir: Path) -> None:
        """Test that created_at is preserved across saves."""
        from datetime import datetime

        persistence = SessionPersistence(temp_image_dir)

        created_time = datetime(2024, 1, 1, 12, 0, 0)

        await persistence.save_session(
            classes=["cat"],
            current_index=0,
            labels={},
            deleted=set(),
            undo_stack=[],
            created_at=created_time,
        )

        session = await persistence.load_session()
        assert session is not None
        assert session.created_at == created_time

    @pytest.mark.asyncio
    async def test_working_directory_resolution(self, temp_image_dir: Path) -> None:
        """Test that working directory is resolved to absolute path."""
        # Use relative path
        import os
        original_cwd = os.getcwd()
        try:
            os.chdir(temp_image_dir.parent)
            relative_path = Path(temp_image_dir.name)

            persistence = SessionPersistence(relative_path)
            assert persistence.working_directory.is_absolute()
        finally:
            os.chdir(original_cwd)
