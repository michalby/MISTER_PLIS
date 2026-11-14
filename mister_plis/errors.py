class ToolError(Exception):
    """Raise for problems the user can fix (bad input, wrong file). Shown without a traceback."""


class Cancelled(Exception):
    """Raised inside a run when the user cancels the job."""
