"""Task definitions for the sample project."""

from plx.framework._project import task
from plx.framework._types import T

from . import MainProgram

main_task = task("MainTask", periodic=T(ms=10), pous=[MainProgram], priority=1)
