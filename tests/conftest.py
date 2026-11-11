"""Builders for sample documents, and the GGUF model, used by the tests."""

import os
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from doc_categoriser import LlamaCppClassifier

PageLines = Sequence[str]


def render_text_image(lines: PageLines) -> Image.Image:
    """Draw the lines as black text on a white A4-ratio image, like a scanned page."""
    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for line_index, line in enumerate(lines):
        draw.text((100, 150 + line_index * 80), line, fill="black", font=font)
    return image


@pytest.fixture
def make_text_pdf(tmp_path: Path) -> Callable[[str, list[PageLines]], Path]:
    """Return a builder that writes a PDF with a real text layer, one entry per page."""

    def build(file_name: str, pages: list[PageLines]) -> Path:
        pdf_path = tmp_path / file_name
        canvas = Canvas(str(pdf_path), pagesize=A4)
        for lines in pages:
            for line_index, line in enumerate(lines):
                canvas.drawString(72, 770 - line_index * 20, line)
            canvas.showPage()
        canvas.save()
        return pdf_path

    return build


@pytest.fixture
def make_scanned_pdf(tmp_path: Path) -> Callable[[str, list[PageLines]], Path]:
    """Return a builder that writes an image-only PDF (no text layer), one entry per page."""

    def build(file_name: str, pages: list[PageLines]) -> Path:
        pdf_path = tmp_path / file_name
        page_images = [render_text_image(lines) for lines in pages]
        page_images[0].save(pdf_path, save_all=True, append_images=page_images[1:], resolution=150)
        return pdf_path

    return build


@pytest.fixture
def make_image(tmp_path: Path) -> Callable[[str, PageLines], Path]:
    """Return a builder that writes a single-page image file in the format given by the suffix."""

    def build(file_name: str, lines: PageLines) -> Path:
        image_path = tmp_path / file_name
        render_text_image(lines).save(image_path)
        return image_path

    return build


@pytest.fixture
def make_mixed_pdf(tmp_path: Path) -> Callable[[str, list[tuple[str, PageLines]]], Path]:
    """Return a builder for a PDF whose pages are each ("text", lines) for a text layer or ("scan", lines) for an image only."""

    def build(file_name: str, pages: list[tuple[str, PageLines]]) -> Path:
        pdf_path = tmp_path / file_name
        canvas = Canvas(str(pdf_path), pagesize=A4)
        page_width, page_height = A4
        for kind, lines in pages:
            if kind == "scan":
                canvas.drawInlineImage(render_text_image(lines), 0, 0, width=page_width, height=page_height)
            else:
                for line_index, line in enumerate(lines):
                    canvas.drawString(72, 770 - line_index * 20, line)
            canvas.showPage()
        canvas.save()
        return pdf_path

    return build


TEST_MODEL_PATH = Path(
    os.environ.get(
        "DOC_CATEGORISER_TEST_MODEL",
        Path(__file__).resolve().parent.parent / "models" / "Qwen3.5-4B-Q4_K_M.gguf",
    )
)


@pytest.fixture(scope="session")
def test_model_path() -> Path:
    """Return the GGUF model used by the classification tests. Skip the test if the file is not there."""
    if not TEST_MODEL_PATH.is_file():
        pytest.skip(f"GGUF model not found at {TEST_MODEL_PATH}. Set DOC_CATEGORISER_TEST_MODEL to its path.")
    return TEST_MODEL_PATH


@pytest.fixture(scope="session")
def llama_classifier(test_model_path: Path) -> LlamaCppClassifier:
    """Return one classifier for the whole test session, because loading the model takes several seconds."""
    return LlamaCppClassifier(test_model_path)
