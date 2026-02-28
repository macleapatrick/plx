"""plx export — code generation from Universal IR.

Public API::

    from plx.export import to_structured_text
    st_text = to_structured_text(project_or_pou)
"""

from .st import to_structured_text

__all__ = ["to_structured_text"]
