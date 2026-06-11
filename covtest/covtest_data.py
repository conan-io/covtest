import gzip
import os

import msgpack

from covtest.errors import CovTestException


class CovTestData:

    def __init__(self, data_files=None, py_files=None, scopes=None):
        # the relation between the files in the project that have been opened
        # and the tests that cover/use them
        self.data_files = data_files or {}  # filepath: set(tests)
        self.py_files = py_files or {}  # Actual python files
        self.scopes = scopes or {}  # {filepath: {line: lines of scope}}

    def summary(self):
        result = [f"Data files: {len(self.data_files)}",
                  f"Py files: {len(self.py_files)}"]
        all_tests = set()
        for tests in self.data_files.values():
            all_tests.update(tests)
        for tests in self.py_files.values():
            for line_tests in tests.values():
                all_tests.update(line_tests)
        result.append(f"Annotated tests: {len(all_tests)}")
        return "\n".join(result)

    @staticmethod
    def create(coverage_data, parse_data, opened_files, import_time_lines):
        result = CovTestData()
        result.py_files = coverage_data
        result._extend_mappings(parse_data, import_time_lines)
        result.scopes = {f: {line: lines for line, lines in scope_data.scopes.items()}
                         for f, scope_data in parse_data.files.items()}

        for item in opened_files or []:
            test, file = item
            result.data_files.setdefault(file.replace("\\", "/"), []).append(test)
        return result

    def _extend_mappings(self, parse_data, import_time_lines):
        # Snapshot raw coverage so the import-time projection uses unenriched data.
        # IMPORTANT: we must read test attribution from the RAW coverage data,
        # not from the enriched py_files.  The existing first pass propagates tests
        # from usage sites back to import declaration lines (e.g. both test_add and
        # test_mult end up on a shared `from mymath import add, mult` line).  Using
        # that enriched data would cause the projection to spread both tests onto
        # all import-time lines of mymath, producing false positives.  The raw data
        # only has a test on an import line when the test DIRECTLY executed it —
        # which is exactly what we want (function-body / local imports).
        # Snapshot raw coverage before passes 1 & 2 mutated it.
        # Values are shallow-copied sets so later mutations don't bleed in.
        raw_py_files = {
            f: {line: set(tests) for line, tests in td.items()}
            for f, td in self.py_files.items()
        }

        def _collect_tests(test_data_, lines_):
            """Return the union of tests attributed to any of the given lines."""
            if not lines_:
                return None
            result = set()
            for line in lines_:
                t = test_data_.get(line)
                if t:
                    result.update(t)
            return result

        def _propagate(test_data_, lines_, tests):
            """Add *tests* to every line in *lines_*, creating entries as needed."""
            if not lines_ or not tests:
                return
            for line in lines_:
                test_data_.setdefault(line, set()).update(tests)

        def _extend_global_usages(test_data_, parsed_file_data_):
            for name, usage_lines_ in parsed_file_data_.global_usages.items():
                tests = _collect_tests(test_data_, usage_lines_)
                defined_lines = parsed_file_data_.global_definitions.get(name)
                _propagate(test_data_, defined_lines, tests)

        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files[file]

            # 1st projection: The scopes
            # Every line covered by coverage but without tests gets the
            # tests of its scoped lines
            # A class gets all of its scope, a function the same, etc.
            for line, tests in test_data.items():
                if tests:
                    continue
                # Only if this line is covered but no tests assigned
                endline = parsed_file_data.scopes.get(line)
                if endline:  # TODO
                    for lin in range(line, endline+1):
                        lin_tests = test_data.get(lin, [])
                        tests.update(lin_tests)

            # 2nd projection, the used global objects within this file
            _extend_global_usages(test_data, parsed_file_data)

            # 3rd projection: the imports
            for import_name, import_declared_lines in parsed_file_data.imports.items():
                # within this file
                usage_lines = parsed_file_data.imports_usages.get(import_name)
                import_tests = _collect_tests(test_data, usage_lines)
                if not import_tests:
                    continue
                _propagate(test_data, import_declared_lines, import_tests)

                # Project into other files — brute-force search for this name
                # TODO: maybe this can be improved with the build-import-graph
                for other_file, other_test_data in self.py_files.items():
                    if other_file == file:
                        continue
                    other_parsed_file_data = parse_data.files[other_file]
                    for global_def, global_def_lines in other_parsed_file_data.global_definitions.items():
                        if import_name == global_def:
                            for other_line in global_def_lines:
                                other_test_data.setdefault(other_line, set()).update(import_tests)

        # Second pass, complete with global objects usages
        # In case some of the global objects are imported from other files and got new tests
        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files[file]
            _extend_global_usages(test_data, parsed_file_data)

        # Third pass: import-time line projection.
        # For each import statement that has test coverage (the import line was
        # executed during a test — true for function-body / local imports), project
        # those tests onto every line that runs when the imported module is loaded.
        # This handles transitive chains through __init__.py re-exports and
        # import-time function calls that static AST analysis cannot see.
        new_data = {}  # target_file → {line → set(tests)} accumulated before merging
        for file, raw_test_data in raw_py_files.items():
            parsed_file_data = parse_data.files.get(file)
            if parsed_file_data is None:
                continue
            for dotpath, decl_lines in parsed_file_data.local_import_sources.items():
                import_tests = _collect_tests(raw_test_data, decl_lines)
                if not import_tests:
                    continue  # import line not directly covered → skip

                # Project to every line executed when importing this dotpath,
                # AND every ancestor package in the dotpath chain.
                # e.g. for "sympy.physics.quantum.state", also include the
                # import-time lines of "sympy.physics.quantum", "sympy.physics",
                # and "sympy", because importing the leaf for the first time
                # triggers all of those __init__.py files transitively.
                parts = dotpath.split(".")
                for depth in range(1, len(parts) + 1):
                    ancestor = ".".join(parts[:depth])
                    for target_file, lines in import_time_lines.get(ancestor, {}).items():
                        target_file_data = new_data.setdefault(target_file, {})
                        for line in lines:
                            target_file_data.setdefault(line, set()).update(import_tests)

        # Merge accumulated data into py_files (done outside the loop to
        # avoid mutating the dict while iterating over it)
        for target_file, file_data in new_data.items():
            existing = self.py_files.setdefault(target_file, {})
            for line, tests in file_data.items():
                existing.setdefault(line, set()).update(tests)

    def save(self, filepath):
        all_tests = set()
        for tests in self.data_files.values():
            all_tests.update(tests)
        for tests in self.py_files.values():
            for line_tests in tests.values():
                all_tests.update(line_tests)
        all_tests = list(sorted(all_tests))
        dict_tests = {test: i for i, test in enumerate(all_tests)}
        data_files = {path: [dict_tests[t] for t in tests]
                      for path, tests in self.data_files.items()}
        # Fix 3: skip lines with no test attribution — they contribute nothing to
        # predictions and can be numerous (def/import/class lines hit at module load).
        pyfiles = {f: {line: [dict_tests[t] for t in tests]
                       for line, tests in test_data.items() if tests}
                   for f, test_data in self.py_files.items()}
        result = {"tests": all_tests,
                  "data_files": data_files,
                  "py_files": pyfiles,
                  "scopes": self.scopes}
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with gzip.open(filepath, 'wb') as fh:
            fh.write(msgpack.packb(result, use_bin_type=True))

    @staticmethod
    def load(filepath):
        if not os.path.exists(filepath):
            raise CovTestException(f"Covtest file not found: {filepath}")

        with gzip.open(filepath, 'rb') as fh:
            data = msgpack.unpackb(fh.read(), raw=False, strict_map_key=False)

        tests_list = data["tests"]
        data_files = {k: set(tests_list[i] for i in v)
                      for k, v in data["data_files"].items()}
        # msgpack preserves integer keys natively — no int() cast needed
        py_files = {filename: {line: set(tests_list[i] for i in tests)
                               for line, tests in lines.items()}
                    for filename, lines in data["py_files"].items()}
        scopes = {filename: dict(lines)
                  for filename, lines in data["scopes"].items()}
        return CovTestData(data_files=data_files, py_files=py_files, scopes=scopes)


