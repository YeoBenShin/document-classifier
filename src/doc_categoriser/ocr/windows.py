"""OCR with the Windows.Media.Ocr API of Windows 10 and later, through the pywinrt projection. Importable only on Windows."""

# The winrt packages install only on Windows, so on other systems their types are unknown to pyright.
# pyright: reportMissingImports=false, reportUnknownParameterType=false

import asyncio

from PIL import Image
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine as WinRtOcrEngine
from winrt.windows.media.ocr import OcrLine, OcrResult
from winrt.windows.storage.streams import DataWriter

from doc_categoriser.errors import OcrEngineUnavailableError
from doc_categoriser.ocr.layout import TextBox, boxes_to_text


def _fit_within(image: Image.Image, max_dimension: int) -> Image.Image:
    """Return `image` scaled down, aspect ratio kept, so that neither side is longer than `max_dimension`."""
    if max(image.size) <= max_dimension:
        return image
    scale = max_dimension / max(image.size)
    return image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)


def _to_software_bitmap(image: Image.Image) -> SoftwareBitmap:
    """Copy the pixels of `image` into a Windows SoftwareBitmap in RGBA8 format."""
    rgba_image = image.convert("RGBA")
    writer = DataWriter()
    writer.write_bytes(rgba_image.tobytes())
    return SoftwareBitmap.create_copy_from_buffer(
        writer.detach_buffer(), BitmapPixelFormat.RGBA8, rgba_image.width, rgba_image.height
    )


def _line_to_box(line: OcrLine, image_width: int, image_height: int) -> TextBox:
    """Return the text of `line` with the bounding box of all its words, as fractions of the image size."""
    word_rects = [word.bounding_rect for word in line.words]
    left = min(rect.x for rect in word_rects)
    top = min(rect.y for rect in word_rects)
    bottom = max(rect.y + rect.height for rect in word_rects)
    return TextBox(
        text=line.text,
        left=left / image_width,
        top=top / image_height,
        height=(bottom - top) / image_height,
    )


class WindowsOcrEngine:
    """OCR with the Windows.Media.Ocr API, in the languages of the Windows user profile."""

    def __init__(self) -> None:
        """Raise OcrEngineUnavailableError if no OCR language of the user profile is installed."""
        engine = WinRtOcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise OcrEngineUnavailableError(
                "Windows OCR has no installed language of the user profile. "
                "Install an OCR language pack in Windows Settings > Time & Language > Language."
            )
        self._engine = engine

    def recognise_text(self, image: Image.Image) -> str:
        """Return the text in `image`, one line per visual row."""
        fitted_image = _fit_within(image, WinRtOcrEngine.max_image_dimension)
        result = asyncio.run(self._recognise(_to_software_bitmap(fitted_image)))
        boxes = [
            _line_to_box(line, fitted_image.width, fitted_image.height) for line in result.lines if len(line.words) > 0
        ]
        return boxes_to_text(boxes)

    async def _recognise(self, bitmap: SoftwareBitmap) -> OcrResult:
        """Run the asynchronous Windows OCR call on `bitmap`."""
        return await self._engine.recognize_async(bitmap)
