"""Digital IO global variable list."""

from plx.framework._global_vars import global_var, global_vars
from plx.framework._types import BOOL


@global_vars
class DigitalIO:
    motor_run = global_var(BOOL, address="%Q0.0")
    e_stop = global_var(BOOL, address="%I0.0")
