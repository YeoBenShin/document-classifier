"""Puts recognised text fragments in reading order, so each visual row of a page is one line."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TextBox:
    """One recognised text fragment with its position as fractions of the image size, origin at top left."""

    text: str
    left: float
    top: float
    height: float

    @property
    def vertical_centre(self) -> float:
        return self.top + self.height / 2


def _group_into_rows(boxes: list[TextBox]) -> list[list[TextBox]]:
    """Group boxes whose vertical centres fall inside the same row, top row first."""
    rows: list[list[TextBox]] = []
    for box in sorted(boxes, key=lambda candidate: candidate.top):
        current_row = rows[-1] if rows else None
        if current_row is not None and abs(box.vertical_centre - current_row[0].vertical_centre) < current_row[0].height / 2:
            current_row.append(box)
        else:
            rows.append([box])
    return rows


def boxes_to_text(boxes: list[TextBox]) -> str:
    """Join boxes into lines, left to right within a row and top to bottom across rows."""
    lines = [
        " ".join(box.text for box in sorted(row, key=lambda candidate: candidate.left))
        for row in _group_into_rows(boxes)
    ]
    return "\n".join(lines)
