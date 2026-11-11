"""OCR engines that turn a page image into text, and selection of an engine by name."""

import sys
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from PIL import Image

from doc_categoriser.errors import OcrEngineUnavailableError


class OcrEngine(Protocol):
    """Turns an image of a page into plain text in reading order."""

    def recognise_text(self, image: Image.Image) -> str: ...


class OcrEngineName(StrEnum):
    """The OCR engines the program can use. Each one runs only on its own operating system."""

    APPLE_VISION = "apple-vision"
    WINDOWS = "windows"


def _create_apple_vision_engine() -> OcrEngine:
    from doc_categoriser.extraction.ocr.apple_vision import AppleVisionOcrEngine

    return AppleVisionOcrEngine()


def _create_windows_engine() -> OcrEngine:
    from doc_categoriser.extraction.ocr.windows import WindowsOcrEngine

    return WindowsOcrEngine()


@dataclass(frozen=True)
class _EngineSpec:
    """How to show, place and build one OCR engine. `platform` is the `sys.platform` value it needs."""

    display_name: str
    platform: str
    platform_display_name: str
    create: Callable[[], OcrEngine]


_ENGINE_SPECS = {
    OcrEngineName.APPLE_VISION: _EngineSpec("Apple Vision OCR", "darwin", "macOS", _create_apple_vision_engine),
    OcrEngineName.WINDOWS: _EngineSpec("Windows OCR", "win32", "Windows", _create_windows_engine),
}


def native_ocr_engine_name() -> OcrEngineName:
    """Return the engine of the operating system the program runs on. Raise OcrEngineUnavailableError if there is none."""
    for engine_name, spec in _ENGINE_SPECS.items():
        if sys.platform == spec.platform:
            return engine_name
    raise OcrEngineUnavailableError(f"no OCR engine is available on this operating system ({sys.platform})")


def create_ocr_engine(engine_name: OcrEngineName) -> OcrEngine:
    """Return a new engine of the given name. Raise OcrEngineUnavailableError if it cannot run on this operating system."""
    spec = _ENGINE_SPECS[engine_name]
    if sys.platform != spec.platform:
        raise OcrEngineUnavailableError(f"{spec.display_name} is available only on {spec.platform_display_name}")
    return spec.create()
