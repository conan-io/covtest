def file_scopes_up_projection(file_cov_data, file_ast_data):
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


def scopes_down_projection(cov_data, ast_data):
    # Iterate all files
    # extend class or function declaration only to its inner scope if the inner scope is
    # completely empty (import-time exclusive execution)
    # Reverse projection for import-time functions

    for file, test_data in cov_data.items():
        parsed_file_data = ast_data.files.get(file)
        if parsed_file_data is None:
            continue
        file_scopes_down_projection(test_data, parsed_file_data)


def file_scopes_down_projection(file_cov_data, file_ast_data):
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


def _collect_tests(test_data_, lines_):
    """Return the union of tests attributed to any of the given lines."""
    if not lines_:
        return None
    result = set()
    for line_ in lines_:
        t = test_data_.get(line_)
        if t:
            result.update(t)
    return result


def _propagate(test_data_, lines_, tests_):
    """Add *tests* to every line in *lines_*, creating entries as needed."""
    if not lines_ or not tests_:
        return 0
    updated = 0
    for line_ in lines_:
        tests_to_update = test_data_.setdefault(line_, set())
        old_lines = len(tests_to_update)
        tests_to_update.update(tests_)
        updated += len(tests_to_update) - old_lines
    return updated


def project_global_usages(file_cov_data, file_ast_data):
    """ within the same file, project usages of globally declared things in the file
    """
    updated = 1
    while updated:
        updated = 0
        for name, usage_lines_ in file_ast_data.global_usages.items():
            tests_ = _collect_tests(file_cov_data, usage_lines_)
            defined_lines = (file_ast_data.global_objects.get(name) or
                             file_ast_data.global_declarations.get(name))
            updated += _propagate(file_cov_data, defined_lines, tests_)


def project_imports_in_file(file_cov_data, file_ast_data):
    # 3rd projection: the imports
    for import_name, import_declared_lines in file_ast_data.imports.items():
        # within this file
        usage_lines = file_ast_data.imports_usages.get(import_name)
        import_tests = _collect_tests(file_cov_data, usage_lines)
        if not import_tests:
            continue
        _propagate(file_cov_data, import_declared_lines, import_tests)


def project_imports(cov_data, ast_data, import_time_lines):

    # print("PROJECTING IMPORTS!!!!!!")
    for _ in range(3):
        new_data = {}
        projected_new_tests = False
        for file, raw_test_data in cov_data.items():
            parsed_file_data = ast_data.files.get(file)
            if parsed_file_data is None:
                continue
            # print(f"  Projecting from file: {file}")
            for dotpath, decl_lines in parsed_file_data.import_sources.items():
                import_tests = _collect_tests(raw_test_data, decl_lines)
                if not import_tests:
                    continue  # import line not directly covered → skip

                # print(f"    Projecting from dotpath: {dotpath}: {decl_lines} Tests: {import_tests}")

                # Project to every line executed when importing this dotpath,
                # AND every ancestor package in the dotpath chain.
                # e.g. for "sympy.physics.quantum.state", also include the
                # import-time lines of "sympy.physics.quantum", "sympy.physics",
                # and "sympy", because importing the leaf for the first time
                # triggers all of those __init__.py files transitively.
                parts = dotpath.split(".")
                for depth in range(1, len(parts) + 1):
                    ancestor = ".".join(parts[:depth])
                    ancestor_data = import_time_lines.get(ancestor, {})
                    # print(f"  ancestor={ancestor!r}: {len(ancestor_data)} file(s) in import_time_lines")
                    for target_file, lines in ancestor_data.items():
                        # print(f"    -> {target_file}: lines={sorted(lines)}")
                        existing_file = cov_data.get(target_file, {})
                        target_file_data = new_data.setdefault(target_file, {})
                        for line in lines:
                            if not existing_file.get(line):
                                target_file_data[line] = import_tests
                                projected_new_tests = True

        # Merge accumulated data into py_files (done outside the loop to
        # avoid mutating the dict while iterating over it)
        for target_file, file_data in new_data.items():
            existing = cov_data.setdefault(target_file, {})
            for line, tests in file_data.items():
                existing.setdefault(line, set()).update(tests)

        if not projected_new_tests:
            break


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
        if "/http.py" not in f_:
            continue
        if not td:
            continue
        print(f"  {f_}:")
        for ln__, ts_ in sorted(td.items()):
            code = _src_line(f_, ln__, _src_cache, folder)
            print(f"    {ln__:3d}: {code:<50}  {sorted(ts_)}")
