"""Roller conveyor FB."""

from plx.framework._decorators import fb
from plx.framework._descriptors import input_var, output_var
from plx.framework._types import BOOL


@fb
class RollerConveyor:
    cmd_run = input_var(BOOL)
    is_running = output_var(BOOL)

    def logic(self):
        self.is_running = self.cmd_run
