def file_scopes_forward_projection(file_cov_data, file_ast_data):
    # 1st projection: The scopes
    # Every line covered by coverage but without tests gets the
    # tests of its scoped lines
    # A class gets all of its scope, a function the same, etc.

    # Modify IN-PLACE
    for line, tests in file_cov_data.items():
        if tests:
            continue
        # Only if this line is covered but no tests assigned
        endline = file_ast_data.scopes.get(line)
        if endline:  # TODO
            for lin in range(line, endline + 1):
                lin_tests = file_cov_data.get(lin, [])
                tests.update(lin_tests)


def scopes_backward_projection(cov_data, ast_data):
    # Iterate all files
    # extend class or function declaration only to its inner scope if the inner scope is
    # completely empty (import-time exclusive execution)
    # Reverse projection for import-time functions

    for file, test_data in cov_data.items():
        parsed_file_data = ast_data.files.get(file)
        if parsed_file_data is None:
            continue
        file_scopes_backward_projection(test_data, parsed_file_data)


def file_scopes_backward_projection(file_cov_data, file_ast_data):
    """ When a function or class declaration has tests information, but its inner
    scope is completely blank, it got it from import/global projection.
    It can project those tests from the declaration to the inner scope
    """
    new_data = {}
    for line, tests in file_cov_data.items():
        if not tests:
            continue
        endline = file_ast_data.scopes.get(line)
        if endline and endline > line:
            if not any(file_cov_data.get(lin) for lin in range(line + 1, endline + 1)):
                for ln_ in range(line + 1, endline + 1):
                    assert not file_cov_data.get(ln_)
                    new_data[ln_] = tests

    for k, v in new_data.items():
        file_cov_data[k] = v


def _src_line(relf, lineno, _src_cache, folder):
    if relf not in _src_cache:
        if folder:
            try:
                import os as _os
                path = _os.path.join(folder, relf.replace("/", _os.sep))
                with open(path, encoding="utf-8", errors="replace") as fh:
                    raw = fh.read().splitlines()
                # Sanitize to ASCII so subprocess stdout stays decodable
                _src_cache[relf] = [
                    ln__.encode("ascii", errors="replace").decode("ascii")
                    for ln__ in raw
                ]
            except OSError:
                _src_cache[relf] = []
        else:
            _src_cache[relf] = []
    lines_result = _src_cache[relf]
    return lines_result[lineno - 1] if 0 < lineno <= len(lines_result) else ""


def print_cov_data(cov_data, folder, label):
    _src_cache = {}
    print(f"\n=== DIAG _extend_mappings: {label} ===")
    for f_, td in sorted(cov_data.items()):
        if not td:
            continue
        print(f"  {f_}:")
        for ln__, ts_ in sorted(td.items()):
            code = _src_line(f_, ln__, _src_cache, folder)
            print(f"    {ln__:3d}: {code:<50}  {sorted(ts_)}")
