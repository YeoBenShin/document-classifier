"""Text extraction from image files."""

from pathlib import Path

from PIL import Image, ImageSequence
from pillow_heif import register_heif_opener

from doc_categoriser.models import ExtractedDocument, ExtractionMethod, PageText
from doc_categoriser.ocr import OcrEngine

register_heif_opener()


class ImageExtractor:
    """Reads an image file with OCR, one page per image frame (multi-page TIFF files have several frames)."""

    supported_suffixes = frozenset({".png", ".jpg", ".jpeg", ".tif", ".tiff", ".heic", ".heif"})

    def __init__(self, ocr_engine: OcrEngine) -> None:
        self._ocr_engine = ocr_engine

    def extract(self, path: Path) -> ExtractedDocument:
        """Return the OCR text of each frame of the image at `path`, in frame order."""
        with Image.open(path) as image:
            pages = [
                PageText(
                    page_number=frame_index + 1,
                    text=self._ocr_engine.recognise_text(frame.convert("RGB")),
                    method=ExtractionMethod.OCR,
                )
                for frame_index, frame in enumerate(ImageSequence.Iterator(image))
            ]
        return ExtractedDocument(source_path=path, pages=pages)
