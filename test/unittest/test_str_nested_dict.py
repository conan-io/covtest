import tempfile
import os

from covtest.covtest import str_nested_dict


def test_str_nested_dict_empty_file():
    """str_nested_dict must not raise when a tracked file is completely empty.
    Without the 'if not read_lines: continue' guard, accessing read_lines[line-1]
    on an empty list would raise an IndexError.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write("")  # completely empty file
        empty_path = f.name
    try:
        files = {empty_path: {1: {"some_test"}}}
        result = str_nested_dict(files)
        assert empty_path in result
        # No line details should be printed for the empty file
        assert "some_test" not in result
    finally:
        os.unlink(empty_path)
