"""Compilation protocols for framework-decorated classes.

These ``@runtime_checkable`` protocols replace scattered ``hasattr`` checks
with explicit ``isinstance`` tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from plx.model.pou import POU
from plx.model.project import GlobalVariableList
from plx.model.types import TypeDefinition


@runtime_checkable
class CompiledPOU(Protocol):
    """A class decorated with ``@fb``, ``@program``, ``@function``, or ``@sfc``."""

    _compiled_pou: POU

    def compile(self) -> POU: ...


@runtime_checkable
class CompiledDataType(Protocol):
    """A class decorated with ``@struct`` or ``@enumeration``."""

    _compiled_type: TypeDefinition

    def compile(self) -> TypeDefinition: ...


@runtime_checkable
class CompiledGlobalVarList(Protocol):
    """A class decorated with ``@global_vars``."""

    _compiled_gvl: GlobalVariableList

    def compile(self) -> GlobalVariableList: ...


@runtime_checkable
class CompiledEnum(CompiledDataType, Protocol):
    """A class decorated with ``@enumeration``."""

    _enum_values: dict[str, int]
