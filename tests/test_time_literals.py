"""Tests for TIME and LTIME literal helpers."""

from plx.framework import T, LT, TimeLiteral, LTimeLiteral, TIME, LTIME
from plx.model.expressions import LiteralExpr
from plx.model.types import PrimitiveType, PrimitiveTypeRef


# ---------------------------------------------------------------------------
# T() constructor
# ---------------------------------------------------------------------------

class TestT:
    def test_seconds_positional(self):
        assert T(5).to_iec() == "T#5s"

    def test_seconds_keyword(self):
        assert T(seconds=10).to_iec() == "T#10s"

    def test_milliseconds(self):
        assert T(ms=500).to_iec() == "T#500ms"

    def test_microseconds(self):
        assert T(us=250).to_iec() == "T#250us"

    def test_minutes(self):
        assert T(minutes=2).to_iec() == "T#2m"

    def test_hours(self):
        assert T(hours=1).to_iec() == "T#1h"

    def test_composite(self):
        assert T(hours=1, minutes=30, seconds=15, ms=500).to_iec() == "T#1h30m15s500ms"

    def test_minutes_and_seconds(self):
        assert T(minutes=1, seconds=30).to_iec() == "T#1m30s"

    def test_zero(self):
        assert T(0).to_iec() == "T#0s"
        assert T().to_iec() == "T#0s"

    def test_fractional_seconds(self):
        assert T(0.5).to_iec() == "T#500ms"

    def test_fractional_seconds_with_us(self):
        assert T(1.5).to_iec() == "T#1s500ms"

    def test_fractional_ms(self):
        assert T(ms=1.5).to_iec() == "T#1ms500us"

    def test_negative(self):
        assert T(seconds=-5).to_iec() == "T#-5s"

    def test_large_values(self):
        lit = T(hours=24, minutes=59, seconds=59, ms=999)
        assert lit.to_iec() == "T#24h59m59s999ms"

    def test_returns_time_literal(self):
        assert isinstance(T(5), TimeLiteral)


# ---------------------------------------------------------------------------
# TimeLiteral properties
# ---------------------------------------------------------------------------

class TestTimeLiteralProperties:
    def test_total_seconds(self):
        assert T(5).total_seconds == 5.0

    def test_total_ms(self):
        assert T(5).total_ms == 5000.0

    def test_total_us(self):
        assert T(5).total_us == 5_000_000

    def test_total_seconds_composite(self):
        assert T(minutes=1, seconds=30).total_seconds == 90.0

    def test_total_ms_fractional(self):
        assert T(ms=500).total_ms == 500.0


# ---------------------------------------------------------------------------
# TimeLiteral.to_ir()
# ---------------------------------------------------------------------------

class TestTimeLiteralIR:
    def test_produces_literal_expr(self):
        ir = T(5).to_ir()
        assert isinstance(ir, LiteralExpr)

    def test_value_is_iec_string(self):
        ir = T(5).to_ir()
        assert ir.value == "T#5s"

    def test_data_type_is_time(self):
        ir = T(5).to_ir()
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.TIME)

    def test_composite_ir(self):
        ir = T(minutes=1, seconds=30).to_ir()
        assert ir.value == "T#1m30s"
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.TIME)

    def test_ir_serializes(self):
        ir = T(5).to_ir()
        d = ir.model_dump()
        assert d["kind"] == "literal"
        assert d["value"] == "T#5s"


# ---------------------------------------------------------------------------
# TimeLiteral equality and hashing
# ---------------------------------------------------------------------------

class TestTimeLiteralEquality:
    def test_equal(self):
        assert T(5) == T(5)

    def test_not_equal(self):
        assert T(5) != T(10)

    def test_equal_different_construction(self):
        assert T(seconds=90) == T(minutes=1, seconds=30)

    def test_fractional_equals_ms(self):
        assert T(0.5) == T(ms=500)

    def test_hashable(self):
        s = {T(5), T(10), T(5)}
        assert len(s) == 2

    def test_hash_consistency(self):
        assert hash(T(5)) == hash(T(5))

    def test_not_equal_to_other_types(self):
        assert T(5) != 5
        assert T(5) != "T#5s"


