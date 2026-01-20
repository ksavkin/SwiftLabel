"""
SwiftLabel Session Persistence

Handles loading and saving session state to disk.
Session files are stored in .swiftlabel/session.json.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from swiftlabel.filesystem import (
    append_line,
    ensure_directory,
    file_exists,
    read_json,
    write_json,
)
from swiftlabel.models import SessionFile, UndoStackItem

logger = logging.getLogger(__name__)


class SessionPersistence:
    """
    Handles session file persistence.

    Session data is stored in:
    - .swiftlabel/session.json - Main session state
    - .swiftlabel/history.jsonl - Append-only action log
    """

    def __init__(self, working_directory: Path) -> None:
        self.working_directory = working_directory.resolve()
        self._swiftlabel_dir = self.working_directory / ".swiftlabel"
        self._session_file = self._swiftlabel_dir / "session.json"
        self._history_file = self._swiftlabel_dir / "history.jsonl"

    @property
    def session_file_path(self) -> Path:
        """Get path to session.json."""
        return self._session_file

    @property
    def history_file_path(self) -> Path:
        """Get path to history.jsonl."""
        return self._history_file

    async def ensure_directory_exists(self) -> None:
        """Create .swiftlabel directory if needed."""
        await ensure_directory(self._swiftlabel_dir)

    async def session_exists(self) -> bool:
        """Check if a session file exists."""
        return await file_exists(self._session_file)

    async def load_session(self) -> SessionFile | None:
        """
        Load session from disk.

        Returns:
            SessionFile if exists and valid, None otherwise
        """
        if not await self.session_exists():
            return None

        try:
            data = await read_json(self._session_file)
            session = SessionFile.model_validate(data)
            logger.info(f"Loaded session from {self._session_file}")
            return session
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return None

    async def save_session(
        self,
        classes: list[str],
        current_index: int,
        labels: dict[str, int],
        deleted: set[str],
        undo_stack: list[UndoStackItem],
        created_at: datetime | None = None,
    ) -> None:
        """
        Save session state to disk.

        Args:
            classes: List of class names
            current_index: Current image index
            labels: Map of image_id -> class_index
            deleted: Set of image IDs marked for deletion
            undo_stack: List of undo stack items
            created_at: Original creation time (for updates)
        """
        await self.ensure_directory_exists()

        session = SessionFile(
            version="1.0",
            working_directory=str(self.working_directory),
            classes=classes,
            current_index=current_index,
            labels=labels,
            deleted=list(deleted),
            undo_stack=undo_stack,
            created_at=created_at or datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await write_json(self._session_file, session.model_dump())
        logger.debug("Session saved")

    async def log_history(self, record: dict[str, Any]) -> None:
        """
        Append a record to history.jsonl.

        Args:
            record: Dictionary to log (timestamp will be added)
        """
        await self.ensure_directory_exists()

        record["ts"] = time.time()
        line = json.dumps(record) + "\n"
        await append_line(self._history_file, line)

    async def clear_session(self) -> None:
        """Delete the session file (for fresh start)."""
        if await self.session_exists():
            import aiofiles.os
            await aiofiles.os.remove(self._session_file)
            logger.info("Session cleared")
