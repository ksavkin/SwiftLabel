"""
Tests for FastAPI server endpoints.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from httpx import AsyncClient

if TYPE_CHECKING:
    pass


class TestAPIEndpoints:
    """Tests for REST API endpoints."""

    @pytest.mark.asyncio
    async def test_get_session(self, client: AsyncClient) -> None:
        """Test GET /api/session."""
        response = await client.get("/api/session")

        assert response.status_code == 200
        data = response.json()
        assert "version" in data
        assert "classes" in data
        assert "images" in data
        assert data["classes"] == ["cat", "dog", "bird"]

    @pytest.mark.asyncio
    async def test_get_stats(self, client: AsyncClient) -> None:
        """Test GET /api/stats."""
        response = await client.get("/api/stats")

        assert response.status_code == 200
        data = response.json()
        assert "total_images" in data
        assert "labeled_count" in data
        assert "per_class" in data

    @pytest.mark.asyncio
    async def test_get_images(self, client: AsyncClient) -> None:
        """Test GET /api/images."""
        response = await client.get("/api/images")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 8

    @pytest.mark.asyncio
    async def test_get_image(self, client: AsyncClient) -> None:
        """Test GET /api/images/{id}."""
        # Get image list first
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        response = await client.get(f"/api/images/{image_id}")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")

    @pytest.mark.asyncio
    async def test_get_image_not_found(self, client: AsyncClient) -> None:
        """Test GET /api/images/{id} with non-existent image."""
        response = await client.get("/api/images/nonexistent.png")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_label_image(self, client: AsyncClient) -> None:
        """Test POST /api/label."""
        # Get image list first
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        response = await client.post(
            "/api/label",
            json={"image_id": image_id, "class_index": 0}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["class_name"] == "cat"

    @pytest.mark.asyncio
    async def test_label_invalid_class(self, client: AsyncClient) -> None:
        """Test POST /api/label with invalid class."""
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        response = await client.post(
            "/api/label",
            json={"image_id": image_id, "class_index": 99}
        )

        # 422 from Pydantic validation (class_index > 9), or 400 from business logic
        assert response.status_code in (400, 422)

    @pytest.mark.asyncio
    async def test_delete_image(self, client: AsyncClient) -> None:
        """Test POST /api/delete."""
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        response = await client.post(
            "/api/delete",
            json={"image_id": image_id}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    @pytest.mark.asyncio
    async def test_undo(self, client: AsyncClient) -> None:
        """Test POST /api/undo."""
        # First label an image
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        await client.post(
            "/api/label",
            json={"image_id": image_id, "class_index": 0}
        )

        # Then undo
        response = await client.post("/api/undo")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["undone_action"] == "label"

    @pytest.mark.asyncio
    async def test_undo_empty_stack(self, client: AsyncClient) -> None:
        """Test POST /api/undo with empty stack."""
        response = await client.post("/api/undo")

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_preview_changes(self, client: AsyncClient) -> None:
        """Test GET /api/changes/preview."""
        # Label some images first
        response = await client.get("/api/images")
        images = response.json()

        await client.post(
            "/api/label",
            json={"image_id": images[0]["id"], "class_index": 0}
        )
        await client.post(
            "/api/delete",
            json={"image_id": images[1]["id"]}
        )

        response = await client.get("/api/changes/preview")

        assert response.status_code == 200
        data = response.json()
        assert data["total_changes"] == 2
        assert len(data["moves"]) == 1
        assert len(data["deletes"]) == 1

    @pytest.mark.asyncio
    async def test_stats_updated_after_label(self, client: AsyncClient) -> None:
        """Test that stats are updated after labeling."""
        # Get initial stats
        response = await client.get("/api/stats")
        initial_stats = response.json()

        # Label an image
        response = await client.get("/api/images")
        images = response.json()
        await client.post(
            "/api/label",
            json={"image_id": images[0]["id"], "class_index": 0}
        )

        # Get updated stats
        response = await client.get("/api/stats")
        updated_stats = response.json()

        assert updated_stats["labeled_count"] == initial_stats["labeled_count"] + 1

    @pytest.mark.asyncio
    async def test_image_info_updated_after_label(self, client: AsyncClient) -> None:
        """Test that image info is updated after labeling."""
        # Get images
        response = await client.get("/api/images")
        images = response.json()
        image_id = images[0]["id"]

        assert images[0]["label"] is None

        # Label the image
        await client.post(
            "/api/label",
            json={"image_id": image_id, "class_index": 1}
        )

        # Get updated images
        response = await client.get("/api/images")
        updated_images = response.json()

        labeled_image = next(img for img in updated_images if img["id"] == image_id)
        assert labeled_image["label"] == 1
        assert labeled_image["class_name"] == "dog"

    @pytest.mark.asyncio
    async def test_session_state_consistency(self, client: AsyncClient) -> None:
        """Test that session state is consistent after operations."""
        # Get images
        response = await client.get("/api/images")
        images = response.json()

        # Perform several operations
        await client.post(
            "/api/label",
            json={"image_id": images[0]["id"], "class_index": 0}
        )
        await client.post(
            "/api/label",
            json={"image_id": images[1]["id"], "class_index": 1}
        )
        await client.post(
            "/api/delete",
            json={"image_id": images[2]["id"]}
        )

        # Verify session state
        response = await client.get("/api/session")
        session = response.json()

        assert session["images"][0]["class_name"] == "cat"
        assert session["images"][1]["class_name"] == "dog"
        assert session["images"][2]["marked_for_deletion"] is True

    @pytest.mark.asyncio
    async def test_empty_preview_when_no_changes(self, client: AsyncClient) -> None:
        """Test that preview is empty when no changes are staged."""
        response = await client.get("/api/changes/preview")

        assert response.status_code == 200
        data = response.json()
        assert data["total_changes"] == 0
        assert len(data["moves"]) == 0
        assert len(data["deletes"]) == 0

    @pytest.mark.asyncio
    async def test_delete_nonexistent_image(self, client: AsyncClient) -> None:
        """Test deleting a non-existent image."""
        response = await client.post(
            "/api/delete",
            json={"image_id": "nonexistent.png"}
        )

        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_label_nonexistent_image(self, client: AsyncClient) -> None:
        """Test labeling a non-existent image."""
        response = await client.post(
            "/api/label",
            json={"image_id": "nonexistent.png", "class_index": 0}
        )

        assert response.status_code == 400
