"""Value system for the simulator.

Provides literal parsing, type defaults, and type coercion — the
foundation for all runtime value handling.
"""

from __future__ import annotations

import re

from plx.model.types import (
    ArrayTypeRef,
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    StringTypeRef,
    TypeRef,
)


class SimulationError(Exception):
    """Runtime error during simulation."""


# ---------------------------------------------------------------------------
# TIME literal regex
# ---------------------------------------------------------------------------

_TIME_RE = re.compile(
    r"^(?:L?TIME#|T#|LT#)"
    r"(?:(-)?)"
    r"(?:(\d+)h)?"
    r"(?:(\d+)m(?!s))?"
    r"(?:(\d+(?:\.\d+)?)s)?"
    r"(?:(\d+(?:\.\d+)?)ms)?"
    r"(?:(\d+(?:\.\d+)?)us)?"
    r"(?:(\d+)ns)?"
    r"$",
    re.IGNORECASE,
)


def _parse_time_literal(value: str) -> int:
    """Parse an IEC TIME/LTIME literal to milliseconds (int)."""
    m = _TIME_RE.match(value)
    if m is None:
        raise SimulationError(f"Invalid TIME literal: {value!r}")

    sign = -1 if m.group(1) else 1
    hours = int(m.group(2)) if m.group(2) else 0
    minutes = int(m.group(3)) if m.group(3) else 0
    seconds = float(m.group(4)) if m.group(4) else 0.0
    ms = float(m.group(5)) if m.group(5) else 0.0
    us = float(m.group(6)) if m.group(6) else 0.0
    # ns ignored for millisecond resolution

    total_ms = (
        hours * 3_600_000
        + minutes * 60_000
        + seconds * 1_000
        + ms
        + us / 1_000
    )
    return sign * int(round(total_ms))


# ---------------------------------------------------------------------------
# Literal parsing
# ---------------------------------------------------------------------------

_INTEGER_TYPES = frozenset({
    PrimitiveType.SINT, PrimitiveType.INT, PrimitiveType.DINT, PrimitiveType.LINT,
    PrimitiveType.USINT, PrimitiveType.UINT, PrimitiveType.UDINT, PrimitiveType.ULINT,
    PrimitiveType.BYTE, PrimitiveType.WORD, PrimitiveType.DWORD, PrimitiveType.LWORD,
})

_FLOAT_TYPES = frozenset({
    PrimitiveType.REAL, PrimitiveType.LREAL,
})

_TIME_TYPES = frozenset({
    PrimitiveType.TIME, PrimitiveType.LTIME,
})


def parse_literal(
    value: str,
    data_type: TypeRef | None = None,
    enum_registry: dict[str, dict[str, int]] | None = None,
) -> object:
    """Parse an IR literal string into a Python value.

    - "TRUE"/"FALSE" -> bool
    - Integer strings -> int
    - Float strings -> float
    - "T#..."/"TIME#..."/"LTIME#..." -> int (milliseconds)
    - "'text'" -> str
    - "EnumName#MEMBER" -> int (via enum_registry)
    """
    upper = value.upper()

    # Boolean
    if upper == "TRUE":
        return True
    if upper == "FALSE":
        return False

    # TIME/LTIME literals
    if upper.startswith(("T#", "TIME#", "LTIME#", "LT#")):
        return _parse_time_literal(value)

    # Quoted string
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]

    # Enum literal: "EnumName#MEMBER"
    if "#" in value:
        enum_name, _, member_name = value.partition("#")
        if enum_registry and enum_name in enum_registry:
            members = enum_registry[enum_name]
            if member_name in members:
                return members[member_name]
        raise SimulationError(f"Cannot resolve enum literal: {value!r}")

    # Use data_type hint if available
    if data_type is not None and isinstance(data_type, PrimitiveTypeRef):
        ptype = data_type.type
        if ptype == PrimitiveType.BOOL:
            return upper == "TRUE"
        if ptype in _TIME_TYPES:
            return _parse_time_literal(value)
        if ptype in _FLOAT_TYPES:
            try:
                return float(value)
            except ValueError:
                pass
        if ptype in _INTEGER_TYPES:
            try:
                return int(value)
            except ValueError:
                pass

    # Generic numeric detection
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass

    return value


# ---------------------------------------------------------------------------
# Type defaults
# ---------------------------------------------------------------------------

def type_default(data_type: TypeRef) -> object:
    """Return the default zero-value for a type.

    NamedTypeRef and ArrayTypeRef return None — handled at allocation level.
    """
    if isinstance(data_type, PrimitiveTypeRef):
        ptype = data_type.type
        if ptype == PrimitiveType.BOOL:
            return False
        if ptype in _INTEGER_TYPES:
            return 0
        if ptype in _FLOAT_TYPES:
            return 0.0
        if ptype in _TIME_TYPES:
            return 0
        if ptype in (PrimitiveType.CHAR, PrimitiveType.WCHAR):
            return ""
        # DATE/TOD/DT/LDT — return 0 for now
        return 0

    if isinstance(data_type, StringTypeRef):
        return ""

    # Named types and arrays are handled at allocation level
    return None


# ---------------------------------------------------------------------------
# Type coercion
# ---------------------------------------------------------------------------

def coerce_type(value: object, target_type: TypeRef) -> object:
    """Coerce a value to match a target type.

    - int <-> float conversions
    - bool <-> int conversions
    - IEC DIV semantics: int(a/b) truncates toward zero
    """
    if not isinstance(target_type, PrimitiveTypeRef):
        return value

    ptype = target_type.type

    if ptype == PrimitiveType.BOOL:
        return bool(value)

    if ptype in _INTEGER_TYPES:
        if isinstance(value, float):
            return int(value)  # truncate toward zero
        if isinstance(value, bool):
            return int(value)
        return value

    if ptype in _FLOAT_TYPES:
        if isinstance(value, (int, bool)):
            return float(value)
        return value

    return value
