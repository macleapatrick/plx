"""Program Organization Units for the Universal IR."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, model_validator

from .sfc import SFCBody
from .statements import Statement
from .types import TypeRef
from .variables import Variable


def _check_body_exclusivity(networks: list, sfc_body: object | None, context: str) -> None:
    """Shared validation: at most one body type (networks or sfc_body)."""
    bodies = sum([bool(networks), sfc_body is not None])
    if bodies > 1:
        raise ValueError(
            f"{context} must have at most one body type "
            f"(networks or sfc_body)"
        )


class POUType(str, Enum):
    PROGRAM = "PROGRAM"
    FUNCTION_BLOCK = "FUNCTION_BLOCK"
    FUNCTION = "FUNCTION"
    INTERFACE = "INTERFACE"


class AccessSpecifier(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    PROTECTED = "PROTECTED"
    INTERNAL = "INTERNAL"


class Language(str, Enum):
    """IEC 61131-3 programming language for POU body."""
    ST = "ST"
    LD = "LD"
    FBD = "FBD"


class Network(BaseModel):
    """A single network / rung of logic."""

    label: str | None = None
    comment: str | None = None
    statements: list[Statement] = []


class POUInterface(BaseModel):
    """The variable interface of a POU, Method, or similar code unit.

    Each list encodes the variable's role structurally — Variables carry
    no redundant direction/scope enums.
    """

    input_vars: list[Variable] = []
    output_vars: list[Variable] = []
    inout_vars: list[Variable] = []
    static_vars: list[Variable] = []
    temp_vars: list[Variable] = []
    constant_vars: list[Variable] = []


class PropertyAccessor(BaseModel):
    """Getter or setter body for a Property."""

    local_vars: list[Variable] = []
    networks: list[Network] = []


class Property(BaseModel):
    """A property on a FUNCTION_BLOCK (OOP extension)."""

    name: str
    data_type: TypeRef
    access: AccessSpecifier = AccessSpecifier.PUBLIC
    getter: PropertyAccessor | None = None
    setter: PropertyAccessor | None = None


class Method(BaseModel):
    """A method on a FUNCTION_BLOCK (OOP extension)."""

    name: str
    language: Language | None = None
    return_type: TypeRef | None = None
    access: AccessSpecifier = AccessSpecifier.PUBLIC
    interface: POUInterface = POUInterface()
    networks: list[Network] = []
    sfc_body: SFCBody | None = None

    @model_validator(mode="after")
    def _body_exclusivity(self) -> Self:
        _check_body_exclusivity(self.networks, self.sfc_body, "Method")
        return self


class POUAction(BaseModel):
    """A named action on a POU.

    Actions execute in the parent POU's variable scope — they have
    direct access to all parent variables with no parameter passing.
    Used standalone or referenced by SFC steps via action qualifiers.
    """

    name: str
    body: list[Network] = []


class POU(BaseModel):
    """Program Organization Unit.

    For INTERFACE POUs, only *methods* and *properties* are meaningful;
    *networks*, *sfc_body*, and *interface* are unused.
    """

    pou_type: POUType
    name: str
    folder: str = ""
    language: Language | None = None
    return_type: TypeRef | None = None
    interface: POUInterface = POUInterface()
    networks: list[Network] = []
    sfc_body: SFCBody | None = None
    actions: list[POUAction] = []
    methods: list[Method] = []
    properties: list[Property] = []
    extends: str | None = None
    implements: list[str] = []

    @model_validator(mode="after")
    def _body_exclusivity(self) -> Self:
        _check_body_exclusivity(self.networks, self.sfc_body, "POU")
        return self
