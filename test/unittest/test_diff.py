import difflib
import textwrap

from covtest.diff import diff


def make_diff(filename, before, after):
    """Compute a unified diff text from two file content strings."""
    return "".join(difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
    ))


def test_modified_line():
    """Replacing a line appears as a modified source line."""
    before = textwrap.dedent("""\
        pytest
        coverage
        nose
        """)
    after = textwrap.dedent("""\
        pytest
        coverage>5
        nose
        """)
    result = diff(make_diff("requirements.txt", before, after))
    assert len(result) == 1
    assert result["requirements.txt"]["modified"] == [2]
    assert result["requirements.txt"]["deleted"] == []  # refer the old file
    assert result["requirements.txt"]["inserted"] == []  # refer the new file


def test_deleted_line():
    """Removing a line appears as a modified source line with no insertion."""
    before = textwrap.dedent("""\
        pytest
        coverage
        nose
        """)
    after = textwrap.dedent("""\
        pytest
        nose
        """)
    result = diff(make_diff("requirements.txt", before, after))
    assert len(result) == 1
    assert result["requirements.txt"]["modified"] == []
    assert result["requirements.txt"]["deleted"] == [2]  # refer the old file
    assert result["requirements.txt"]["inserted"] == []  # refer the new file


def test_inserted_line():
    before = textwrap.dedent("""\
        pytest
        coverage
        nose
        """)
    after = textwrap.dedent("""\
        pytest
        coverage
        diff
        nose
        """)
    result = diff(make_diff("requirements.txt", before, after))
    assert len(result) == 1
    assert result["requirements.txt"]["modified"] == []
    assert result["requirements.txt"]["deleted"] == []  # refer the old file
    assert result["requirements.txt"]["inserted"] == [3]  # refer the new file


def test_inserted_blank_line():
    before = textwrap.dedent("""\
        pytest
        nose
        """)
    after = textwrap.dedent("""\
        pytest

        nose
        """)
    result = diff(make_diff("requirements.txt", before, after))
    assert len(result) == 1
    assert result["requirements.txt"]["modified"] == []
    assert result["requirements.txt"]["deleted"] == []  # refer the old file
    assert result["requirements.txt"]["inserted"] == [2]  # refer the new file


def test_pure_insertion_between_functions():
    """Inserting a new function must not mark the shifted second function's
    lines as modified — only the first new target line number is returned."""
    before = textwrap.dedent("""\
        def add(a, b):
            return a + b


        def mult(a, b):
            return a * b
        """)
    after = textwrap.dedent("""\
        def add(a, b):
            return a + b


        def div(a, b):
            return a / b


        def mult(a, b):
            return a * b
        """)
    result = diff(make_diff("mymath.py", before, after))
    assert len(result) == 1
    assert result["mymath.py"]["modified"] == []
    assert result["mymath.py"]["deleted"] == []       # refer the old file
    assert result["mymath.py"]["inserted"] == [5, 6, 7, 8]  # refer the new file
