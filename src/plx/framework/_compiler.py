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
from collections.abc import Callable
from dataclasses import dataclass, field

from plx.model.expressions import (
    ArrayAccessExpr,
    BinaryExpr,
    BinaryOp,
    BitAccessExpr,
    CallArg,
    Expression,
    FunctionCallExpr,
    LiteralExpr,
    MemberAccessExpr,
    SystemFlag,
    SystemFlagExpr,
    TypeConversionExpr,
    UnaryExpr,
    UnaryOp,
    VariableRef,
)
from plx.model.statements import (
    Assignment,
    CaseBranch,
    CaseStatement,
    ContinueStatement,
    ExitStatement,
    FBInvocation,
    ForStatement,
    FunctionCallStatement,
    IfBranch,
    IfStatement,
    ReturnStatement,
    Statement,
    WhileStatement,
)
from plx.model.types import (
    NamedTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    TypeRef,
)
from plx.model.variables import Variable

from ._descriptors import VarDirection
from ._types import _resolve_type_ref


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
    ast.BitAnd: BinaryOp.AND,
    ast.BitOr: BinaryOp.OR,
    ast.BitXor: BinaryOp.XOR,
    ast.LShift: BinaryOp.SHL,
    ast.RShift: BinaryOp.SHR,
    ast.Pow: BinaryOp.EXPT,
    ast.FloorDiv: BinaryOp.DIV,
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
# Duration helper
# ---------------------------------------------------------------------------

def _parse_duration_kwarg(
    call_node: ast.Call,
    ctx: CompileContext,
    compiler: ASTCompiler,
) -> Expression:
    """Parse duration kwargs (seconds=, ms=, duration=) from a sentinel call.

    Returns a LiteralExpr for literal values, or passes through variable
    expressions for HMI-configurable durations.
    """
    keywords = {kw.arg: kw.value for kw in call_node.keywords}

    if "duration" in keywords:
        return compiler.compile_expression(keywords["duration"])

    total_ms = 0.0
    has_duration = False

    if "seconds" in keywords:
        val = keywords["seconds"]
        if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
            total_ms += val.value * 1000
            has_duration = True
        else:
            raise CompileError("seconds= must be a numeric literal", call_node, ctx)

    if "ms" in keywords:
        val = keywords["ms"]
        if isinstance(val, ast.Constant) and isinstance(val.value, (int, float)):
            total_ms += val.value
            has_duration = True
        else:
            raise CompileError("ms= must be a numeric literal", call_node, ctx)

    if not has_duration:
        raise CompileError(
            "Timer sentinel requires seconds=, ms=, or duration= argument",
            call_node, ctx,
        )

    # Format as IEC TIME literal
    total_ms_int = int(total_ms)
    if total_ms_int == total_ms:
        if total_ms_int >= 1000 and total_ms_int % 1000 == 0:
            iec_str = f"T#{total_ms_int // 1000}s"
        else:
            iec_str = f"T#{total_ms_int}ms"
    else:
        iec_str = f"T#{total_ms}ms"

    return LiteralExpr(
        value=iec_str,
        data_type=PrimitiveTypeRef(type=PrimitiveType.TIME),
    )


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
# ASTCompiler
# ---------------------------------------------------------------------------

