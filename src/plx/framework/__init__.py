"""plx Python Framework — public API.

Users import everything from this single flat namespace::

    from plx.framework import fb, input_var, BOOL, REAL, TIME, T, delayed
"""

from ._types import (
    # Primitive type constants
    BOOL,
    BYTE,
    CHAR,
    DATE,
    DINT,
    DWORD,
    DT,
    INT,
    LDATE,
    LINT,
    LREAL,
    LTIME,
    LTOD,
    LWORD,
    LDT,
    REAL,
    SINT,
    TIME,
    TOD,
    UDINT,
    UINT,
    ULINT,
    USINT,
    WCHAR,
    WORD,
    # Duration literal constructors
    T,
    LT,
    # Duration literal types (for isinstance checks / type annotations)
    TimeLiteral,
    LTimeLiteral,
    # Type constructors
    ARRAY,
    STRING,
    WSTRING,
    POINTER_TO,
    REFERENCE_TO,
    # System flag sentinels
    first_scan,
)

from ._descriptors import (
    VarDirection,
    input_var,
    output_var,
    static_var,
    inout_var,
    temp_var,
    constant_var,
)

from ._decorators import (
    fb,
    program,
    function,
    method,
)

from ._sfc import (
    sfc,
    step,
    transition,
)

from ._data_types import (
    struct,
    enumeration,
)

from ._global_vars import (
    global_vars,
    global_var,
)

from ._protocols import (
    CompiledPOU,
    CompiledDataType,
    CompiledGlobalVarList,
)

from ._compiler import (
    delayed,
    rising,
    falling,
    sustained,
    pulse,
    count_up,
    count_down,
    CompileError,
)

from ._discover import (
    discover,
    DiscoveryResult,
)

from ._project import (
    project,
    task,
)

__all__ = [
    # Primitive type constants
    "BOOL",
    "BYTE",
    "CHAR",
    "DATE",
    "DINT",
    "DWORD",
    "DT",
    "INT",
    "LDATE",
    "LINT",
    "LREAL",
    "LTIME",
    "LTOD",
    "LWORD",
    "LDT",
    "REAL",
    "SINT",
    "TIME",
    "TOD",
    "UDINT",
    "UINT",
    "ULINT",
    "USINT",
    "WCHAR",
    "WORD",
    # Duration literals
    "T",
    "LT",
    "TimeLiteral",
    "LTimeLiteral",
    # Type constructors
    "ARRAY",
    "STRING",
    "WSTRING",
    "POINTER_TO",
    "REFERENCE_TO",
    # Variable descriptors
    "VarDirection",
    "input_var",
    "output_var",
    "static_var",
    "inout_var",
    "temp_var",
    "constant_var",
    # POU decorators
    "fb",
    "program",
    "function",
    "method",
    # SFC
    "sfc",
    "step",
    "transition",
    # Data type decorators
    "struct",
    "enumeration",
    # Global variable lists
    "global_vars",
    "global_var",
    # Sentinel functions
    "first_scan",
    "delayed",
    "rising",
    "falling",
    "sustained",
    "pulse",
    "count_up",
    "count_down",
    # Protocols
    "CompiledPOU",
    "CompiledDataType",
    "CompiledGlobalVarList",
    # Errors
    "CompileError",
    # Discovery
    "discover",
    "DiscoveryResult",
    # Project & tasks
    "project",
    "task",
]
