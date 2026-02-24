"""Top-level Project container for the Universal IR."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from .hardware import Controller
from .pou import POU
from .task import Task
from .types import TypeDefinition
from .variables import Variable


class GlobalVariableList(BaseModel):
    """A named group of global variables.

    Maps to Beckhoff GVLs, Siemens tag tables, AB controller/program
    scoped tag collections.
    """

    name: str
    folder: str = ""
    description: str = ""
    variables: list[Variable] = []


class LibraryReference(BaseModel):
    """A reference to an external library dependency."""

    name: str
    version: str | None = None
    vendor: str | None = None


class Project(BaseModel):
    name: str
    description: str = ""
    controller: Controller | None = None
    data_types: list[TypeDefinition] = []
    global_variable_lists: list[GlobalVariableList] = []
    pous: list[POU] = []
    tasks: list[Task] = []
    libraries: list[LibraryReference] = []
    metadata: dict[str, Any] = {}
