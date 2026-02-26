"""AST compiler: transforms Python AST from logic() into IR nodes.

This module is the core of the framework — it walks a Python AST and
emits Universal IR expression and statement nodes.  The source is parsed
(via ``ast.parse``), never executed.

Key concepts:

- **CompileContext**: carries variable metadata and accumulates generated
  variables (FB instances, temp vars) during compilation.
- **ASTCompiler**: dispatch-table compiler that maps Python AST node
  types to handler methods.
- **Sentinel functions**: ``delayed``, ``rising``, ``falling``,
  ``sustained``, ``pulse``, ``count_up``, ``count_down`` — importable
  functions whose bodies raise ``RuntimeError``.  The AST compiler
  recognises them by name and expands them to FBInvocation + instance
  variables.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from plx.model.expressions import (
    BinaryOp,
    Expression,
    SystemFlag,
)
from plx.model.statements import (
    FBInvocation,
    Statement,
)
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    TypeRef,
)
from plx.model.variables import Variable

from ._descriptors import VarDirection


# ---------------------------------------------------------------------------
# CompileError
# ---------------------------------------------------------------------------

class CompileError(Exception):
    """Error during AST compilation with source location."""

    def __init__(self, message: str, node: ast.AST | None = None, ctx: CompileContext | None = None):
        self.source_file = "<unknown>"
        self.source_line: int | None = None
        if node is not None and ctx is not None:
            self.source_file = ctx.source_file
            lineno = getattr(node, "lineno", None)
            if lineno is not None:
                self.source_line = lineno + ctx.source_line_offset
        loc = ""
        if self.source_line is not None:
            loc = f" ({self.source_file}:{self.source_line})"
        super().__init__(f"{message}{loc}")


# ---------------------------------------------------------------------------
# CompileContext
# ---------------------------------------------------------------------------

@dataclass
class CompileContext:
    """Mutable state carried through compilation."""

    declared_vars: dict[str, VarDirection] = field(default_factory=dict)
    """name -> direction (input/output/static/inout/temp)"""

    static_var_types: dict[str, TypeRef] = field(default_factory=dict)
    """name -> TypeRef for static vars (used for FB call resolution)"""

    generated_static_vars: list[Variable] = field(default_factory=list)
    """Auto-created FB instances (TON, R_TRIG, etc.)"""

    generated_temp_vars: list[Variable] = field(default_factory=list)
    """Discovered temp vars from type annotations"""

    pending_fb_invocations: list[Statement] = field(default_factory=list)
    """FBInvocations to flush before the next statement"""

    pou_class: type | None = None
    """The class being compiled (needed for super().logic() resolution)"""

    known_enums: dict[str, dict[str, int]] = field(default_factory=dict)
    """enum_name -> {member_name: int_value} for enum literal resolution"""

    source_line_offset: int = 0
    source_file: str = "<unknown>"
    _auto_counter: int = 0

    def next_auto_name(self, prefix: str) -> str:
        """Generate a unique instance name like ``__ton_0``."""
        name = f"__{prefix}_{self._auto_counter}"
        self._auto_counter += 1
        return name


# ---------------------------------------------------------------------------
# Sentinel functions
# ---------------------------------------------------------------------------
# These exist for IDE autocompletion / linting.  The AST compiler
# recognises them by name and never calls them.

def delayed(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None) -> bool:
    """TON (on-delay timer).  Recognised by the AST compiler."""
    raise RuntimeError("delayed() is a compile-time sentinel — do not call directly")


def sustained(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None) -> bool:
    """TOF (off-delay timer).  Recognised by the AST compiler."""
    raise RuntimeError("sustained() is a compile-time sentinel — do not call directly")


def pulse(signal: object, *, seconds: int | float = 0, ms: int | float = 0, duration: object = None) -> bool:
    """TP (pulse timer).  Recognised by the AST compiler."""
    raise RuntimeError("pulse() is a compile-time sentinel — do not call directly")


def rising(signal: object) -> bool:
    """R_TRIG (rising edge detect).  Recognised by the AST compiler."""
    raise RuntimeError("rising() is a compile-time sentinel — do not call directly")


def falling(signal: object) -> bool:
    """F_TRIG (falling edge detect).  Recognised by the AST compiler."""
    raise RuntimeError("falling() is a compile-time sentinel — do not call directly")


def count_up(signal: object, *, preset: int = 0, reset: object = None) -> bool:
    """CTU (count up).  Recognised by the AST compiler."""
    raise RuntimeError("count_up() is a compile-time sentinel — do not call directly")


def count_down(signal: object, *, preset: int = 0, load: object = None) -> bool:
    """CTD (count down).  Recognised by the AST compiler."""
    raise RuntimeError("count_down() is a compile-time sentinel — do not call directly")


# ---------------------------------------------------------------------------
# AST operator maps
# ---------------------------------------------------------------------------

_BINOP_MAP: dict[type, BinaryOp] = {
    ast.Add: BinaryOp.ADD,
    ast.Sub: BinaryOp.SUB,
    ast.Mult: BinaryOp.MUL,
    ast.Div: BinaryOp.DIV,
    ast.Mod: BinaryOp.MOD,
    ast.BitXor: BinaryOp.XOR,
    ast.LShift: BinaryOp.SHL,
    ast.RShift: BinaryOp.SHR,
    ast.Pow: BinaryOp.EXPT,
}

_REJECTED_BINOP_MESSAGES: dict[type, str] = {
    ast.FloorDiv: "Floor division (//) is not supported — PLC division has no floor variant. Use / instead.",
    ast.BitAnd: "Bitwise & is not supported in logic(). Use 'and' for logical AND.",
    ast.BitOr: "Bitwise | is not supported in logic(). Use 'or' for logical OR.",
}

_CMPOP_MAP: dict[type, BinaryOp] = {
    ast.Eq: BinaryOp.EQ,
    ast.NotEq: BinaryOp.NE,
    ast.Gt: BinaryOp.GT,
    ast.GtE: BinaryOp.GE,
    ast.Lt: BinaryOp.LT,
    ast.LtE: BinaryOp.LE,
}

_TYPE_CONV_RE = re.compile(r"^([A-Z_][A-Za-z0-9_]*)_TO_([A-Z_][A-Za-z0-9_]*)$")
_BIT_ACCESS_RE = re.compile(r"^bit(\d+)$")

_BUILTIN_FUNCS = frozenset({
    "ABS", "SQRT", "LN", "LOG", "EXP", "SIN", "COS", "TAN",
    "ASIN", "ACOS", "ATAN", "ATAN2",
    "MIN", "MAX", "LIMIT", "SEL", "MUX",
    "SHL", "SHR", "ROL", "ROR",
    "TRUNC", "ROUND",
    "LEN", "LEFT", "RIGHT", "MID", "CONCAT", "FIND", "REPLACE", "INSERT", "DELETE",
    "AND", "OR", "XOR", "NOT",
})

_PYTHON_BUILTIN_MAP: dict[str, str] = {
    "abs": "ABS",
    "min": "MIN",
    "max": "MAX",
    "len": "LEN",
}

# Sentinel function names
_TIMER_SENTINELS = {
    "delayed": ("TON", "IN", "PT"),
    "sustained": ("TOF", "IN", "PT"),
    "pulse": ("TP", "IN", "PT"),
}

_EDGE_SENTINELS = {
    "rising": "R_TRIG",
    "falling": "F_TRIG",
}

_COUNTER_SENTINELS = {
    "count_up": ("CTU", "CU", "PV", "RESET"),
    "count_down": ("CTD", "CD", "PV", "LOAD"),
}

_SYSTEM_FLAG_SENTINELS = {
    "first_scan": SystemFlag.FIRST_SCAN,
}

# Complete set of rejected AST node types
_REJECTED_NODES: dict[type, str] = {
    ast.FunctionDef: "Function definitions are not allowed in PLC logic",
    ast.AsyncFunctionDef: "Async functions are not allowed in PLC logic",
    ast.ClassDef: "Class definitions are not allowed in PLC logic",
    ast.Delete: "del statements are not allowed in PLC logic",
    ast.With: "with statements are not allowed in PLC logic",
    ast.AsyncWith: "async with statements are not allowed in PLC logic",
    ast.AsyncFor: "async for statements are not allowed in PLC logic",
    ast.Raise: "raise statements are not allowed in PLC logic",
    ast.Try: "try/except statements are not allowed in PLC logic",
    ast.Assert: "assert statements are not allowed in PLC logic",
    ast.Import: "import statements are not allowed in PLC logic",
    ast.ImportFrom: "import statements are not allowed in PLC logic",
    ast.Global: "global statements are not allowed in PLC logic",
    ast.Nonlocal: "nonlocal statements are not allowed in PLC logic",
    ast.NamedExpr: "Walrus operator (:=) is not allowed in PLC logic",
    ast.Lambda: "Lambda expressions are not allowed in PLC logic",
    ast.Dict: "Dict literals are not allowed in PLC logic",
    ast.Set: "Set literals are not allowed in PLC logic",
    ast.List: "List literals are not allowed in PLC logic",
    ast.Tuple: "Tuple literals are not allowed in PLC logic",
    ast.ListComp: "List comprehensions are not allowed in PLC logic",
    ast.SetComp: "Set comprehensions are not allowed in PLC logic",
    ast.DictComp: "Dict comprehensions are not allowed in PLC logic",
    ast.GeneratorExp: "Generator expressions are not allowed in PLC logic",
    ast.Await: "await expressions are not allowed in PLC logic",
    ast.Yield: "yield expressions are not allowed in PLC logic",
    ast.YieldFrom: "yield from expressions are not allowed in PLC logic",
    ast.FormattedValue: "f-string expressions are not allowed in PLC logic",
    ast.JoinedStr: "f-strings are not allowed in PLC logic",
    ast.Starred: "Star unpacking is not allowed in PLC logic",
    ast.Slice: "Slice operations are not allowed in PLC logic",
}

# Also reject TryStar if available (Python 3.11+)
if hasattr(ast, "TryStar"):
    _REJECTED_NODES[ast.TryStar] = "try/except* statements are not allowed in PLC logic"


# ---------------------------------------------------------------------------
# Annotation resolution (shared by compiler + decorators)
# ---------------------------------------------------------------------------

def resolve_annotation(
    ann: ast.expr,
    *,
    node: ast.AST | None = None,
    ctx: CompileContext | None = None,
    location_hint: str = "",
) -> TypeRef | None:
    """Resolve a type annotation AST node to a TypeRef.

    Handles ``ast.Name``, ``ast.Attribute``, and ``ast.Constant(None)`` → None.
    Used by both the ASTCompiler and ``_decorators.py``.
    """
    if isinstance(ann, ast.Name):
        try:
            return PrimitiveTypeRef(type=PrimitiveType(ann.id))
        except ValueError:
            return NamedTypeRef(name=ann.id)
    if isinstance(ann, ast.Attribute):
        return NamedTypeRef(name=ann.attr)
    if isinstance(ann, ast.Constant) and ann.value is None:
        return None
    msg = f"Unsupported type annotation: {ast.dump(ann)}"
    if location_hint:
        msg = f"{msg} ({location_hint})"
    raise CompileError(msg, node, ctx)


# ---------------------------------------------------------------------------
# ASTCompiler — composed from mixins
# ---------------------------------------------------------------------------
# Import mixins after all module-level names are defined (they import from
# this module).

from ._compiler_sentinels import _SentinelMixin    # noqa: E402
from ._compiler_expressions import _ExpressionMixin  # noqa: E402
from ._compiler_statements import _StatementMixin    # noqa: E402


class ASTCompiler(_StatementMixin, _ExpressionMixin, _SentinelMixin):
    """Compiles Python AST nodes into Universal IR nodes."""

    def __init__(self, ctx: CompileContext) -> None:
        self.ctx = ctx

    # -----------------------------------------------------------------------
    # Public entry points
    # -----------------------------------------------------------------------

    def compile_statements(self, nodes: list[ast.stmt]) -> list[Statement]:
        """Compile a list of AST statement nodes into IR statements."""
        stmts: list[Statement] = []
        for node in nodes:
            stmts.extend(self._compile_statement(node))
        return stmts

    def compile_body(self, func_def: ast.FunctionDef) -> list[Statement]:
        """Compile a function body into a list of IR statements."""
        return self.compile_statements(func_def.body)

    # -----------------------------------------------------------------------
    # Statement dispatch
    # -----------------------------------------------------------------------

    def _compile_statement(self, node: ast.stmt) -> list[Statement]:
        """Compile a single AST statement node into IR statements."""
        # Check rejected nodes first
        if type(node) in _REJECTED_NODES:
            raise CompileError(_REJECTED_NODES[type(node)], node, self.ctx)

        handler = self._STATEMENT_HANDLERS.get(type(node))
        if handler is None:
            raise CompileError(
                f"Unsupported Python syntax: {type(node).__name__}. "
                f"PLC logic supports a subset of Python.",
                node, self.ctx,
            )
        result = handler(self, node)
        assert not self.ctx.pending_fb_invocations, (
            f"Unflushed pending_fb_invocations after {type(node).__name__}. "
            f"Handler must call _flush_pending()."
        )
        return result

    # -----------------------------------------------------------------------
    # Expression dispatch
    # -----------------------------------------------------------------------

    def compile_expression(self, node: ast.expr) -> Expression:
        """Compile a single AST expression node into an IR expression."""
        # Check rejected nodes
        if type(node) in _REJECTED_NODES:
            raise CompileError(_REJECTED_NODES[type(node)], node, self.ctx)

        handler = self._EXPRESSION_HANDLERS.get(type(node))
        if handler is None:
            raise CompileError(
                f"Unsupported Python syntax: {type(node).__name__}. "
                f"PLC logic supports a subset of Python.",
                node, self.ctx,
            )
        return handler(self, node)

    # -----------------------------------------------------------------------
    # Shared utilities (used by multiple mixins)
    # -----------------------------------------------------------------------

    def _flush_pending(self) -> list[Statement]:
        """Flush pending FB invocations."""
        pending = list(self.ctx.pending_fb_invocations)
        self.ctx.pending_fb_invocations.clear()
        return pending

    def _compile_expr_and_flush(self, node: ast.expr) -> tuple[Expression, list[Statement]]:
        """Compile an expression and flush any pending FB invocations."""
        expr = self.compile_expression(node)
        pre = self._flush_pending()
        return expr, pre

    def _build_fb_invocation(self, instance_name: str, call_node: ast.Call) -> FBInvocation | None:
        """Build an FBInvocation if *instance_name* is a known static FB instance."""
        if instance_name not in self.ctx.static_var_types:
            return None
        type_ref = self.ctx.static_var_types[instance_name]
        fb_type = type_ref.name if isinstance(type_ref, NamedTypeRef) else None
        inputs = self._compile_call_kwargs(call_node)
        return FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        )
