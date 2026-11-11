"""The list of categories a document can be classified into, read from a TOML file."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_categoriser.errors import CategoryFileError


@dataclass(frozen=True)
class Category:
    """One category: `name` goes into the output, `description` tells the model what the category holds."""

    name: str
    description: str


def load_categories(path: Path) -> list[Category]:
    """
    Return the `[[category]]` entries of the TOML file at `path`, in file order.
    Raise CategoryFileError if the file is missing, is not TOML, has no entries,
    has an entry without a text name and description, or uses a name twice.
    """
    content = _read_toml(path)
    entries = content.get("category")
    if not isinstance(entries, list) or not entries:
        raise CategoryFileError(path, "has no [[category]] entries")
    categories = [_category_from_entry(path, entry_number, entry) for entry_number, entry in enumerate(entries, start=1)]
    _check_names_are_unique(path, categories)
    return categories


def _read_toml(path: Path) -> dict[str, Any]:
    """Return the parsed TOML content of `path`."""
    try:
        with path.open("rb") as categories_file:
            return tomllib.load(categories_file)
    except FileNotFoundError as error:
        raise CategoryFileError(path, "does not exist") from error
    except tomllib.TOMLDecodeError as error:
        raise CategoryFileError(path, f"is not valid TOML ({error})") from error


def _category_from_entry(path: Path, entry_number: int, entry: Any) -> Category:
    """Return the Category for one `[[category]]` table. `entry_number` starts at 1 and is used in the error message."""
    name = entry.get("name") if isinstance(entry, dict) else None
    description = entry.get("description") if isinstance(entry, dict) else None
    if not isinstance(name, str) or not name or not isinstance(description, str) or not description:
        raise CategoryFileError(path, f"category {entry_number} needs a text 'name' and 'description'")
    return Category(name=name, description=description)


def _check_names_are_unique(path: Path, categories: list[Category]) -> None:
    """Raise CategoryFileError if two categories have the same name."""
    seen_names: set[str] = set()
    for category in categories:
        if category.name in seen_names:
            raise CategoryFileError(path, f"category name '{category.name}' is used more than once")
        seen_names.add(category.name)
