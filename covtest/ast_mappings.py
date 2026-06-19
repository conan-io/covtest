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


def file_scopes_down_projection(file_cov_data, file_ast_data):
    """When a function or class declaration has tests but its executed body lines
    are still empty, project those tests down into the body.

    Only lines already present in file_cov_data (executed, with empty test sets)
    are eligible — lines absent from coverage (never executed) are never touched.

    Returns the number of newly-added (line, test) attributions.
    """
    new_data = {}
    for line, tests in file_cov_data.items():
        if not tests:
            continue
        endline = file_ast_data.scopes.get(line)
        if endline and endline > line:
            body_covered = [ln for ln in range(line + 1, endline + 1)
                            if ln in file_cov_data]
            if body_covered and not any(file_cov_data[ln] for ln in body_covered):
                for ln in body_covered:
                    new_data[ln] = tests

    added = 0
    for k, v in new_data.items():
        file_cov_data[k] = v
        added += len(v)
    return added


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
    """Add *tests* to lines in *lines_* that are already in *test_data_*.

    Lines absent from test_data_ (never executed) are skipped — the coverage
    universe is never expanded by projection.
    """
    if not lines_ or not tests_:
        return 0
    updated = 0
    for line_ in lines_:
        if line_ not in test_data_:
            continue
        tests_to_update = test_data_[line_]
        old_size = len(tests_to_update)
        tests_to_update.update(tests_)
        updated += len(tests_to_update) - old_size
    return updated


def project_global_usages(file_cov_data, file_ast_data):
    """ within the same file, project usages of globally declared things in the file.

    Returns the total number of newly-added attributions across the inner fixpoint.
    """
    total = 0
    updated = 1
    while updated:
        updated = 0
        for name, usage_lines_ in file_ast_data.global_usages.items():
            tests_ = _collect_tests(file_cov_data, usage_lines_)
            defined_lines = (file_ast_data.global_objects.get(name) or
                             file_ast_data.global_declarations.get(name))
            updated += _propagate(file_cov_data, defined_lines, tests_)
        total += updated
    return total


def project_imports_in_file(file_cov_data, file_ast_data):
    # 3rd projection: the imports. Returns the number of newly-added attributions.
    added = 0
    for import_name, import_declared_lines in file_ast_data.imports.items():
        # within this file
        usage_lines = file_ast_data.imports_usages.get(import_name)
        import_tests = _collect_tests(file_cov_data, usage_lines)
        if not import_tests:
            continue
        added += _propagate(file_cov_data, import_declared_lines, import_tests)
    return added


def _module_relpath(dotpath, ast_data):
    """Resolve a module dotpath to its relative file path in ast_data.files, or None.

    Tries the plain-module form (``a/b/c.py``) then the package form
    (``a/b/c/__init__.py``).  Only files actually present in the parsed data are
    returned — stdlib / third-party dotpaths resolve to None.
    """
    prefix = dotpath.replace(".", "/")
    for candidate in (prefix + ".py", prefix + "/__init__.py"):
        if candidate in ast_data.files:
            return candidate
    return None


def import_time_lines(parsed_file_data):
    """Lines of a file that execute when the module is imported.

    Everything at module level — assignments, bare calls, import statements, and
    def/class *header* lines — but NOT function/class bodies (those run only when
    called).  Derived purely from the parsed AST data.
    """
    lines = set()
    for mapping in (parsed_file_data.global_objects,
                    parsed_file_data.global_calls,
                    parsed_file_data.imports,
                    parsed_file_data.global_declarations):
        for decl_lines in mapping.values():
            lines.update(decl_lines)
    return lines


def project_imports(cov_data, ast_data):
    """Static cross-file projection — replaces dynamic import tracing.

    For each imported name in each file, propagate the tests attributed to that
    name's *usages* onto the name's definition in the source module, plus the
    import-time lines of every ancestor package (importing a submodule runs each
    ancestor ``__init__.py``).  Single-name import statements additionally follow
    the import line's own tests, which threads attribution through pure re-export
    chains.  Returns the number of newly-added attributions.
    """
    added = 0
    # Snapshot source files: projecting may add new target files to cov_data, and
    # those get processed on the next outer fixpoint iteration.
    for file in list(cov_data):
        file_cov = cov_data[file]
        parsed_file_data = ast_data.files.get(file)
        if parsed_file_data is None:
            continue
        for bound_name, binding in parsed_file_data.import_bindings.items():
            dotpath, original_name, is_module, lines, sole_name = binding
            # Per-name usage tests (contamination-free): tests on lines where the
            # bound name is actually used.  usage_names is keyed by bare name.
            tests = set(_collect_tests(file_cov, parsed_file_data.usage_names.get(bound_name)) or ())
            if sole_name:
                # Re-export rule: a statement binding a single name also carries the
                # tests attributed to the import line itself, so attribution flows
                # through ``from .sub import RESULT`` style re-exports.
                tests |= set(_collect_tests(file_cov, lines) or ())
            if not tests:
                continue

            # (a) precise target in the imported module
            target_relpath = _module_relpath(dotpath, ast_data)
            if target_relpath is not None:
                target_pdata = ast_data.files[target_relpath]
                if is_module:
                    target_lines = import_time_lines(target_pdata)
                else:
                    target_lines = (list(target_pdata.global_objects.get(original_name, []))
                                    + list(target_pdata.global_declarations.get(original_name, []))
                                    + list(target_pdata.imports.get(original_name, [])))
                added += _propagate(cov_data.setdefault(target_relpath, {}), target_lines, tests)

            # (b) ancestor packages — importing a submodule runs each ancestor __init__.py
            parts = dotpath.split(".")
            for depth in range(1, len(parts)):
                ancestor = ".".join(parts[:depth])
                anc_relpath = _module_relpath(ancestor, ast_data)
                if anc_relpath is not None:
                    anc_pdata = ast_data.files[anc_relpath]
                    added += _propagate(cov_data.setdefault(anc_relpath, {}),
                                        import_time_lines(anc_pdata), tests)
    return added


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
    return
    _src_cache = {}
    print(f"\n=== DIAG _extend_mappings: {label} ===")
    for f_, td in sorted(cov_data.items()):
        if not td:
            continue
        print(f"  {f_}:")
        for ln__, ts_ in sorted(td.items()):
            if not ts_:
                continue
            code = _src_line(f_, ln__, _src_cache, folder)
            print(f"    {ln__:3d}: {code:<50}  {list(ts_)[:1]}")
