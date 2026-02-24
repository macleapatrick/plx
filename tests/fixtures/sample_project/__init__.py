"""Sample project root — contains a @program in the root package."""

from plx.framework._decorators import program
from plx.framework._descriptors import input_var, output_var
from plx.framework._types import BOOL


@program
class MainProgram:
    running = input_var(BOOL)
    done = output_var(BOOL)

    def logic(self):
        self.done = self.running
