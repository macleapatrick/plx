"""Tests for AST compiler — error handling and rejected nodes."""

import ast
import textwrap

import pytest

from conftest import compile_stmts, compile_expr

from plx.framework._compiler import ASTCompiler, CompileContext, CompileError
from plx.framework._descriptors import VarDirection


# ---------------------------------------------------------------------------
# Rejected statement nodes
# ---------------------------------------------------------------------------

class TestRejectedStatements:
    def test_function_def(self):
        with pytest.raises(CompileError, match="Function definitions"):
            compile_stmts("def foo(): pass")

    def test_class_def(self):
        with pytest.raises(CompileError, match="Class definitions"):
            compile_stmts("class Foo: pass")

    def test_delete(self):
        with pytest.raises(CompileError, match="del statements"):
            compile_stmts("del x")

    def test_with(self):
        with pytest.raises(CompileError, match="with statements"):
            compile_stmts("with open('f') as f: pass")

    def test_raise(self):
        with pytest.raises(CompileError, match="raise statements"):
            compile_stmts("raise ValueError()")

    def test_try(self):
        with pytest.raises(CompileError, match="try/except"):
            compile_stmts("""\
try:
    pass
except:
    pass
""")

    def test_assert(self):
        with pytest.raises(CompileError, match="assert statements"):
            compile_stmts("assert True")

    def test_import(self):
        with pytest.raises(CompileError, match="import statements"):
            compile_stmts("import os")

    def test_import_from(self):
        with pytest.raises(CompileError, match="import statements"):
            compile_stmts("from os import path")

    def test_global(self):
        with pytest.raises(CompileError, match="global statements"):
            compile_stmts("global x")

    def test_nonlocal(self):
        # nonlocal requires an enclosing scope, so wrap it
        with pytest.raises(CompileError):
            source = textwrap.dedent("""\
def outer():
    x = 1
    def logic(self):
        nonlocal x
""")
            tree = ast.parse(source)
            # Extract the inner function
            inner = tree.body[0].body[1]
            ctx = CompileContext()
            compiler = ASTCompiler(ctx)
            compiler.compile_body(inner)


# ---------------------------------------------------------------------------
# Rejected expression nodes
# ---------------------------------------------------------------------------

class TestRejectedExpressions:
    def test_lambda(self):
        with pytest.raises(CompileError, match="Lambda"):
            compile_expr("lambda x: x")

    def test_dict(self):
        with pytest.raises(CompileError, match="Dict"):
            compile_expr("{'a': 1}")

    def test_set(self):
        with pytest.raises(CompileError, match="Set"):
            compile_expr("{1, 2, 3}")

    def test_list(self):
        with pytest.raises(CompileError, match="List"):
            compile_expr("[1, 2, 3]")

    def test_tuple(self):
        with pytest.raises(CompileError, match="Tuple"):
            compile_expr("(1, 2)")

    def test_list_comp(self):
        with pytest.raises(CompileError, match="List comprehension"):
            compile_expr("[x for x in range(10)]")

    def test_dict_comp(self):
        with pytest.raises(CompileError, match="Dict comprehension"):
            compile_expr("{k: v for k, v in items}")

    def test_set_comp(self):
        with pytest.raises(CompileError, match="Set comprehension"):
            compile_expr("{x for x in items}")

    def test_generator_exp(self):
        with pytest.raises(CompileError, match="Generator"):
            compile_expr("sum(x for x in items)")

    def test_fstring(self):
        with pytest.raises(CompileError, match="f-string"):
            compile_expr("f'hello {x}'")

    def test_walrus(self):
        with pytest.raises(CompileError, match="Walrus"):
            compile_expr("(x := 5)")


# ---------------------------------------------------------------------------
# Specific error cases
# ---------------------------------------------------------------------------

class TestSpecificErrors:
    def test_range_outside_for(self):
        with pytest.raises(CompileError, match="range.*for loop"):
            compile_expr("range(10)")

    def test_for_non_range(self):
        with pytest.raises(CompileError, match="range"):
            compile_stmts("""\
for x in items:
    self.y = x
""")

    def test_for_non_name_target(self):
        with pytest.raises(CompileError, match="simple name"):
            compile_stmts("""\
for a, b in range(10):
    pass
""")

    def test_type_conv_wrong_arg_count(self):
        with pytest.raises(CompileError, match="exactly 1 argument"):
            compile_expr("INT_TO_REAL(a, b)")

    def test_sentinel_as_statement(self):
        with pytest.raises(CompileError, match="must be used in an expression"):
            compile_stmts("delayed(self.input, seconds=5)")

    def test_sentinel_no_signal(self):
        with pytest.raises(CompileError, match="requires a signal"):
            compile_expr("delayed()")

    def test_sentinel_no_duration(self):
        with pytest.raises(CompileError, match="requires seconds"):
            ctx = CompileContext()
            stmts = compile_stmts("self.x = delayed(self.input)", ctx)

    def test_rising_no_signal(self):
        with pytest.raises(CompileError, match="requires a signal"):
            compile_expr("rising()")

    def test_compile_error_has_location(self):
        ctx = CompileContext(source_file="test.py", source_line_offset=10)
        with pytest.raises(CompileError, match="test.py"):
            compile_stmts("def foo(): pass", ctx)

    def test_fb_positional_args_rejected(self):
        ctx = CompileContext(
            declared_vars={"timer": VarDirection.STATIC},
            static_var_types={"timer": NamedTypeRef(name="TON")},
        )
        with pytest.raises(CompileError, match="keyword arguments"):
            compile_stmts("self.timer(self.input, self.preset)", ctx)


from plx.model.types import NamedTypeRef


# ---------------------------------------------------------------------------
# MatMult operator rejection (#6)
# ---------------------------------------------------------------------------

class TestMatMultRejected:
    def test_matmult_raises(self):
        """@ operator (MatMult) must be rejected in logic()."""
        ctx = CompileContext(declared_vars={"a": VarDirection.STATIC, "b": VarDirection.STATIC})
        with pytest.raises(CompileError, match="Unsupported binary operator"):
            compile_stmts("self.a = self.a @ self.b", ctx)
