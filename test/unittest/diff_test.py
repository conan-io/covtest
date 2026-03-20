import os
import textwrap

from covtest.diff import diff
from covtest.util.files import chdir
from covtest.util.run import run


def test_diff_parser():
    text = textwrap.dedent("""
        diff --git a/requirements.txt b/requirements.txt
        index 8a546b1..0062942 100644
        --- a/requirements.txt
        +++ b/requirements.txt
        @@ -1,4 +1,5 @@
         pytest
         coverage
         nose
        -pytest-cov
        +pytest-cov
        +unidiff
        """)
    result = diff(text)
    assert result == {'requirements.txt': [4, 5]}


def test_diff_folder():
    current = os.path.dirname(__file__)
    base = os.path.realpath(os.path.join(current, "..", "integration/cases/mymath/"))

    with chdir(base):
        # --no-index return 1 if there are differences, and 0 if not
        out, err = run('git diff --no-index src fix_add', ignore_error=True)
    result = diff(out)
    assert result == {'fix_add/mymath.py': [3], 'fix_add/test.json': [3]}
