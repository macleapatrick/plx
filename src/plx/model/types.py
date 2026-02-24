"""Type system for the Universal IR.

Two distinct concepts:
- TypeRef: used wherever a type is *referenced* (variable declarations,
  expression annotations, array element types, function return types).
- TypeDefinition: a named type *definition* that lives in the project's
  type registry (project.data_types).

These are separate discriminated unions. TypeRef never contains a
TypeDefinition — named types are referenced by name via NamedTypeRef.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

class PrimitiveType(str, Enum):
    """IEC 61131-3 elementary types."""

    # Boolean
    BOOL = "BOOL"

    # Bit-string
    BYTE = "BYTE"
    WORD = "WORD"
    DWORD = "DWORD"
    LWORD = "LWORD"

    # Signed integer
    SINT = "SINT"
    INT = "INT"
    DINT = "DINT"
    LINT = "LINT"

    # Unsigned integer
    USINT = "USINT"
    UINT = "UINT"
    UDINT = "UDINT"
    ULINT = "ULINT"

    # Floating point
    REAL = "REAL"
    LREAL = "LREAL"

    # Duration
    TIME = "TIME"
    LTIME = "LTIME"

    # Date and time
    DATE = "DATE"
    LDATE = "LDATE"
    TOD = "TOD"
    LTOD = "LTOD"
    DT = "DT"
    LDT = "LDT"

    # Character
    CHAR = "CHAR"
    WCHAR = "WCHAR"


# ---------------------------------------------------------------------------
# Type References (used in variable decls, expressions, return types, etc.)
# ---------------------------------------------------------------------------

class PrimitiveTypeRef(BaseModel):
    """Reference to a primitive type (BOOL, INT, REAL, etc.)."""

    kind: Literal["primitive"] = "primitive"
    type: PrimitiveType


class StringTypeRef(BaseModel):
    """STRING or WSTRING with optional max length."""

    kind: Literal["string"] = "string"
    wide: bool = False
    max_length: int | None = None


class NamedTypeRef(BaseModel):
    """Reference to a named type (UDT, FB type, system type, etc.)."""

    kind: Literal["named"] = "named"
    name: str


class DimensionRange(BaseModel):
    """Array dimension bounds (inclusive)."""

    lower: int = 0
    upper: int

    @model_validator(mode="after")
    def _bounds_check(self):
        if self.lower > self.upper:
            raise ValueError(
                f"lower ({self.lower}) must be <= upper ({self.upper})"
            )
        return self


class ArrayTypeRef(BaseModel):
    """Inline array type: ARRAY[lo..hi, lo..hi] OF element_type."""

    kind: Literal["array"] = "array"
    element_type: TypeRef
    dimensions: list[DimensionRange]


class PointerTypeRef(BaseModel):
    """POINTER TO target_type."""

    kind: Literal["pointer"] = "pointer"
    target_type: TypeRef


class ReferenceTypeRef(BaseModel):
    """REFERENCE TO target_type."""

    kind: Literal["reference"] = "reference"
    target_type: TypeRef


TypeRef = Annotated[
    Union[
        PrimitiveTypeRef,
        StringTypeRef,
        NamedTypeRef,
        ArrayTypeRef,
        PointerTypeRef,
        ReferenceTypeRef,
    ],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Type Definitions (live in project.data_types)
# ---------------------------------------------------------------------------

class StructMember(BaseModel):
    """Member of a struct or union."""

    name: str
    data_type: TypeRef
    initial_value: str | None = None
    description: str = ""


class StructType(BaseModel):
    """Named struct type definition."""

    kind: Literal["struct"] = "struct"
    name: str
    folder: str = ""
    members: list[StructMember]


class EnumMember(BaseModel):
    """Member of an enum type."""

    name: str
    value: int | None = None


class EnumType(BaseModel):
    """Named enum type definition."""

    kind: Literal["enum"] = "enum"
    name: str
    folder: str = ""
    members: list[EnumMember]
    base_type: PrimitiveType | None = None


class UnionType(BaseModel):
    """Named union type definition."""

    kind: Literal["union"] = "union"
    name: str
    folder: str = ""
    members: list[StructMember]


class AliasType(BaseModel):
    """Type alias (typedef): TYPE MyAlias : base_type; END_TYPE."""

    kind: Literal["alias"] = "alias"
    name: str
    folder: str = ""
    base_type: TypeRef


class SubrangeType(BaseModel):
    """Constrained numeric subrange: TYPE Pct : INT(0..100); END_TYPE."""

    kind: Literal["subrange"] = "subrange"
    name: str
    folder: str = ""
    base_type: PrimitiveType
    lower_bound: int
    upper_bound: int

    @model_validator(mode="after")
    def _bounds_check(self):
        if self.lower_bound > self.upper_bound:
            raise ValueError(
                f"lower_bound ({self.lower_bound}) must be "
                f"<= upper_bound ({self.upper_bound})"
            )
        return self


TypeDefinition = Annotated[
    Union[StructType, EnumType, UnionType, AliasType, SubrangeType],
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Rebuild models with recursive TypeRef references
# ---------------------------------------------------------------------------

ArrayTypeRef.model_rebuild()
PointerTypeRef.model_rebuild()
ReferenceTypeRef.model_rebuild()
StructMember.model_rebuild()
AliasType.model_rebuild()
