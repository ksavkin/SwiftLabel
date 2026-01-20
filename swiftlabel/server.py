"""
SwiftLabel FastAPI Server

HTTP REST API and WebSocket endpoints for the SwiftLabel backend.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from swiftlabel.filesystem import (
    file_exists,
    get_mime_type,
    resolve_image_path,
    validate_image_path,
)
from swiftlabel.formats import FORMAT_LABELS, FormatDetector
from swiftlabel.models import (
    Breadcrumb,
    Breadcrumbs,
    ChangeCount,
    ChangeDiff,
    ChangeDiffItem,
    CommitResult,
    DeleteRequest,
    DeleteResponse,
    ErrorResponse,
    FormatInfo,
    LabelRequest,
    LabelResponse,
    NavigateFolderRequest,
    NavigateFolderResponse,
    PreviewSummary,
    SessionState,
    Stats,
    SubfolderInfo,
    SubfolderList,
    UndoResponse,
    WSChangesCommitted,
    WSError,
    WSImageDeleted,
    WSImageLabeled,
    WSStateUpdate,
    WSUndoCompleted,
)
from swiftlabel.state import SessionManager

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

# Global state (initialized on startup)
session_manager: SessionManager | None = None
websocket_clients: set[WebSocket] = set()


def create_app(
    working_directory: Path,
    classes: list[str],
    host: str = "127.0.0.1",
    port: int = 8765,
) -> FastAPI:
    """
    Create and configure the FastAPI application.

    Args:
        working_directory: Path to the image directory
        classes: List of class names
        host: Server bind address
        port: Server port

    Returns:
        Configured FastAPI application
    """
    global session_manager

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
        """Manage application lifecycle."""
        global session_manager

        # Startup
        logger.info(f"Starting SwiftLabel server on {host}:{port}")
        logger.info(f"Working directory: {working_directory}")
        logger.info(f"Classes: {classes}")

        session_manager = SessionManager(working_directory, classes)
        await session_manager.initialize()

        yield

        # Shutdown
        logger.info("Shutting down SwiftLabel server")
        websocket_clients.clear()

    app = FastAPI(
        title="SwiftLabel",
        description="Keyboard-first image classification tool",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[f"http://localhost:{port}", f"http://127.0.0.1:{port}"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    # Static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Register routes
    _register_routes(app)

    return app


def _register_routes(app: FastAPI) -> None:
    """Register all API routes."""

    @app.get("/")
    async def serve_index() -> FileResponse:
        """Serve the main HTML page."""
        static_dir = Path(__file__).parent / "static"
        return FileResponse(static_dir / "index.html")

    @app.get("/style.css")
    async def serve_css() -> FileResponse:
        """Serve the stylesheet."""
        static_dir = Path(__file__).parent / "static"
        return FileResponse(static_dir / "style.css", media_type="text/css")

    @app.get("/app.js")
    async def serve_js() -> FileResponse:
        """Serve the JavaScript application."""
        static_dir = Path(__file__).parent / "static"
        return FileResponse(static_dir / "app.js", media_type="application/javascript")

    # === API Endpoints ===

    @app.get("/api/session/info")
    async def get_session_info() -> dict[str, Any]:
        """Get session info - used for resume/fresh modal."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        # Check if there's pending work from a previous session
        has_labels = len(session_manager.labels) > 0
        has_deletions = len(session_manager.deleted) > 0
        has_pending = has_labels or has_deletions

        return {
            "has_pending_changes": has_pending,
            "labels_count": len(session_manager.labels),
            "deletions_count": len(session_manager.deleted),
        }

    @app.post("/api/session/clear")
    async def clear_session() -> dict[str, Any]:
        """Clear the session - start fresh."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        # Clear all tracked changes
        session_manager.labels.clear()
        session_manager.deleted.clear()
        session_manager.undo_stack.clear()

        # Reset initial tracking
        session_manager.initial_labels = {}
        session_manager.initial_deleted = set()

        # Rebuild image list (removes deletion marks and auto-labels only)
        from swiftlabel.filesystem import scan_images
        image_ids = await scan_images(session_manager.working_directory)
        session_manager._build_image_list(image_ids)

        # Save the cleared session
        await session_manager._save_session()

        return {"success": True, "message": "Session cleared"}

    @app.get("/api/session", response_model=SessionState)
    async def get_session() -> SessionState:
        """Get complete session state."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")
        return session_manager.get_session_state()

    @app.get("/api/stats", response_model=Stats)
    async def get_stats() -> Stats:
        """Get labeling statistics."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")
        return session_manager.get_stats()

    @app.get("/api/images")
    async def get_images() -> list[dict[str, Any]]:
        """Get list of all images."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")
        return [img.model_dump() for img in session_manager.images]

    @app.get("/api/images/{image_id:path}")
    async def get_image(image_id: str) -> Response:
        """Serve an image file."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        # URL decode the image ID
        image_id = unquote(image_id)

        # Validate path
        is_valid, error = validate_image_path(image_id, session_manager.working_directory)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="INVALID_IMAGE_PATH",
                    message=error,
                    details={"image_id": image_id}
                ).model_dump()
            )

        # Resolve path
        path = resolve_image_path(image_id, session_manager.working_directory)

        if not await file_exists(path):
            raise HTTPException(
                status_code=404,
                detail=ErrorResponse(
                    error="IMAGE_NOT_FOUND",
                    message=f"Image not found: {image_id}",
                    details={"image_id": image_id}
                ).model_dump()
            )

        return FileResponse(
            path,
            media_type=get_mime_type(path),
            headers={"Cache-Control": "max-age=3600"}
        )

    @app.post("/api/label", response_model=LabelResponse)
    async def label_image(request: LabelRequest) -> LabelResponse:
        """Assign a class label to an image."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        success, message, class_name = await session_manager.label_image(
            request.image_id,
            request.class_index,
        )

        if not success:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="LABEL_FAILED",
                    message=message,
                    details={"image_id": request.image_id}
                ).model_dump()
            )

        # Broadcast update
        await _broadcast_ws({
            "type": "image_labeled",
            "payload": WSImageLabeled(
                image_id=request.image_id,
                class_index=request.class_index,
                class_name=class_name or "",
            ).model_dump()
        })
        await _broadcast_state_update()

        return LabelResponse(
            success=True,
            image_id=request.image_id,
            class_index=request.class_index,
            class_name=class_name or "",
        )

    @app.post("/api/delete", response_model=DeleteResponse)
    async def delete_image(request: DeleteRequest) -> DeleteResponse:
        """Mark an image for deletion."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        success, message = await session_manager.delete_image(request.image_id)

        if not success:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="DELETE_FAILED",
                    message=message,
                    details={"image_id": request.image_id}
                ).model_dump()
            )

        # Broadcast update
        await _broadcast_ws({
            "type": "image_deleted",
            "payload": WSImageDeleted(image_id=request.image_id).model_dump()
        })
        await _broadcast_state_update()

        return DeleteResponse(success=True, image_id=request.image_id)

    @app.post("/api/undo", response_model=UndoResponse)
    async def undo_action() -> UndoResponse:
        """Undo the last action."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        success, message, undone_action, image_id = await session_manager.undo()

        if not success:
            raise HTTPException(
                status_code=400,
                detail=ErrorResponse(
                    error="NOTHING_TO_UNDO",
                    message=message,
                    details=None
                ).model_dump()
            )

        # Broadcast update
        if undone_action and image_id:
            img = session_manager.get_image_by_id(image_id)
            await _broadcast_ws({
                "type": "undo_completed",
                "payload": WSUndoCompleted(
                    undone_action=undone_action,
                    image_id=image_id,
                    restored_state={
                        "label": img.label if img else None,
                        "class_name": img.class_name if img else None,
                        "marked_for_deletion": img.marked_for_deletion if img else False,
                    }
                ).model_dump()
            })
        await _broadcast_state_update()

        return UndoResponse(
            success=True,
            undone_action=undone_action,
            image_id=image_id,
            message=message,
        )

    @app.get("/api/changes/preview", response_model=PreviewSummary)
    async def preview_changes() -> PreviewSummary:
        """Preview pending changes before commit."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")
        return session_manager.get_preview()

    @app.post("/api/changes/commit", response_model=CommitResult)
    async def commit_changes() -> CommitResult:
        """Apply all staged changes to filesystem."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        result = await session_manager.commit()

        # Broadcast update
        await _broadcast_ws({
            "type": "changes_committed",
            "payload": WSChangesCommitted(
                moves_count=result.moves_completed,
                deletes_count=result.deletes_completed,
                errors=result.errors,
            ).model_dump()
        })
        await _broadcast_state_update()

        return result

    # === v2 API Endpoints ===

    @app.get("/api/subfolders", response_model=SubfolderList)
    async def get_subfolders() -> SubfolderList:
        """List navigable subfolders."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        current_folder = getattr(session_manager, 'current_folder', '')
        base_path = session_manager.working_directory / current_folder if current_folder else session_manager.working_directory

        subfolders = []
        if base_path.exists():
            for item in sorted(base_path.iterdir()):
                if item.is_dir() and not item.name.startswith('.'):
                    rel_path = str(item.relative_to(session_manager.working_directory))
                    # Count images in folder
                    image_count = len(list(item.glob('*.jpg')) + list(item.glob('*.png')) + list(item.glob('*.webp')))
                    subfolders.append(SubfolderInfo(
                        path=rel_path,
                        name=item.name,
                        image_count=image_count,
                        labeled_count=0  # TODO: count labeled
                    ))

        return SubfolderList(
            current_folder=current_folder,
            subfolders=subfolders,
            has_subfolders=len(subfolders) > 0
        )

    @app.post("/api/navigate/folder", response_model=NavigateFolderResponse)
    async def navigate_folder(request: NavigateFolderRequest) -> NavigateFolderResponse:
        """Change current subfolder context."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        folder_path = request.folder_path
        target = session_manager.working_directory / folder_path if folder_path else session_manager.working_directory

        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=404, detail="Folder not found")

        # Store current folder on session manager
        session_manager.current_folder = folder_path

        # Build breadcrumbs
        breadcrumbs = [Breadcrumb(path="", name="root", is_current=(folder_path == ""))]
        if folder_path:
            parts = folder_path.split('/')
            accumulated = ""
            for i, part in enumerate(parts):
                accumulated = f"{accumulated}/{part}".strip('/')
                breadcrumbs.append(Breadcrumb(
                    path=accumulated,
                    name=part,
                    is_current=(i == len(parts) - 1)
                ))

        image_count = len(list(target.glob('*.jpg')) + list(target.glob('*.png')) + list(target.glob('*.webp')))

        return NavigateFolderResponse(
            success=True,
            current_folder=folder_path,
            image_count=image_count,
            breadcrumbs=breadcrumbs
        )

    @app.get("/api/breadcrumbs", response_model=Breadcrumbs)
    async def get_breadcrumbs() -> Breadcrumbs:
        """Get current path as breadcrumb list."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        current_folder = getattr(session_manager, 'current_folder', '')
        breadcrumbs = [Breadcrumb(path="", name="root", is_current=(current_folder == ""))]
        if current_folder:
            parts = current_folder.split('/')
            accumulated = ""
            for i, part in enumerate(parts):
                accumulated = f"{accumulated}/{part}".strip('/')
                breadcrumbs.append(Breadcrumb(
                    path=accumulated,
                    name=part,
                    is_current=(i == len(parts) - 1)
                ))

        return Breadcrumbs(breadcrumbs=breadcrumbs)

    @app.get("/api/format", response_model=FormatInfo)
    async def get_format() -> FormatInfo:
        """Get detected annotation format."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        # Actually run the format detector
        detector = FormatDetector(session_manager.working_directory)
        detected_format, confidence, detected_paths = await detector.detect()

        return FormatInfo(
            format=detected_format.value,
            format_label=FORMAT_LABELS.get(detected_format, "Unknown"),
            detected_paths=detected_paths,
            classes_from_file=session_manager.classes,
            confidence=confidence
        )

    @app.get("/api/changes/count", response_model=ChangeCount)
    async def get_changes_count() -> ChangeCount:
        """Get ONLY user-made changes count."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        # Use get_preview() which correctly calculates actual pending changes
        # (only images that will actually move or be deleted on commit)
        preview = session_manager.get_preview()
        user_changes = preview.total_changes

        return ChangeCount(
            user_changes_count=user_changes,
            has_changes=user_changes > 0,
            breakdown={
                "moves": len(preview.moves),
                "deletions": len(preview.deletes)
            }
        )

    @app.get("/api/changes/diff", response_model=ChangeDiff)
    async def get_changes_diff() -> ChangeDiff:
        """Get detailed diff (old → new labels)."""
        if session_manager is None:
            raise HTTPException(status_code=500, detail="Session not initialized")

        changes = []
        initial_labels = getattr(session_manager, 'initial_labels', {})

        for image_id, new_label in session_manager.labels.items():
            prev = initial_labels.get(image_id)
            change_type = "new_label" if prev is None else "relabel"
            changes.append(ChangeDiffItem(
                image_id=image_id,
                previous_label=prev,
                new_label=new_label,
                change_type=change_type
            ))

        for image_id in session_manager.deleted:
            prev = initial_labels.get(image_id)
            changes.append(ChangeDiffItem(
                image_id=image_id,
                previous_label=prev,
                new_label=None,
                change_type="deletion"
            ))

        return ChangeDiff(changes=changes, total_changes=len(changes))

    # === WebSocket Endpoint ===

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        """WebSocket endpoint for real-time updates."""
        await websocket.accept()
        websocket_clients.add(websocket)

        try:
            # Send initial state
            await _send_state_update(websocket)

            # Handle messages
            while True:
                data = await websocket.receive_json()
                await _handle_ws_message(websocket, data)

        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected")
        except Exception as e:
            logger.error(f"WebSocket error: {e}")
        finally:
            websocket_clients.discard(websocket)


async def _handle_ws_message(websocket: WebSocket, data: dict[str, Any]) -> None:
    """Handle incoming WebSocket message."""
    if session_manager is None:
        await websocket.send_json({
            "type": "error",
            "payload": WSError(
                code="SESSION_NOT_INITIALIZED",
                message="Session not initialized",
            ).model_dump()
        })
        return

    msg_type = data.get("type")
    payload = data.get("payload", {})

    try:
        if msg_type == "sync":
            await _send_state_update(websocket)

        elif msg_type == "navigate":
            direction = payload.get("direction", "next")
            index = payload.get("index")
            session_manager.navigate(direction, index)
            await _broadcast_state_update()

        elif msg_type == "label":
            image_id = payload.get("image_id")
            class_index = payload.get("class_index")

            if image_id is not None and class_index is not None:
                success, message, class_name = await session_manager.label_image(
                    image_id, class_index
                )

                if success:
                    await _broadcast_ws({
                        "type": "image_labeled",
                        "payload": WSImageLabeled(
                            image_id=image_id,
                            class_index=class_index,
                            class_name=class_name or "",
                        ).model_dump()
                    })
                    await _broadcast_state_update()
                else:
                    await websocket.send_json({
                        "type": "error",
                        "payload": WSError(
                            code="LABEL_FAILED",
                            message=message,
                            details={"image_id": image_id}
                        ).model_dump()
                    })

        elif msg_type == "delete":
            image_id = payload.get("image_id")

            if image_id is not None:
                success, message = await session_manager.delete_image(image_id)

                if success:
                    await _broadcast_ws({
                        "type": "image_deleted",
                        "payload": WSImageDeleted(image_id=image_id).model_dump()
                    })
                    await _broadcast_state_update()
                else:
                    await websocket.send_json({
                        "type": "error",
                        "payload": WSError(
                            code="DELETE_FAILED",
                            message=message,
                            details={"image_id": image_id}
                        ).model_dump()
                    })

        elif msg_type == "undo":
            success, message, undone_action, image_id = await session_manager.undo()

            if success and undone_action and image_id:
                img = session_manager.get_image_by_id(image_id)
                await _broadcast_ws({
                    "type": "undo_completed",
                    "payload": WSUndoCompleted(
                        undone_action=undone_action,
                        image_id=image_id,
                        restored_state={
                            "label": img.label if img else None,
                            "class_name": img.class_name if img else None,
                            "marked_for_deletion": img.marked_for_deletion if img else False,
                        }
                    ).model_dump()
                })
                await _broadcast_state_update()
            elif not success:
                await websocket.send_json({
                    "type": "error",
                    "payload": WSError(
                        code="NOTHING_TO_UNDO",
                        message=message,
                    ).model_dump()
                })

    except Exception as e:
        logger.error(f"Error handling WebSocket message: {e}")
        await websocket.send_json({
            "type": "error",
            "payload": WSError(
                code="INTERNAL_ERROR",
                message=str(e),
            ).model_dump()
        })


async def _send_state_update(websocket: WebSocket) -> None:
    """Send state update to a single WebSocket client."""
    if session_manager is None:
        return

    stats = session_manager.get_stats()
    current_image = session_manager.get_current_image()

    await websocket.send_json({
        "type": "state_update",
        "payload": WSStateUpdate(
            current_index=session_manager.current_index,
            total_images=stats.total_images,
            labeled_count=stats.labeled_count,
            deleted_count=stats.deleted_count,
            current_image=current_image,
        ).model_dump()
    })


async def _broadcast_state_update() -> None:
    """Broadcast state update to all WebSocket clients."""
    if session_manager is None:
        return

    stats = session_manager.get_stats()
    current_image = session_manager.get_current_image()

    message = {
        "type": "state_update",
        "payload": WSStateUpdate(
            current_index=session_manager.current_index,
            total_images=stats.total_images,
            labeled_count=stats.labeled_count,
            deleted_count=stats.deleted_count,
            current_image=current_image,
        ).model_dump()
    }

    await _broadcast_ws(message)


async def _broadcast_ws(message: dict[str, Any]) -> None:
    """Broadcast message to all WebSocket clients."""
    disconnected: set[WebSocket] = set()

    for client in websocket_clients:
        try:
            await client.send_json(message)
        except Exception:
            disconnected.add(client)

    # Clean up disconnected clients
    websocket_clients.difference_update(disconnected)
