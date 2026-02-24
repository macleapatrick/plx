"""Tests for type constructors and _resolve_type_ref."""

import pytest

from plx.framework._types import (
    ARRAY,
    POINTER_TO,
    REFERENCE_TO,
    STRING,
    WSTRING,
    _resolve_type_ref,
)
from plx.model.types import (
    ArrayTypeRef,
    DimensionRange,
    NamedTypeRef,
    PointerTypeRef,
    PrimitiveType,
    PrimitiveTypeRef,
    ReferenceTypeRef,
    StringTypeRef,
)


# ---------------------------------------------------------------------------
# _resolve_type_ref
# ---------------------------------------------------------------------------

class TestResolveTypeRef:
    def test_primitive_type_enum(self):
        result = _resolve_type_ref(PrimitiveType.BOOL)
        assert result == PrimitiveTypeRef(type=PrimitiveType.BOOL)

    def test_primitive_type_ref_passthrough(self):
        ref = PrimitiveTypeRef(type=PrimitiveType.INT)
        assert _resolve_type_ref(ref) is ref

    def test_string_type_ref_passthrough(self):
        ref = StringTypeRef(wide=False, max_length=80)
        assert _resolve_type_ref(ref) is ref

    def test_named_type_ref_passthrough(self):
        ref = NamedTypeRef(name="MyUDT")
        assert _resolve_type_ref(ref) is ref

    def test_array_type_ref_passthrough(self):
        ref = ArrayTypeRef(
            element_type=PrimitiveTypeRef(type=PrimitiveType.INT),
            dimensions=[DimensionRange(lower=0, upper=9)],
        )
        assert _resolve_type_ref(ref) is ref

    def test_pointer_type_ref_passthrough(self):
        ref = PointerTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.DINT))
        assert _resolve_type_ref(ref) is ref

    def test_reference_type_ref_passthrough(self):
        ref = ReferenceTypeRef(target_type=PrimitiveTypeRef(type=PrimitiveType.REAL))
        assert _resolve_type_ref(ref) is ref

    def test_string_to_named_type_ref(self):
        result = _resolve_type_ref("MyFB")
        assert result == NamedTypeRef(name="MyFB")

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError, match="Expected a type"):
            _resolve_type_ref(42)

    def test_invalid_type_none_raises(self):
        with pytest.raises(TypeError, match="Expected a type"):
            _resolve_type_ref(None)


# ---------------------------------------------------------------------------
# ARRAY
# ---------------------------------------------------------------------------

class TestARRAY:
    def test_single_int_dim(self):
        result = ARRAY(PrimitiveType.INT, 10)
        assert isinstance(result, ArrayTypeRef)
        assert result.element_type == PrimitiveTypeRef(type=PrimitiveType.INT)
        assert len(result.dimensions) == 1
        assert result.dimensions[0].lower == 0
        assert result.dimensions[0].upper == 9

    def test_single_tuple_dim(self):
        result = ARRAY(PrimitiveType.REAL, (1, 10))
        assert result.dimensions[0].lower == 1
        assert result.dimensions[0].upper == 10

    def test_multi_dim(self):
        result = ARRAY(PrimitiveType.BOOL, 3, 4)
        assert len(result.dimensions) == 2
        assert result.dimensions[0] == DimensionRange(lower=0, upper=2)
        assert result.dimensions[1] == DimensionRange(lower=0, upper=3)

    def test_mixed_dims(self):
        result = ARRAY(PrimitiveType.DINT, 5, (1, 10))
        assert result.dimensions[0] == DimensionRange(lower=0, upper=4)
        assert result.dimensions[1] == DimensionRange(lower=1, upper=10)

    def test_string_element_type(self):
        result = ARRAY("MyStruct", 5)
        assert result.element_type == NamedTypeRef(name="MyStruct")

    def test_no_dims_raises(self):
        with pytest.raises(ValueError, match="at least one dimension"):
            ARRAY(PrimitiveType.INT)

    def test_zero_size_raises(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(PrimitiveType.INT, 0)

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="must be >= 1"):
            ARRAY(PrimitiveType.INT, -1)

    def test_invalid_dim_type_raises(self):
        with pytest.raises(TypeError, match="Dimension must be"):
            ARRAY(PrimitiveType.INT, "bad")

    def test_nested_array(self):
        inner = ARRAY(PrimitiveType.INT, 5)
        outer = ARRAY(inner, 3)
        assert isinstance(outer.element_type, ArrayTypeRef)


# ---------------------------------------------------------------------------
# STRING / WSTRING
# ---------------------------------------------------------------------------

class TestSTRING:
    def test_default_length(self):
        result = STRING()
        assert isinstance(result, StringTypeRef)
        assert result.wide is False
        assert result.max_length == 255

    def test_custom_length(self):
        result = STRING(80)
        assert result.max_length == 80

    def test_wstring_default(self):
        result = WSTRING()
        assert result.wide is True
        assert result.max_length == 255

    def test_wstring_custom(self):
        result = WSTRING(100)
        assert result.wide is True
        assert result.max_length == 100


# ---------------------------------------------------------------------------
# POINTER_TO / REFERENCE_TO
# ---------------------------------------------------------------------------

class TestPOINTER_TO:
    def test_primitive(self):
        result = POINTER_TO(PrimitiveType.INT)
        assert isinstance(result, PointerTypeRef)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.INT)

    def test_named(self):
        result = POINTER_TO("MyStruct")
        assert result.target_type == NamedTypeRef(name="MyStruct")


class TestREFERENCE_TO:
    def test_primitive(self):
        result = REFERENCE_TO(PrimitiveType.REAL)
        assert isinstance(result, ReferenceTypeRef)
        assert result.target_type == PrimitiveTypeRef(type=PrimitiveType.REAL)

    def test_named(self):
        result = REFERENCE_TO("MyFB")
        assert result.target_type == NamedTypeRef(name="MyFB")
