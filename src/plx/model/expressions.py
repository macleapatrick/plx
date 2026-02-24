"""Expression AST nodes for the Universal IR."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field

from .types import TypeRef


class SystemFlag(str, Enum):
    FIRST_SCAN = "first_scan"


class SystemFlagExpr(BaseModel):
    """Reference to a system-level PLC flag (e.g. first scan)."""

    kind: Literal["system_flag"] = "system_flag"
    flag: SystemFlag


class BinaryOp(str, Enum):
    ADD = "ADD"
    SUB = "SUB"
    MUL = "MUL"
    DIV = "DIV"
    MOD = "MOD"
    AND = "AND"
    OR = "OR"
    XOR = "XOR"
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"
    SHL = "SHL"
    SHR = "SHR"
    ROL = "ROL"
    ROR = "ROR"
    EXPT = "EXPT"


class UnaryOp(str, Enum):
    NEG = "NEG"
    NOT = "NOT"


class LiteralExpr(BaseModel):
    """A typed constant value (e.g. TRUE, 42, 3.14, T#5s)."""

    kind: Literal["literal"] = "literal"
    value: str
    data_type: TypeRef | None = None


class VariableRef(BaseModel):
    """Reference to a variable by name."""

    kind: Literal["variable_ref"] = "variable_ref"
    name: str


class BinaryExpr(BaseModel):
    kind: Literal["binary"] = "binary"
    op: BinaryOp
    left: Expression
    right: Expression


class UnaryExpr(BaseModel):
    kind: Literal["unary"] = "unary"
    op: UnaryOp
    operand: Expression


class CallArg(BaseModel):
    """A single argument in a function/FB call.

    Positional if *name* is None, named otherwise.
    """

    name: str | None = None
    value: Expression


class FunctionCallExpr(BaseModel):
    """Inline function call that returns a value."""

    kind: Literal["function_call"] = "function_call"
    function_name: str
    args: list[CallArg] = []


class ArrayAccessExpr(BaseModel):
    """Array subscript: arr[i] or arr[i, j]."""

    kind: Literal["array_access"] = "array_access"
    array: Expression
    indices: list[Expression]


class MemberAccessExpr(BaseModel):
    """Struct/FB member access: expr.member."""

    kind: Literal["member_access"] = "member_access"
    struct: Expression
    member: str


class BitAccessExpr(BaseModel):
    """Bit-level access on an integer/word variable: var.bit5."""

    kind: Literal["bit_access"] = "bit_access"
    target: Expression
    bit_index: int


class TypeConversionExpr(BaseModel):
    """Explicit type conversion: INT_TO_REAL(x)."""

    kind: Literal["type_conversion"] = "type_conversion"
    target_type: TypeRef
    source: Expression


Expression = Annotated[
    Union[
        LiteralExpr,
        VariableRef,
        BinaryExpr,
        UnaryExpr,
        FunctionCallExpr,
        ArrayAccessExpr,
        MemberAccessExpr,
        BitAccessExpr,
        TypeConversionExpr,
        SystemFlagExpr,
    ],
    Field(discriminator="kind"),
]

# Rebuild models with recursive Expression references.
BinaryExpr.model_rebuild()
UnaryExpr.model_rebuild()
CallArg.model_rebuild()
FunctionCallExpr.model_rebuild()
ArrayAccessExpr.model_rebuild()
MemberAccessExpr.model_rebuild()
BitAccessExpr.model_rebuild()
TypeConversionExpr.model_rebuild()
SystemFlagExpr.model_rebuild()
