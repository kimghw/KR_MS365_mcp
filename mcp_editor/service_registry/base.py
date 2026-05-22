"""
Scanner Base - Common utilities for multi-language code scanning.

This module provides shared constants, enums, and helper functions used by
the MCP service scanner and other code analysis tools.

Exports:
- Language: Enum for supported programming languages
- DEFAULT_SKIP_PARTS: Default directories to skip during scanning
- detect_language(): Detect language from file extension
- _should_skip(): Check if path should be skipped
- _is_class_type(): Check if type is a custom class
- _parse_type_info(): Parse type string to extract base type and class name
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional

__all__ = [
    "Language",
    "DEFAULT_SKIP_PARTS",
    "detect_language",
    "_should_skip",
    "_is_class_type",
    "_parse_type_info",
]


DEFAULT_SKIP_PARTS = ("venv", "__pycache__", ".git", "node_modules", "backups", ".claude")


class Language(Enum):
    """Supported programming languages."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    TYPESCRIPT = "typescript"
    UNKNOWN = "unknown"


def detect_language(file_path: Path | str) -> Language:
    """Detect programming language from file extension."""
    if isinstance(file_path, str):
        file_path = Path(file_path)
    ext = file_path.suffix.lower()
    if ext == ".py":
        return Language.PYTHON
    elif ext in (".js", ".mjs"):
        return Language.JAVASCRIPT
    elif ext in (".ts", ".tsx"):
        return Language.TYPESCRIPT
    return Language.UNKNOWN


def _should_skip(path: Path, skip_parts: tuple[str, ...] = DEFAULT_SKIP_PARTS) -> bool:
    """Check whether a path should be skipped based on directory parts."""
    return any(part in path.parts for part in skip_parts)


def _is_class_type(type_str: str) -> bool:
    """Check if type is a custom class (not a primitive or generic type).

    Custom class types:
    - Start with uppercase letter
    - Don't start with generic prefixes (List, Dict, Union, Optional, etc.)
    - Are not Python primitives (str, int, float, bool, None, Any)
    """
    if not type_str or not type_str[0].isupper():
        return False

    # Generic type prefixes (keep as-is, not class types)
    generic_prefixes = ("List[", "Dict[", "Union[", "Optional[", "Set[", "Tuple[", "Callable[")
    if any(type_str.startswith(prefix) for prefix in generic_prefixes):
        return False

    # Python/typing primitives that start with uppercase
    primitives = ("None", "Any", "NoReturn", "Type", "Literal")
    if type_str in primitives:
        return False

    # If it's a simple identifier starting with uppercase, it's likely a class
    # e.g., FilterParams, EventSelectParams, QueryMethod
    return True


def _parse_type_info(type_str: Optional[str]) -> Dict[str, Any]:
    """Parse type string to extract base type, class name, and optional flag.

    Returns:
        - base_type: JSON Schema compatible type (object, string, etc.) or generic type
        - class_name: Original class name if type is a custom class, else None
        - is_optional: True if type was Optional[...]

    Examples:
        'Optional[str]' -> {'base_type': 'str', 'class_name': None, 'is_optional': True}
        'str' -> {'base_type': 'str', 'class_name': None, 'is_optional': False}
        'Optional[FilterParams]' -> {'base_type': 'object', 'class_name': 'FilterParams', 'is_optional': True}
        'FilterParams' -> {'base_type': 'object', 'class_name': 'FilterParams', 'is_optional': False}
        'List[str]' -> {'base_type': 'List[str]', 'class_name': None, 'is_optional': False}
    """
    if type_str is None:
        return {"base_type": None, "class_name": None, "is_optional": False}

    is_optional = False
    inner_type = type_str

    # Check for Optional[...]
    if type_str.startswith("Optional[") and type_str.endswith("]"):
        inner_type = type_str[9:-1]  # Remove 'Optional[' and ']'
        is_optional = True

    # Check if inner type is a custom class
    if _is_class_type(inner_type):
        return {"base_type": "object", "class_name": inner_type, "is_optional": is_optional}

    return {"base_type": inner_type, "class_name": None, "is_optional": is_optional}
