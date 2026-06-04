def _compute():
    return "changed"       # body executed at import time via the call below


MODULE_DATA = _compute()   # calls _compute() at module level during import
