import sys

SILENT = 0   # errors only
WARNING = 1  # warnings + errors
INFO = 2     # status lines (default)
VERBOSE = 3  # timing / detail
DEBUG = 4    # internal debug
TRACE = 5    # raw data dumps

_level = INFO


def set_level(level: int) -> None:
    global _level
    _level = max(SILENT, min(TRACE, level))


def out_info(msg: str) -> None:
    if _level >= INFO:
        print(f"covtest: {msg}")


def out_verbose(msg: str) -> None:
    if _level >= VERBOSE:
        print(f"  {msg}")


def out_debug(msg: str) -> None:
    if _level >= DEBUG:
        print(f"  [debug] {msg}")


def out_trace(msg: str) -> None:
    if _level >= TRACE:
        print(f"  [trace] {msg}")


def out_warning(msg: str) -> None:
    if _level >= WARNING:
        print(f"covtest warning: {msg}", file=sys.stderr)


def out_error(msg: str) -> None:
    print(f"covtest error: {msg}", file=sys.stderr)
