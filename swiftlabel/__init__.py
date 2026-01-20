"""
SwiftLabel - Keyboard-first image classification tool.

A fast, local-only tool for ML practitioners to classify images
using keyboard shortcuts. All changes are staged until committed.
"""

__version__ = "1.0.0"
__author__ = "SwiftLabel Team"
__license__ = "MIT"

from swiftlabel.models import (
    ActionType,
    ImageInfo,
    SessionState,
    Stats,
)
from swiftlabel.state import SessionManager

__all__ = [
    "__version__",
    "ActionType",
    "ImageInfo",
    "SessionState",
    "SessionManager",
    "Stats",
]
