"""
SwiftLabel Data Models

All Pydantic models for API requests, responses, and internal state.
These models are the single source of truth for data structures.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Types of actions that can be staged/undone."""
    LABEL = "label"
    DELETE = "delete"
    UNLABEL = "unlabel"
    UNDELETE = "undelete"


class ImageInfo(BaseModel):
    """Information about a single image in the working directory."""
    id: str = Field(
        ...,
        description="Relative path from working directory (image ID)",
        examples=["photo001.jpg", "batch1/img_003.png"]
    )
    filename: str = Field(
        ...,
        description="Just the filename without directory path"
    )
    label: int | None = Field(
        None,
        ge=0,
        le=9,
        description="Class index (0-9) or None if unlabeled"
    )
    class_name: str | None = Field(
        None,
        description="Class name corresponding to label"
    )
    marked_for_deletion: bool = Field(
        False,
        description="Whether the image is marked for deletion"
    )


class StagedChange(BaseModel):
    """A single staged change (not yet applied to filesystem)."""
    action: ActionType
    image_id: str
    class_index: int | None = Field(None, ge=0, le=9)
    class_name: str | None = None
    previous_label: int | None = Field(None, ge=0, le=9)
    previous_class_name: str | None = None
    timestamp: float


class UndoStackItem(BaseModel):
    """A single item in the undo stack."""
    action: str
    image_id: str
    class_index: int | None = None
    previous_label: int | None = None
    previous_class_name: str | None = None
    timestamp: float


class SessionState(BaseModel):
    """Complete session state returned by GET /api/session."""
    version: str = "1.0"
    working_directory: str
    classes: list[str] = Field(..., min_length=1, max_length=10)
    images: list[ImageInfo] = Field(default_factory=list)
    current_index: int = Field(0, ge=0)
    staged_changes: list[StagedChange] = Field(default_factory=list)
    undo_stack: list[UndoStackItem] = Field(default_factory=list)


class SessionFile(BaseModel):
    """Schema for .swiftlabel/session.json file."""
    version: str = "1.0"
    working_directory: str
    classes: list[str] = Field(..., min_length=1, max_length=10)
    current_index: int = Field(0, ge=0)
    labels: dict[str, int] = Field(default_factory=dict)
    deleted: list[str] = Field(default_factory=list)
    undo_stack: list[UndoStackItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class Stats(BaseModel):
    """Labeling statistics returned by GET /api/stats."""
    total_images: int = Field(..., ge=0)
    labeled_count: int = Field(..., ge=0)
    unlabeled_count: int = Field(..., ge=0)
    deleted_count: int = Field(..., ge=0)
    per_class: dict[str, int]
    progress_percent: float = Field(..., ge=0, le=100)


# === Request Models ===

class LabelRequest(BaseModel):
    """Request body for POST /api/label."""
    image_id: str = Field(..., min_length=1)
    class_index: int = Field(..., ge=0, le=9)


class DeleteRequest(BaseModel):
    """Request body for POST /api/delete."""
    image_id: str = Field(..., min_length=1)


# === Response Models ===

class LabelResponse(BaseModel):
    """Response body for POST /api/label."""
    success: bool
    image_id: str
    class_index: int
    class_name: str


class DeleteResponse(BaseModel):
    """Response body for POST /api/delete."""
    success: bool
    image_id: str


class UndoResponse(BaseModel):
    """Response body for POST /api/undo."""
    success: bool
    undone_action: str | None = None
    image_id: str | None = None
    message: str


class PreviewChange(BaseModel):
    """A single change in the commit preview."""
    action: str
    source: str
    destination: str | None = None


class PreviewSummary(BaseModel):
    """Response body for GET /api/changes/preview."""
    total_changes: int = Field(..., ge=0)
    moves: list[PreviewChange]
    deletes: list[PreviewChange]
    warnings: list[str] = Field(default_factory=list)


class CommitResult(BaseModel):
    """Response body for POST /api/changes/commit."""
    success: bool
    moves_completed: int = Field(..., ge=0)
    deletes_completed: int = Field(..., ge=0)
    errors: list[str] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standardized error response format."""
    error: str
    message: str
    details: dict[str, Any] | None = None


# === WebSocket Message Models ===

class WSStateUpdate(BaseModel):
    """WebSocket state_update message payload."""
    current_index: int
    total_images: int
    labeled_count: int
    deleted_count: int
    current_image: ImageInfo | None = None


class WSImageLabeled(BaseModel):
    """WebSocket image_labeled message payload."""
    image_id: str
    class_index: int
    class_name: str


class WSImageDeleted(BaseModel):
    """WebSocket image_deleted message payload."""
    image_id: str


class WSUndoCompleted(BaseModel):
    """WebSocket undo_completed message payload."""
    undone_action: str
    image_id: str
    restored_state: dict[str, Any]


class WSChangesCommitted(BaseModel):
    """WebSocket changes_committed message payload."""
    moves_count: int
    deletes_count: int
    errors: list[str]


class WSError(BaseModel):
    """WebSocket error message payload."""
    code: str
    message: str
    details: dict[str, Any] | None = None


# === v2 Models: Subfolder Navigation ===

class SubfolderInfo(BaseModel):
    """Information about a navigable subfolder."""
    path: str
    name: str
    image_count: int = 0
    labeled_count: int = 0


class SubfolderList(BaseModel):
    """Response for GET /api/subfolders."""
    current_folder: str = ""
    subfolders: list[SubfolderInfo] = Field(default_factory=list)
    has_subfolders: bool = False


class Breadcrumb(BaseModel):
    """Single breadcrumb in navigation path."""
    path: str
    name: str
    is_current: bool = False


class Breadcrumbs(BaseModel):
    """Response for GET /api/breadcrumbs."""
    breadcrumbs: list[Breadcrumb] = Field(default_factory=list)


class NavigateFolderRequest(BaseModel):
    """Request for POST /api/navigate/folder."""
    folder_path: str = ""


class NavigateFolderResponse(BaseModel):
    """Response for POST /api/navigate/folder."""
    success: bool
    current_folder: str
    image_count: int = 0
    breadcrumbs: list[Breadcrumb] = Field(default_factory=list)


# === v2 Models: Format Detection ===

class FormatInfo(BaseModel):
    """Response for GET /api/format."""
    format: str
    format_label: str
    detected_paths: dict[str, Any] = Field(default_factory=dict)
    classes_from_file: list[str] = Field(default_factory=list)
    confidence: float = 1.0


# === v2 Models: Change Tracking ===

class ChangeCount(BaseModel):
    """Response for GET /api/changes/count."""
    user_changes_count: int = 0
    has_changes: bool = False
    breakdown: dict[str, int] = Field(default_factory=dict)


class ChangeDiffItem(BaseModel):
    """Single item in the change diff."""
    image_id: str
    previous_label: int | None = None
    new_label: int | None = None
    change_type: str


class ChangeDiff(BaseModel):
    """Response for GET /api/changes/diff."""
    changes: list[ChangeDiffItem] = Field(default_factory=list)
    total_changes: int = 0


# === v2 WebSocket Messages ===

class WSFolderChanged(BaseModel):
    """WebSocket folder_changed message payload."""
    current_folder: str
    image_count: int
    labeled_count: int
    breadcrumbs: list[Breadcrumb]


class WSChangeCountUpdate(BaseModel):
    """WebSocket change_count_update message payload."""
    user_changes_count: int
    has_changes: bool
