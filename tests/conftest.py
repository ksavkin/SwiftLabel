"""
Pytest fixtures for SwiftLabel tests.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

if TYPE_CHECKING:
    from fastapi import FastAPI
    from swiftlabel.state import SessionManager


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_image_dir() -> Generator[Path, None, None]:
    """Create temporary directory with test images."""
    temp_dir = Path(tempfile.mkdtemp())

    # Create test images (1x1 pixel PNGs)
    # Minimal valid PNG header
    png_header = bytes([
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,  # PNG signature
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,  # IHDR chunk
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,  # 1x1 pixels
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,  # 8-bit RGB
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,  # IDAT chunk
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xFF, 0xFF, 0x3F,  # Compressed data
        0x00, 0x05, 0xFE, 0x02, 0xFE, 0xDC, 0xCC, 0x59,
        0xE7, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E,  # IEND chunk
        0x44, 0xAE, 0x42, 0x60, 0x82
    ])

    # Create test images
    for i in range(5):
        (temp_dir / f"image{i:03d}.png").write_bytes(png_header)

    # Create subdirectory with images
    subdir = temp_dir / "batch1"
    subdir.mkdir()
    for i in range(3):
        (subdir / f"sub_image{i:03d}.png").write_bytes(png_header)

    yield temp_dir

    # Cleanup
    shutil.rmtree(temp_dir)


@pytest.fixture
def test_classes() -> list[str]:
    """Default test class names."""
    return ["cat", "dog", "bird"]


@pytest_asyncio.fixture
async def session_manager(
    temp_image_dir: Path,
    test_classes: list[str],
) -> AsyncGenerator["SessionManager", None]:
    """Create initialized SessionManager."""
    from swiftlabel.state import SessionManager

    manager = SessionManager(temp_image_dir, test_classes)
    await manager.initialize()
    yield manager


@pytest_asyncio.fixture
async def app(
    temp_image_dir: Path,
    test_classes: list[str],
) -> AsyncGenerator["FastAPI", None]:
    """Create test FastAPI application with initialized session."""
    from swiftlabel import server
    from swiftlabel.server import create_app
    from swiftlabel.state import SessionManager

    app = create_app(
        working_directory=temp_image_dir,
        classes=test_classes,
    )

    # Manually initialize session_manager for tests (lifespan doesn't trigger with test client)
    server.session_manager = SessionManager(temp_image_dir, test_classes)
    await server.session_manager.initialize()

    yield app

    # Cleanup
    server.session_manager = None
    server.websocket_clients.clear()


@pytest_asyncio.fixture
async def client(app: "FastAPI") -> AsyncGenerator[AsyncClient, None]:
    """Create async HTTP test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
