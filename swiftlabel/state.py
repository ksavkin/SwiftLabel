"""
SwiftLabel Session State Management

Manages labeling state, undo/redo, staging, and persistence.
This is the core business logic for SwiftLabel.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from swiftlabel.filesystem import (
    delete_file,
    move_file,
    resolve_image_path,
    scan_images,
    validate_image_path,
)
from swiftlabel.models import (
    CommitResult,
    ImageInfo,
    PreviewChange,
    PreviewSummary,
    SessionFile,
    SessionState,
    Stats,
    UndoStackItem,
)
from swiftlabel.session import SessionPersistence

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Maximum undo stack size
MAX_UNDO_STACK_SIZE = 100


class SessionManager:
    """
    Manages the labeling session state.

    Responsibilities:
    - Track image labels and deletions
    - Manage undo/redo stack
    - Stage filesystem changes
    - Persist state to JSON
    - Execute commits
    """

    def __init__(
        self,
        working_directory: Path,
        classes: list[str],
    ) -> None:
        self.working_directory = working_directory.resolve()
        self.classes = classes
        self.images: list[ImageInfo] = []
        self.current_index: int = 0
        self.labels: dict[str, int] = {}
        self.deleted: set[str] = set()
        self.undo_stack: list[UndoStackItem] = []
        self._persistence = SessionPersistence(self.working_directory)
        self._listeners: list[Callable[[], None]] = []
        self._created_at: datetime | None = None

        # Track initial state to differentiate user changes from loaded data
        self.initial_labels: dict[str, int] = {}
        self.initial_deleted: set[str] = set()

        # V2 Navigation state
        self.current_folder: str = ""

    async def initialize(self) -> None:
        """Initialize session: load existing or create new."""
        # Ensure .swiftlabel directory exists
        await self._persistence.ensure_directory_exists()

        # Try to load existing session
        session = await self._persistence.load_session()
        if session is not None:
            await self._restore_session(session)
        else:
            await self._create_new_session()

        # Log session start to history
        await self._persistence.log_history({
            "action": "session_start",
            "classes": self.classes,
            "total_images": len(self.images),
        })

    async def _restore_session(self, session: SessionFile) -> None:
        """Restore session from loaded data."""

        logger.info(f"Restoring session from {self._persistence.session_file_path}")

        # Verify classes match
        if session.classes != self.classes:
            logger.warning(
                f"Session classes {session.classes} differ from "
                f"requested {self.classes}. Using requested classes."
            )

        # Scan for images
        image_ids = await scan_images(self.working_directory)

        # Restore state from session
        self.labels = session.labels
        self.deleted = set(session.deleted)
        self.undo_stack = session.undo_stack
        self.current_index = min(session.current_index, max(0, len(image_ids) - 1))
        self._created_at = session.created_at

        self._build_image_list(image_ids)

        # Snapshot initial state to track user changes
        self.initial_labels = dict(self.labels)
        self.initial_deleted = set(self.deleted)

        logger.info(
            f"Restored session: {len(self.images)} images, "
            f"{len(self.labels)} labeled, {len(self.deleted)} deleted"
        )

    async def _create_new_session(self) -> None:
        """Create a new session."""
        logger.info("Creating new session")

        # Scan for images
        image_ids = await scan_images(self.working_directory)

        # Initialize state
        self.labels = {}
        self.deleted = set()
        self.undo_stack = []
        self.current_index = 0
        self._created_at = datetime.now(timezone.utc)

        self._build_image_list(image_ids)

        # Snapshot initial state (empty for new session)
        self.initial_labels = {}
        self.initial_deleted = set()

        # Save initial session
        await self._save_session()

        logger.info(f"Created session with {len(self.images)} images")

    def _build_image_list(self, image_ids: list[str]) -> None:
        """Build ImageInfo list from image IDs."""
        self.images = []

        # Create a lowercase mapping of class names for easy matching
        class_map = {c.lower(): i for i, c in enumerate(self.classes)}

        for image_id in image_ids:
            # Check for existing label in session
            label = self.labels.get(image_id)

            # Auto-labeling from path (ResNet-style)
            # If no label in session, check if any parent directory match a class name
            if label is None:
                path_parts = Path(image_id).parent.parts
                for part in reversed(path_parts):
                    if part.lower() in class_map:
                        label = class_map[part.lower()]
                        break

            class_name = self.classes[label] if label is not None else None

            self.images.append(ImageInfo(
                id=image_id,
                filename=image_id,  # Use relative path as filename/ID for context
                label=label,
                class_name=class_name,
                marked_for_deletion=image_id in self.deleted,
            ))

    async def _save_session(self) -> None:
        """Persist session state to disk."""
        await self._persistence.save_session(
            classes=self.classes,
            current_index=self.current_index,
            labels=self.labels,
            deleted=self.deleted,
            undo_stack=self.undo_stack,
            created_at=self._created_at,
        )

    def add_listener(self, callback: Callable[[], None]) -> None:
        """Add state change listener."""
        self._listeners.append(callback)

    def _notify_listeners(self) -> None:
        """Notify all listeners of state change."""
        for callback in self._listeners:
            try:
                callback()
            except Exception as e:
                logger.error(f"Listener error: {e}")

    def get_session_state(self) -> SessionState:
        """Get complete session state for API response."""
        return SessionState(
            version="1.0",
            working_directory=str(self.working_directory),
            classes=self.classes,
            images=self.images,
            current_index=self.current_index,
            staged_changes=[],  # Changes are tracked via labels/deleted
            undo_stack=self.undo_stack,
        )

    def get_stats(self) -> Stats:
        """Get labeling statistics."""
        labeled_count = 0
        deleted_count = 0

        # Count per class
        per_class: dict[str, int] = dict.fromkeys(self.classes, 0)

        for img in self.images:
            if img.marked_for_deletion:
                deleted_count += 1
            elif img.label is not None:
                labeled_count += 1
                if 0 <= img.label < len(self.classes):
                    per_class[self.classes[img.label]] += 1

        unlabeled_count = len(self.images) - labeled_count - deleted_count
        total = len(self.images)
        progress = (labeled_count / total * 100) if total > 0 else 0.0

        return Stats(
            total_images=total,
            labeled_count=labeled_count,
            unlabeled_count=unlabeled_count,
            deleted_count=deleted_count,
            per_class=per_class,
            progress_percent=round(progress, 1),
        )

    def get_current_image(self) -> ImageInfo | None:
        """Get the currently viewed image."""
        if 0 <= self.current_index < len(self.images):
            return self.images[self.current_index]
        return None

    def get_image_by_id(self, image_id: str) -> ImageInfo | None:
        """Get image by ID."""
        for img in self.images:
            if img.id == image_id:
                return img
        return None

    def _find_image_index(self, image_id: str) -> int:
        """Find index of image by ID. Returns -1 if not found."""
        for i, img in enumerate(self.images):
            if img.id == image_id:
                return i
        return -1

    async def label_image(
        self,
        image_id: str,
        class_index: int,
    ) -> tuple[bool, str, str | None]:
        """
        Assign label to image.

        Returns:
            Tuple of (success, message, class_name)
        """
        # Validate class index
        if class_index < 0 or class_index >= len(self.classes):
            return False, f"Invalid class index: {class_index}", None

        # Validate image exists
        is_valid, error = validate_image_path(image_id, self.working_directory)
        if not is_valid:
            return False, error, None

        img_index = self._find_image_index(image_id)
        if img_index == -1:
            return False, f"Image not found: {image_id}", None

        # Get previous state for undo
        previous_label = self.labels.get(image_id)
        previous_class = self.classes[previous_label] if previous_label is not None else None

        # Apply label
        self.labels[image_id] = class_index
        class_name = self.classes[class_index]

        # Update image info
        self.images[img_index].label = class_index
        self.images[img_index].class_name = class_name

        # Remove from deleted if present
        if image_id in self.deleted:
            self.deleted.remove(image_id)
            self.images[img_index].marked_for_deletion = False

        # Add to undo stack
        self._push_undo(UndoStackItem(
            action="label",
            image_id=image_id,
            class_index=class_index,
            previous_label=previous_label,
            previous_class_name=previous_class,
            timestamp=time.time(),
        ))

        # Save and notify
        await self._save_session()
        await self._persistence.log_history({
            "action": "label",
            "image_id": image_id,
            "class_index": class_index,
            "class_name": class_name,
        })
        self._notify_listeners()

        return True, f"Labeled {image_id} as {class_name}", class_name

    async def delete_image(self, image_id: str) -> tuple[bool, str]:
        """
        Mark image for deletion.

        Returns:
            Tuple of (success, message)
        """
        # Validate image exists
        is_valid, error = validate_image_path(image_id, self.working_directory)
        if not is_valid:
            return False, error

        img_index = self._find_image_index(image_id)
        if img_index == -1:
            return False, f"Image not found: {image_id}"

        # Check if already deleted
        if image_id in self.deleted:
            return False, f"Image already marked for deletion: {image_id}"

        # Get previous state for undo
        previous_label = self.labels.get(image_id)
        previous_class = self.classes[previous_label] if previous_label is not None else None

        # Mark for deletion
        self.deleted.add(image_id)
        self.images[img_index].marked_for_deletion = True

        # Remove label if present
        if image_id in self.labels:
            del self.labels[image_id]
            self.images[img_index].label = None
            self.images[img_index].class_name = None

        # Add to undo stack
        self._push_undo(UndoStackItem(
            action="delete",
            image_id=image_id,
            previous_label=previous_label,
            previous_class_name=previous_class,
            timestamp=time.time(),
        ))

        # Save and notify
        await self._save_session()
        await self._persistence.log_history({
            "action": "delete",
            "image_id": image_id,
        })
        self._notify_listeners()

        return True, f"Marked {image_id} for deletion"

    def _push_undo(self, item: UndoStackItem) -> None:
        """Add item to undo stack, maintaining max size."""
        self.undo_stack.append(item)

        # Trim if too large
        if len(self.undo_stack) > MAX_UNDO_STACK_SIZE:
            self.undo_stack = self.undo_stack[-MAX_UNDO_STACK_SIZE:]

    async def undo(self) -> tuple[bool, str, str | None, str | None]:
        """
        Undo last action.

        Returns:
            Tuple of (success, message, undone_action, image_id)
        """
        if not self.undo_stack:
            return False, "Nothing to undo", None, None

        item = self.undo_stack.pop()

        if item.action == "label":
            # Restore previous label state
            img_index = self._find_image_index(item.image_id)
            if img_index == -1:
                return False, f"Image not found: {item.image_id}", None, None

            if item.previous_label is not None:
                # Restore previous label
                self.labels[item.image_id] = item.previous_label
                self.images[img_index].label = item.previous_label
                self.images[img_index].class_name = item.previous_class_name
            else:
                # Remove label
                if item.image_id in self.labels:
                    del self.labels[item.image_id]
                self.images[img_index].label = None
                self.images[img_index].class_name = None

        elif item.action == "delete":
            # Unmark for deletion
            if item.image_id in self.deleted:
                self.deleted.remove(item.image_id)

            img_index = self._find_image_index(item.image_id)
            if img_index >= 0:
                self.images[img_index].marked_for_deletion = False

                # Restore previous label if any
                if item.previous_label is not None:
                    self.labels[item.image_id] = item.previous_label
                    self.images[img_index].label = item.previous_label
                    self.images[img_index].class_name = item.previous_class_name

        # Save and notify
        await self._save_session()
        await self._persistence.log_history({
            "action": "undo",
            "undone_action": item.action,
            "image_id": item.image_id,
        })
        self._notify_listeners()

        return True, f"Undid {item.action} on {item.image_id}", item.action, item.image_id

    def navigate(self, direction: str, index: int | None = None) -> int:
        """
        Navigate to a different image.

        Args:
            direction: "next", "previous", "first", "last", "index"
            index: Target index when direction is "index"

        Returns:
            New current index
        """
        if not self.images:
            return 0

        if direction == "next":
            self.current_index = min(self.current_index + 1, len(self.images) - 1)
        elif direction == "previous":
            self.current_index = max(self.current_index - 1, 0)
        elif direction == "first":
            self.current_index = 0
        elif direction == "last":
            self.current_index = len(self.images) - 1
        elif direction == "index" and index is not None:
            self.current_index = max(0, min(index, len(self.images) - 1))

        return self.current_index

    def get_preview(self) -> PreviewSummary:
        """Get preview of pending changes (only user-made changes, not loaded data)."""
        moves: list[PreviewChange] = []
        deletes: list[PreviewChange] = []
        warnings: list[str] = []

        # Only count changes that differ from initial state
        for img in self.images:
            image_id = img.id

            # Check if newly deleted (not in initial_deleted)
            if img.marked_for_deletion and image_id not in self.initial_deleted:
                deletes.append(PreviewChange(
                    action="delete",
                    source=image_id,
                    destination=None,
                ))
            # Check if label changed from initial
            elif img.label is not None:
                initial_label = self.initial_labels.get(image_id)

                # Only count if label is different from initial
                if initial_label != img.label:
                    class_name = self.classes[img.label]

                    # Calculate destination as sibling folder within same parent
                    # e.g., 20230919/up/image.png -> 20230919/down/image.png
                    path = Path(image_id)
                    parent_parts = list(path.parent.parts)

                    # Find and replace the class folder in the path
                    # (walk from end to find the first class-matching folder)
                    class_names_lower = [c.lower() for c in self.classes]
                    for i in range(len(parent_parts) - 1, -1, -1):
                        if parent_parts[i].lower() in class_names_lower:
                            # Replace this class folder with the new class name
                            parent_parts[i] = class_name
                            break
                    else:
                        # No class folder found in path, put in class folder at end
                        parent_parts.append(class_name)

                    destination = str(Path(*parent_parts) / path.name)

                    # Check if already in the correct class folder
                    if destination != image_id:
                        moves.append(PreviewChange(
                            action="move",
                            source=image_id,
                            destination=destination,
                        ))

        return PreviewSummary(
            total_changes=len(moves) + len(deletes),
            moves=moves,
            deletes=deletes,
            warnings=warnings,
        )

    async def commit(self) -> CommitResult:
        """
        Apply all staged changes to filesystem.

        Returns:
            CommitResult with success status and counts
        """
        preview = self.get_preview()
        moves_completed = 0
        deletes_completed = 0
        errors: list[str] = []

        # Execute moves
        for change in preview.moves:
            try:
                source = resolve_image_path(change.source, self.working_directory)
                if change.destination is None:
                    continue
                destination = self.working_directory / change.destination

                await move_file(source, destination)
                moves_completed += 1

            except Exception as e:
                errors.append(f"Failed to move {change.source}: {e}")
                logger.error(f"Move failed: {change.source} -> {change.destination}: {e}")

        # Execute deletes
        for change in preview.deletes:
            try:
                path = resolve_image_path(change.source, self.working_directory)
                await delete_file(path)
                deletes_completed += 1

            except Exception as e:
                errors.append(f"Failed to delete {change.source}: {e}")
                logger.error(f"Delete failed: {change.source}: {e}")

        # Clear state after commit
        self.labels.clear()
        self.deleted.clear()
        self.undo_stack.clear()

        # Rescan images
        image_ids = await scan_images(self.working_directory)
        self._build_image_list(image_ids)
        self.current_index = min(self.current_index, max(0, len(self.images) - 1))

        # Save and notify
        await self._save_session()
        await self._persistence.log_history({
            "action": "commit",
            "moves": moves_completed,
            "deletes": deletes_completed,
        })
        self._notify_listeners()

        return CommitResult(
            success=len(errors) == 0,
            moves_completed=moves_completed,
            deletes_completed=deletes_completed,
            errors=errors,
        )
