"""Root-level type definitions."""

from plx.framework._data_types import struct
from plx.framework._types import BOOL, INT, REAL


@struct
class MotorData:
    speed: REAL = 0.0
    running: BOOL = False
    fault_code: INT = 0