_PARTIAL_FILE = "partial.covtest"


class PartialData:
    """Lightweight record written by covtest.predict after each run.

    Contains only what covtest_merge needs to forward the snapshot to the
    next commit without running the full test suite again:

    - base_commit  — the commit whose full snapshot was used for prediction
    - tests_run    — test IDs that were selected and executed
    """

    def __init__(self, base_commit, tests_run):
        self.base_commit = base_commit
        self.tests_run = list(tests_run)

    def save(self, folder):
        filepath = os.path.join(folder, ".covtest", _PARTIAL_FILE)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        data = {
            "base_commit": self.base_commit,
            "tests_run": self.tests_run,
        }
        with gzip.open(filepath, "wb") as fh:
            fh.write(msgpack.packb(data, use_bin_type=True))

    @staticmethod
    def load(folder):
        filepath = os.path.join(folder, ".covtest", _PARTIAL_FILE)
        if not os.path.exists(filepath):
            raise CovTestException(
                "no partial covtest data found — run 'pytest -p covtest.predict' first"
            )
        with gzip.open(filepath, "rb") as fh:
            data = msgpack.unpackb(fh.read(), raw=False)
        return PartialData(data["base_commit"], data["tests_run"])

    @staticmethod
    def exists(folder):
        return os.path.exists(os.path.join(folder, ".covtest", _PARTIAL_FILE))

    @staticmethod
    def delete(folder):
        filepath = os.path.join(folder, ".covtest", _PARTIAL_FILE)
        if os.path.exists(filepath):
            os.remove(filepath)
