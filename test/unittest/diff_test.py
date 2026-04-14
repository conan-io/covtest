import textwrap

from covtest.diff import diff


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
    modified, inserted = diff(text)
    # Line 4 was modified (pytest-cov replaced). The pure +unidiff insertion has
    # no source line and must NOT appear — its target line number would collide
    # with source coordinates of existing code in the coverage database.
    assert modified == {'requirements.txt': [4]}


def test_diff_pure_insertion_between_functions():
    """Inserting a new function between two existing functions must not mark
    the shifted second function's lines as modified.  Only source-side line
    numbers (removals / replacements) should be returned; pure additions have
    no source line and their target line numbers collide with coverage data."""
    text = textwrap.dedent("""\
        diff --git a/mymath.py b/mymath.py
        index 1ff87be..7278d6c 100644
        --- a/mymath.py
        +++ b/mymath.py
        @@ -3,5 +3,9 @@ def add(a, b):
             return a + b
         
         
        +def div(a, b):
        +    return a / b
        +
        +
         def mult(a, b):
             return a * b
        """)
    modified, inserted = diff(text)
    # No source lines were removed or changed — only new lines were added.
    # mult() must not appear in the result even though it shifted down.
    assert modified == {'mymath.py': []}
    assert inserted == {'mymath.py': [6]}
