"""Hardware configuration for the Universal IR.

Deliberately minimal — the universal IR only models what the
programming layer needs: I/O points and their variable mappings.
Detailed topology (rack/slot, EtherCAT chains, PROFINET subnets)
lives in vendor IRs.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .types import TypeRef


class IODirection(str, Enum):
    INPUT = "INPUT"
    OUTPUT = "OUTPUT"


class IOPoint(BaseModel):
    """A single I/O point that maps to a PLC variable."""

    address: str
    data_type: TypeRef
    direction: IODirection
    description: str = ""
    mapped_variable: str | None = None


class Module(BaseModel):
    """An I/O module (simplified — no rack/slot topology)."""

    name: str
    module_type: str = ""
    model_number: str = ""
    io_points: list[IOPoint] = []


class Controller(BaseModel):
    name: str
    model: str = ""
    vendor: str = ""
    modules: list[Module] = []
