"""
Lightweight output helpers for covtest.

Two levels:
  out_info(msg)    — always printed, prefixed with "covtest: "
  out_verbose(msg) — printed only when verbose mode is on (indented, no prefix)

Call set_verbose(True) once at startup (CLI flag or plugin option) to enable
the verbose level.
"""

_verbose = False


def set_verbose(verbose: bool) -> None:
    global _verbose
    _verbose = verbose


def out_info(msg: str) -> None:
    """Top-level status line, always shown.

    When writing to a real terminal, first erases the current line so that
    pytest's in-progress "collecting N items" counter (written with \\r) is
    cleanly replaced rather than left frozen on its own line.
    """
    print(f"covtest: {msg}")


def out_verbose(msg: str) -> None:
    """Indented detail / timing line, shown only in verbose mode."""
    if _verbose:
        print(f"  {msg}")
