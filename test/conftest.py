import os
import sys


# Ensure the current Python interpreter's Scripts/bin directory is on PATH so
# that subprocess calls to "pytest", "coverage", etc. find the right executables
# regardless of how the test suite was invoked.
_scripts = os.path.dirname(sys.executable)
if _scripts not in os.environ.get("PATH", ""):
    os.environ["PATH"] = _scripts + os.pathsep + os.environ.get("PATH", "")