# ---------------------------------------------------------------------------
# TimeLiteral repr/str
# ---------------------------------------------------------------------------

class TestTimeLiteralRepr:
    def test_repr(self):
        assert repr(T(5)) == "T#5s"

    def test_str(self):
        assert str(T(minutes=1, seconds=30)) == "T#1m30s"


# ---------------------------------------------------------------------------
# LT() constructor — LTIME
# ---------------------------------------------------------------------------

class TestLT:
    def test_seconds(self):
        assert LT(5).to_iec() == "LTIME#5s"

    def test_milliseconds(self):
        assert LT(ms=100).to_iec() == "LTIME#100ms"

    def test_microseconds(self):
        assert LT(us=250).to_iec() == "LTIME#250us"

    def test_nanoseconds(self):
        assert LT(ns=500).to_iec() == "LTIME#500ns"

    def test_composite_with_ns(self):
        assert LT(seconds=5, ms=100, us=42, ns=15).to_iec() == "LTIME#5s100ms42us15ns"

    def test_zero(self):
        assert LT(0).to_iec() == "LTIME#0s"

    def test_returns_ltime_literal(self):
        assert isinstance(LT(5), LTimeLiteral)


# ---------------------------------------------------------------------------
# LTimeLiteral properties
# ---------------------------------------------------------------------------

class TestLTimeLiteralProperties:
    def test_total_ns(self):
        assert LT(seconds=1).total_ns == 1_000_000_000

    def test_total_us(self):
        assert LT(seconds=1).total_us == 1_000_000.0

    def test_total_ms(self):
        assert LT(seconds=1).total_ms == 1_000.0

    def test_total_seconds(self):
        assert LT(seconds=5).total_seconds == 5.0


# ---------------------------------------------------------------------------
# LTimeLiteral.to_ir()
# ---------------------------------------------------------------------------

class TestLTimeLiteralIR:
    def test_produces_literal_expr(self):
        ir = LT(5).to_ir()
        assert isinstance(ir, LiteralExpr)

    def test_value_is_iec_string(self):
        ir = LT(5).to_ir()
        assert ir.value == "LTIME#5s"

    def test_data_type_is_ltime(self):
        ir = LT(5).to_ir()
        assert ir.data_type == PrimitiveTypeRef(type=PrimitiveType.LTIME)


# ---------------------------------------------------------------------------
# LTimeLiteral equality
# ---------------------------------------------------------------------------

class TestLTimeLiteralEquality:
    def test_equal(self):
        assert LT(5) == LT(5)

    def test_not_equal(self):
        assert LT(5) != LT(10)

    def test_equal_different_construction(self):
        assert LT(seconds=1) == LT(ms=1000)

    def test_not_equal_to_time_literal(self):
        assert T(5) != LT(5)


# ---------------------------------------------------------------------------
# Primitive type constants
# ---------------------------------------------------------------------------

class TestPrimitiveTypeConstants:
    def test_time_is_primitive_type(self):
        assert TIME == PrimitiveType.TIME

    def test_ltime_is_primitive_type(self):
        assert LTIME == PrimitiveType.LTIME

    def test_all_primitive_types_exported(self):
        from plx.framework import (
            BOOL, BYTE, WORD, DWORD, LWORD,
            SINT, INT, DINT, LINT,
            USINT, UINT, UDINT, ULINT,
            REAL, LREAL,
            TIME, LTIME,
            DATE, LDATE, TOD, LTOD, DT, LDT,
            CHAR, WCHAR,
        )
        assert BOOL == PrimitiveType.BOOL
        assert INT == PrimitiveType.INT
        assert REAL == PrimitiveType.REAL
        assert DINT == PrimitiveType.DINT
