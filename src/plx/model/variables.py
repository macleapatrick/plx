"""Variable definitions for the Universal IR.

Variables carry no scope or direction information — that is encoded
structurally by which list a Variable appears in (e.g.
POUInterface.input_vars vs .static_vars, or GlobalVariableList.variables).
"""

from __future__ import annotations

from pydantic import BaseModel

from .types import TypeRef


class Variable(BaseModel):
    """A named, typed data element."""

    name: str
    data_type: TypeRef
    initial_value: str | None = None
    address: str | None = None
    description: str = ""
    constant: bool = False
    retain: bool = False
    persistent: bool = False