class ASTCompiler:
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
    # Statement compilation
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

    def _compile_assign(self, node: ast.Assign) -> list[Statement]:
        target_node = node.targets[0]
        target = self._compile_target(target_node, node)
        value, pending = self._compile_expr_and_flush(node.value)
        pending.append(Assignment(target=target, value=value))
        return pending

    def _compile_target(self, target_node: ast.expr, stmt_node: ast.stmt) -> Expression:
        """Compile an assignment target (LHS)."""
        if isinstance(target_node, ast.Attribute):
            if isinstance(target_node.value, ast.Name) and target_node.value.id == "self":
                return VariableRef(name=target_node.attr)
            return self.compile_expression(target_node)
        if isinstance(target_node, ast.Name):
            name = target_node.id
            if name not in self.ctx.declared_vars:
                raise CompileError(
                    f"Undeclared variable '{name}'. Use a type annotation "
                    f"(e.g. '{name}: INT = 0') to declare temp variables.",
                    stmt_node, self.ctx,
                )
            return VariableRef(name=name)
        if isinstance(target_node, ast.Subscript):
            return self.compile_expression(target_node)
        raise CompileError(
            f"Unsupported assignment target: {type(target_node).__name__}",
            stmt_node, self.ctx,
        )

    def _compile_augassign(self, node: ast.AugAssign) -> list[Statement]:
        target = self._compile_target(node.target, node)
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise CompileError(
                f"Unsupported augmented assignment operator: {type(node.op).__name__}",
                node, self.ctx,
            )
        rhs, pending = self._compile_expr_and_flush(node.value)
        pending.append(Assignment(
            target=target,
            value=BinaryExpr(op=op, left=target, right=rhs),
        ))
        return pending

    def _compile_annassign(self, node: ast.AnnAssign) -> list[Statement]:
        """Handle type-annotated assignment: ``x: REAL = 0.0``."""
        if not isinstance(node.target, ast.Name):
            raise CompileError(
                "Type annotations are only supported on simple names",
                node, self.ctx,
            )
        name = node.target.id
        type_ref = self._resolve_annotation(node.annotation, node)

        # Register as temp var
        self.ctx.declared_vars[name] = VarDirection.TEMP
        var = Variable(name=name, data_type=type_ref)
        self.ctx.generated_temp_vars.append(var)

        if node.value is not None:
            value, pending = self._compile_expr_and_flush(node.value)
            pending.append(Assignment(
                target=VariableRef(name=name),
                value=value,
            ))
            return pending
        return []

    def _resolve_annotation(self, ann: ast.expr, node: ast.stmt) -> TypeRef:
        """Resolve a type annotation AST node to a TypeRef."""
        result = resolve_annotation(ann, node=node, ctx=self.ctx)
        if result is None:
            raise CompileError("None is not a valid type annotation", node, self.ctx)
        return result

    def _compile_if(self, node: ast.If) -> list[Statement]:
        cond, pending = self._compile_expr_and_flush(node.test)

        if_body = self._compile_body_list(node.body)

        # Extract elif chain
        elsif_branches: list[IfBranch] = []
        else_body: list[Statement] = []
        orelse = node.orelse

        while orelse:
            if len(orelse) == 1 and isinstance(orelse[0], ast.If):
                elif_node = orelse[0]
                elif_cond, elif_pending = self._compile_expr_and_flush(elif_node.test)
                # Prepend any pending FB invocations to the elsif body
                elif_body = elif_pending + self._compile_body_list(elif_node.body)
                elsif_branches.append(IfBranch(condition=elif_cond, body=elif_body))
                orelse = elif_node.orelse
            else:
                else_body = self._compile_body_list(orelse)
                break

        pending.append(IfStatement(
            if_branch=IfBranch(condition=cond, body=if_body),
            elsif_branches=elsif_branches,
            else_body=else_body,
        ))
        return pending

    def _compile_for(self, node: ast.For) -> list[Statement]:
        if not isinstance(node.target, ast.Name):
            raise CompileError(
                "For loop variable must be a simple name",
                node, self.ctx,
            )
        loop_var = node.target.id

        # Only range() is supported
        if not (isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"):
            raise CompileError(
                "For loops only support range() iteration",
                node, self.ctx,
            )

        args = node.iter.args
        if len(args) == 1:
            from_expr = LiteralExpr(value="0")
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[0]),
                right=LiteralExpr(value="1"),
            )
            by_expr = None
        elif len(args) == 2:
            from_expr = self.compile_expression(args[0])
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[1]),
                right=LiteralExpr(value="1"),
            )
            by_expr = None
        elif len(args) == 3:
            from_expr = self.compile_expression(args[0])
            to_expr = BinaryExpr(
                op=BinaryOp.SUB,
                left=self.compile_expression(args[1]),
                right=LiteralExpr(value="1"),
            )
            by_expr = self.compile_expression(args[2])
        else:
            raise CompileError("range() takes 1-3 arguments", node, self.ctx)

        # Register loop var as temp
        if loop_var not in self.ctx.declared_vars:
            self.ctx.declared_vars[loop_var] = VarDirection.TEMP
            self.ctx.generated_temp_vars.append(
                Variable(name=loop_var, data_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
            )

        body = self._compile_body_list(node.body)

        return [ForStatement(
            loop_var=loop_var,
            from_expr=from_expr,
            to_expr=to_expr,
            by_expr=by_expr,
            body=body,
        )]

    def _compile_while(self, node: ast.While) -> list[Statement]:
        cond, pending = self._compile_expr_and_flush(node.test)
        body = self._compile_body_list(node.body)
        pending.append(WhileStatement(condition=cond, body=body))
        return pending

    def _compile_match(self, node: ast.Match) -> list[Statement]:
        selector, pending = self._compile_expr_and_flush(node.subject)

        branches: list[CaseBranch] = []
        else_body: list[Statement] = []

        for case in node.cases:
            pattern = case.pattern

            if isinstance(pattern, ast.MatchAs) and pattern.name is None:
                # Wildcard _ → else
                else_body = self._compile_body_list(case.body)
                continue

            values = self._extract_case_values(pattern, node)
            body = self._compile_body_list(case.body)
            branches.append(CaseBranch(values=values, body=body))

        pending.append(CaseStatement(
            selector=selector,
            branches=branches,
            else_body=else_body,
        ))
        return pending

    def _extract_case_values(self, pattern: ast.pattern, node: ast.stmt) -> list[int]:
        """Extract integer values from a match case pattern."""
        if isinstance(pattern, ast.MatchValue):
            return [self._pattern_to_int(pattern.value, node)]
        if isinstance(pattern, ast.MatchOr):
            values: list[int] = []
            for p in pattern.patterns:
                values.extend(self._extract_case_values(p, node))
            return values
        raise CompileError(
            f"Unsupported match pattern: {type(pattern).__name__}. "
            f"Only integer/enum values and | alternatives are supported.",
            node, self.ctx,
        )

    def _pattern_to_int(self, value_node: ast.expr, node: ast.stmt) -> int:
        """Convert a pattern value node to an integer."""
        if isinstance(value_node, ast.Constant) and isinstance(value_node.value, int):
            return value_node.value
        # Negative constants: UnaryOp(USub, Constant)
        if (isinstance(value_node, ast.UnaryOp)
                and isinstance(value_node.op, ast.USub)
                and isinstance(value_node.operand, ast.Constant)
                and isinstance(value_node.operand.value, int)):
            return -value_node.operand.value
        # Enum-style: SomeEnum.MEMBER → resolve to integer value
        if isinstance(value_node, ast.Attribute) and isinstance(value_node.value, ast.Name):
            enum_name = value_node.value.id
            if enum_name in self.ctx.known_enums:
                member_name = value_node.attr
                members = self.ctx.known_enums[enum_name]
                if member_name not in members:
                    raise CompileError(
                        f"'{member_name}' is not a member of enum '{enum_name}'",
                        node, self.ctx,
                    )
                return members[member_name]
            raise CompileError(
                f"Unknown enum type '{enum_name}'",
                node, self.ctx,
            )
        raise CompileError(
            f"Case pattern must be an integer literal or enum member, "
            f"got {type(value_node).__name__}",
            node, self.ctx,
        )

    def _compile_return(self, node: ast.Return) -> list[Statement]:
        if node.value is not None:
            value, pending = self._compile_expr_and_flush(node.value)
        else:
            value, pending = None, []
        pending.append(ReturnStatement(value=value))
        return pending

    def _compile_break(self, node: ast.Break) -> list[Statement]:
        return [ExitStatement()]

    def _compile_continue(self, node: ast.Continue) -> list[Statement]:
        return [ContinueStatement()]

    def _compile_pass(self, node: ast.Pass) -> list[Statement]:
        return []

    def _compile_expr_stmt(self, node: ast.Expr) -> list[Statement]:
        """Compile an expression used as a statement (e.g. function call)."""
        expr_node = node.value

        # super().logic() — inline parent's compiled logic
        if self._is_super_logic_call(expr_node):
            return self._compile_super_logic(node)

        # Function/FB call as statement
        if isinstance(expr_node, ast.Call):
            result = self._compile_call_as_statement(expr_node)
            if result is not None:
                pending = self._flush_pending()
                pending.append(result)
                return pending

        # If the expression generated pending FB invocations, flush them
        _, pending = self._compile_expr_and_flush(expr_node)
        return pending

    def _compile_call_as_statement(self, call_node: ast.Call) -> Statement | None:
        """Try to compile a call expression as a statement."""
        func = call_node.func

        # self.fb_instance(...) → FBInvocation
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            inv = self._build_fb_invocation(func.attr, call_node)
            if inv is not None:
                return inv

        # Bare function call as statement
        if isinstance(func, ast.Name):
            name = func.id
            # Check if it's a sentinel (should be used as expression, not statement)
            if name in _TIMER_SENTINELS or name in _EDGE_SENTINELS or name in _COUNTER_SENTINELS or name in _SYSTEM_FLAG_SENTINELS:
                raise CompileError(
                    f"{name}() must be used in an expression (e.g. in an assignment or if condition), "
                    f"not as a standalone statement",
                    call_node, self.ctx,
                )
            mapped = _PYTHON_BUILTIN_MAP.get(name, name)
            args = self._compile_call_args(call_node)
            return FunctionCallStatement(function_name=mapped, args=args)

        if isinstance(func, ast.Attribute):
            # member function call as statement — compile as MemberAccess call
            name = func.attr
            args = self._compile_call_args(call_node)
            return FunctionCallStatement(function_name=name, args=args)

        return None

    @staticmethod
    def _is_super_logic_call(node: ast.expr) -> bool:
        """Check if node is ``super().logic()``."""
        return (
            isinstance(node, ast.Call)
            and not node.args
            and not node.keywords
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "logic"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
            and not node.func.value.args
            and not node.func.value.keywords
        )

    def _compile_super_logic(self, node: ast.stmt) -> list[Statement]:
        """Inline the parent class's logic() body.

        Re-compiles the parent's source in the *same* CompileContext so
        that auto-generated instance names (``__ton_0``, etc.) continue
        from where the child left off — no renaming needed.
        """
        import inspect as _inspect
        import textwrap as _textwrap

        if self.ctx.pou_class is None:
            raise CompileError(
                "super().logic() used but no class context available",
                node, self.ctx,
            )

        # Walk MRO to find the first parent with its own logic()
        parent_class = None
        for base in self.ctx.pou_class.__mro__[1:]:
            if base is object:
                continue
            if "logic" in base.__dict__:
                parent_class = base
                break

        if parent_class is None:
            raise CompileError(
                f"super().logic(): no parent class with a logic() method "
                f"found in MRO of {self.ctx.pou_class.__name__}",
                node, self.ctx,
            )

        # Get parent's logic source
        logic_method = parent_class.__dict__["logic"]
        source_lines, start_lineno = _inspect.getsourcelines(logic_method)
        source = _textwrap.dedent("".join(source_lines))
        tree = ast.parse(source)

        if not tree.body or not isinstance(tree.body[0], ast.FunctionDef):
            raise CompileError(
                f"Could not parse {parent_class.__name__}.logic()",
                node, self.ctx,
            )

        # Temporarily set pou_class to the parent so nested
        # super().logic() calls resolve to the grandparent
        saved_class = self.ctx.pou_class
        saved_offset = self.ctx.source_line_offset
        self.ctx.pou_class = parent_class
        self.ctx.source_line_offset = start_lineno - 1

        try:
            stmts = self.compile_body(tree.body[0])
        finally:
            self.ctx.pou_class = saved_class
            self.ctx.source_line_offset = saved_offset

        return stmts

    def _compile_body_list(self, stmts: list[ast.stmt]) -> list[Statement]:
        """Compile a list of AST statements."""
        result: list[Statement] = []
        for s in stmts:
            result.extend(self._compile_statement(s))
        return result

    # Statement handler dispatch table
    _STATEMENT_HANDLERS: dict[type[ast.stmt], Callable[[ASTCompiler, ast.stmt], list[Statement]]] = {
        ast.Assign: _compile_assign,
        ast.AugAssign: _compile_augassign,
        ast.AnnAssign: _compile_annassign,
        ast.If: _compile_if,
        ast.For: _compile_for,
        ast.While: _compile_while,
        ast.Match: _compile_match,
        ast.Return: _compile_return,
        ast.Break: _compile_break,
        ast.Continue: _compile_continue,
        ast.Pass: _compile_pass,
        ast.Expr: _compile_expr_stmt,
    }

    # -----------------------------------------------------------------------
    # Expression compilation
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

    def _compile_constant(self, node: ast.Constant) -> Expression:
        value = node.value
        # bool check before int (bool is subclass of int)
        if isinstance(value, bool):
            return LiteralExpr(value="TRUE" if value else "FALSE",
                               data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        if isinstance(value, int):
            return LiteralExpr(value=str(value))
        if isinstance(value, float):
            return LiteralExpr(value=str(value))
        if isinstance(value, str):
            return LiteralExpr(value=f"'{value}'")
        raise CompileError(f"Unsupported constant type: {type(value).__name__}", node, self.ctx)

    def _compile_name(self, node: ast.Name) -> Expression:
        name = node.id
        # Check for TRUE/FALSE constants
        if name in ("True", "TRUE"):
            return LiteralExpr(value="TRUE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        if name in ("False", "FALSE"):
            return LiteralExpr(value="FALSE", data_type=PrimitiveTypeRef(type=PrimitiveType.BOOL))
        return VariableRef(name=name)

    def _compile_attribute(self, node: ast.Attribute) -> Expression:
        # self.x → VariableRef(name="x")
        if isinstance(node.value, ast.Name) and node.value.id == "self":
            return VariableRef(name=node.attr)
        # Enum literal: MachineState.RUNNING → LiteralExpr
        if isinstance(node.value, ast.Name) and node.value.id in self.ctx.known_enums:
            enum_name = node.value.id
            member_name = node.attr
            members = self.ctx.known_enums[enum_name]
            if member_name not in members:
                raise CompileError(
                    f"'{member_name}' is not a member of enum '{enum_name}'",
                    node, self.ctx,
                )
            return LiteralExpr(
                value=f"{enum_name}#{member_name}",
                data_type=NamedTypeRef(name=enum_name),
            )
        # Bit access: expr.bit5 → BitAccessExpr(target=expr, bit_index=5)
        m = _BIT_ACCESS_RE.match(node.attr)
        if m:
            target = self.compile_expression(node.value)
            return BitAccessExpr(target=target, bit_index=int(m.group(1)))
        # self.a.b → MemberAccessExpr
        struct = self.compile_expression(node.value)
        return MemberAccessExpr(struct=struct, member=node.attr)

    def _compile_binop(self, node: ast.BinOp) -> Expression:
        op = _BINOP_MAP.get(type(node.op))
        if op is None:
            raise CompileError(
                f"Unsupported binary operator: {type(node.op).__name__}",
                node, self.ctx,
            )
        left = self.compile_expression(node.left)
        right = self.compile_expression(node.right)
        return BinaryExpr(op=op, left=left, right=right)

    def _compile_boolop(self, node: ast.BoolOp) -> Expression:
        op = BinaryOp.AND if isinstance(node.op, ast.And) else BinaryOp.OR
        # Left-fold: a and b and c → AND(AND(a, b), c)
        result = self.compile_expression(node.values[0])
        for val in node.values[1:]:
            right = self.compile_expression(val)
            result = BinaryExpr(op=op, left=result, right=right)
        return result

    def _compile_compare(self, node: ast.Compare) -> Expression:
        # a < b < c → (a < b) and (b < c)
        parts: list[Expression] = []
        left = self.compile_expression(node.left)

        for cmp_op, comparator in zip(node.ops, node.comparators):
            op = _CMPOP_MAP.get(type(cmp_op))
            if op is None:
                raise CompileError(
                    f"Unsupported comparison operator: {type(cmp_op).__name__}",
                    node, self.ctx,
                )
            right = self.compile_expression(comparator)
            parts.append(BinaryExpr(op=op, left=left, right=right))
            left = right

        if len(parts) == 1:
            return parts[0]
        # Chain: AND all parts together
        result = parts[0]
        for p in parts[1:]:
            result = BinaryExpr(op=BinaryOp.AND, left=result, right=p)
        return result

    def _compile_unaryop(self, node: ast.UnaryOp) -> Expression:
        operand = self.compile_expression(node.operand)
        if isinstance(node.op, ast.Not):
            return UnaryExpr(op=UnaryOp.NOT, operand=operand)
        if isinstance(node.op, ast.USub):
            return UnaryExpr(op=UnaryOp.NEG, operand=operand)
        if isinstance(node.op, ast.Invert):
            return UnaryExpr(op=UnaryOp.NOT, operand=operand)
        if isinstance(node.op, ast.UAdd):
            return operand  # +x → x
        raise CompileError(
            f"Unsupported unary operator: {type(node.op).__name__}",
            node, self.ctx,
        )

    def _compile_call(self, node: ast.Call) -> Expression:
        """Context-dependent call compilation."""
        func = node.func

        if isinstance(func, ast.Name):
            name = func.id

            # Timer sentinels: delayed, sustained, pulse
            if name in _TIMER_SENTINELS:
                return self._compile_timer_sentinel(name, node)

            # Edge sentinels: rising, falling
            if name in _EDGE_SENTINELS:
                return self._compile_edge_sentinel(name, node)

            # Counter sentinels: count_up, count_down
            if name in _COUNTER_SENTINELS:
                return self._compile_counter_sentinel(name, node)

            # System flag sentinels: first_scan
            if name in _SYSTEM_FLAG_SENTINELS:
                return self._compile_system_flag_sentinel(name, node)

            # range() — error (only valid in for)
            if name == "range":
                raise CompileError(
                    "range() can only be used in a for loop",
                    node, self.ctx,
                )

            # Python builtins → IEC functions
            if name in _PYTHON_BUILTIN_MAP:
                mapped = _PYTHON_BUILTIN_MAP[name]
                args = self._compile_call_args(node)
                return FunctionCallExpr(function_name=mapped, args=args)

            # Type conversion: INT_TO_REAL(x)
            m = _TYPE_CONV_RE.match(name)
            if m:
                source_type_name = m.group(1)
                target_type_name = m.group(2)
                if len(node.args) != 1:
                    raise CompileError(
                        f"Type conversion {name}() takes exactly 1 argument",
                        node, self.ctx,
                    )
                source = self.compile_expression(node.args[0])
                try:
                    target_type: TypeRef = PrimitiveTypeRef(type=PrimitiveType(target_type_name))
                except ValueError:
                    target_type = NamedTypeRef(name=target_type_name)
                return TypeConversionExpr(target_type=target_type, source=source)

            # IEC built-in functions (uppercase)
            if name.upper() in _BUILTIN_FUNCS and name == name.upper():
                args = self._compile_call_args(node)
                return FunctionCallExpr(function_name=name, args=args)

            # Default: generic function call
            args = self._compile_call_args(node)
            return FunctionCallExpr(function_name=name, args=args)

        # self.fb_instance(...) → FBInvocation (as expression)
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "self":
            inv = self._build_fb_invocation(func.attr, node)
            if inv is not None:
                self.ctx.pending_fb_invocations.append(inv)
                return VariableRef(name=func.attr)

        # Other attribute calls
        if isinstance(func, ast.Attribute):
            struct = self.compile_expression(func.value)
            args = self._compile_call_args(node)
            return FunctionCallExpr(
                function_name=func.attr,
                args=[CallArg(value=struct)] + args,
            )

        raise CompileError(
            f"Unsupported call target: {type(func).__name__}",
            node, self.ctx,
        )

    def _compile_timer_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile delayed/sustained/pulse sentinel into TON/TOF/TP."""
        fb_type, input_name, pt_name = _TIMER_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])
        duration = _parse_duration_kwarg(node, self.ctx, self)

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        # Add to generated static vars
        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        # Add FBInvocation to pending
        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs={input_name: signal, pt_name: duration},
        ))

        # Return .Q member access
        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_edge_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile rising/falling sentinel into R_TRIG/F_TRIG."""
        fb_type = _EDGE_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        # Add to generated static vars
        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        # Add FBInvocation to pending
        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs={"CLK": signal},
        ))

        # Return .Q member access
        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_counter_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile count_up/count_down sentinel into CTU/CTD."""
        fb_type, count_input, pv_input, ctrl_input = _COUNTER_SENTINELS[name]

        if not node.args:
            raise CompileError(f"{name}() requires a signal argument", node, self.ctx)

        signal = self.compile_expression(node.args[0])

        # Parse keyword args
        keywords = {kw.arg: kw.value for kw in node.keywords}

        # preset is required
        if "preset" not in keywords:
            raise CompileError(
                f"{name}() requires a preset= argument",
                node, self.ctx,
            )
        preset_node = keywords["preset"]
        if isinstance(preset_node, ast.Constant) and isinstance(preset_node.value, int):
            preset_expr = LiteralExpr(
                value=str(preset_node.value),
                data_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            )
        else:
            preset_expr = self.compile_expression(preset_node)

        instance_name = self.ctx.next_auto_name(fb_type.lower())

        self.ctx.generated_static_vars.append(Variable(
            name=instance_name,
            data_type=NamedTypeRef(name=fb_type),
        ))

        inputs = {count_input: signal, pv_input: preset_expr}

        # Optional reset/load
        ctrl_kwarg = "reset" if name == "count_up" else "load"
        if ctrl_kwarg in keywords:
            inputs[ctrl_input] = self.compile_expression(keywords[ctrl_kwarg])

        self.ctx.pending_fb_invocations.append(FBInvocation(
            instance_name=instance_name,
            fb_type=fb_type,
            inputs=inputs,
        ))

        return MemberAccessExpr(
            struct=VariableRef(name=instance_name),
            member="Q",
        )

    def _compile_system_flag_sentinel(self, name: str, node: ast.Call) -> Expression:
        """Compile first_scan() and other system flag sentinels."""
        if node.args or node.keywords:
            raise CompileError(f"{name}() takes no arguments", node, self.ctx)
        return SystemFlagExpr(flag=_SYSTEM_FLAG_SENTINELS[name])

    def _compile_subscript(self, node: ast.Subscript) -> Expression:
        array = self.compile_expression(node.value)
        # Multi-dimensional: a[i, j] → ast.Tuple in node.slice
        if isinstance(node.slice, ast.Tuple):
            indices = [self.compile_expression(elt) for elt in node.slice.elts]
        else:
            indices = [self.compile_expression(node.slice)]
        return ArrayAccessExpr(array=array, indices=indices)

    def _compile_ifexp(self, node: ast.IfExp) -> Expression:
        """Ternary: ``a if cond else b`` → ``SEL(cond, false_val, true_val)``."""
        cond = self.compile_expression(node.test)
        true_val = self.compile_expression(node.body)
        false_val = self.compile_expression(node.orelse)
        return FunctionCallExpr(
            function_name="SEL",
            args=[
                CallArg(value=cond),
                CallArg(value=false_val),
                CallArg(value=true_val),
            ],
        )

    def _compile_call_args(self, node: ast.Call) -> list[CallArg]:
        """Compile positional and keyword arguments."""
        args: list[CallArg] = []
        for arg in node.args:
            args.append(CallArg(value=self.compile_expression(arg)))
        for kw in node.keywords:
            args.append(CallArg(name=kw.arg, value=self.compile_expression(kw.value)))
        return args

    def _compile_call_kwargs(self, node: ast.Call) -> dict[str, Expression]:
        """Compile keyword arguments into a dict (for FBInvocation inputs)."""
        inputs: dict[str, Expression] = {}
        for kw in node.keywords:
            if kw.arg is None:
                raise CompileError("**kwargs not supported in FB calls", node, self.ctx)
            inputs[kw.arg] = self.compile_expression(kw.value)
        # Positional args are not supported for FB invocations
        if node.args:
            raise CompileError(
                "FB invocations only accept keyword arguments (e.g. self.timer(IN=signal, PT=duration))",
                node, self.ctx,
            )
        return inputs

    # Expression handler dispatch table
    _EXPRESSION_HANDLERS: dict[type[ast.expr], Callable[[ASTCompiler, ast.expr], Expression]] = {
        ast.Constant: _compile_constant,
        ast.Name: _compile_name,
        ast.Attribute: _compile_attribute,
        ast.BinOp: _compile_binop,
        ast.BoolOp: _compile_boolop,
        ast.Compare: _compile_compare,
        ast.UnaryOp: _compile_unaryop,
        ast.Call: _compile_call,
        ast.Subscript: _compile_subscript,
        ast.IfExp: _compile_ifexp,
    }
