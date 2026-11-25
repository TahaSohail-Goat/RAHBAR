"""Path confinement helpers for the Assignment 3 command-line tools."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def confined_path(path: Path, roots: Iterable[Path]) -> Path:
    """Resolve a user-supplied path and require it to stay under an allowed root."""
    resolved = path.resolve()
    for root in roots:
        base = root.resolve()
        if resolved == base or resolved.is_relative_to(base):
            return resolved
    raise ValueError(f"path must be inside one of the permitted directories: {path}")
