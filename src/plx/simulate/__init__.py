"""plx simulator — scan-cycle execution of Universal IR.

Entry point::

    from plx.simulate import simulate

    ctx = simulate(MyFB)
    ctx.cmd = True
    ctx.scan()
    assert ctx.running
    ctx.tick(seconds=5)
"""

from __future__ import annotations

from typing import Any

from plx.model.pou import POU
from plx.model.types import EnumType, StructType

from plx.framework._protocols import CompiledDataType, CompiledPOU

from ._context import SimulationContext
from ._values import SimulationError


def simulate(
    target: Any,
    *,
    pous: list[Any] | None = None,
    data_types: list[Any] | None = None,
    scan_period_ms: int = 10,
) -> SimulationContext:
    """Create a simulation context for a POU.

    Parameters
    ----------
    target
        A ``@fb``/``@program``-decorated class (has ``_compiled_pou``)
        or a ``POU`` IR node directly.
    pous
        Additional POU classes or POU IR nodes for nested FB resolution.
    data_types
        ``@struct``/``@enumeration``-decorated classes or TypeDefinition IR
        for type resolution.
    scan_period_ms
        Simulated time advance per scan cycle (default 10ms).

    Returns
    -------
    SimulationContext
        The simulation context with attribute-style variable access.
    """
    # Resolve target POU
    pou = _resolve_pou(target)

    # Build POU registry
    pou_registry: dict[str, POU] = {}
    if pous:
        for p in pous:
            resolved = _resolve_pou(p)
            pou_registry[resolved.name] = resolved

    # Auto-register the target itself
    pou_registry[pou.name] = pou

    # Build data type and enum registries
    data_type_registry: dict[str, StructType | EnumType] = {}
    enum_registry: dict[str, dict[str, int]] = {}
    if data_types:
        for dt in data_types:
            typedef = _resolve_typedef(dt)
            data_type_registry[typedef.name] = typedef
            if isinstance(typedef, EnumType):
                enum_registry[typedef.name] = {
                    m.name: m.value for m in typedef.members if m.value is not None
                }

    return SimulationContext(
        pou=pou,
        pou_registry=pou_registry,
        data_type_registry=data_type_registry,
        enum_registry=enum_registry,
        scan_period_ms=scan_period_ms,
    )


def _resolve_pou(target: Any) -> POU:
    """Resolve a target to a POU IR node."""
    if isinstance(target, POU):
        return target
    if isinstance(target, CompiledPOU):
        return target._compiled_pou
    raise TypeError(
        f"simulate() expects a @fb/@program/@sfc class or POU IR, "
        f"got {type(target).__name__}"
    )


def _resolve_typedef(dt: Any) -> StructType | EnumType:
    """Resolve a data type to a TypeDefinition IR node."""
    if isinstance(dt, (StructType, EnumType)):
        return dt
    if isinstance(dt, CompiledDataType):
        return dt._compiled_type
    raise TypeError(
        f"data_types entries must be @struct/@enumeration classes or TypeDefinition IR, "
        f"got {type(dt).__name__}"
    )


__all__ = ["simulate", "SimulationContext", "SimulationError"]
