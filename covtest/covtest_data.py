import gzip
import os

import msgpack

from covtest.errors import CovTestException


class CovTestData:

    def __init__(self, data_files=None, py_files=None, scopes=None):
        # the relation between the files in the project that have been opened
        # and the tests that cover/use them
        self.data_files = data_files or {}  # filepath: set(tests)
        self.py_files = py_files or {}
        self.scopes = scopes or {}

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
    def create(coverage_data, parse_data, opened_files):
        result = CovTestData()
        result.py_files = coverage_data
        result._extend_mappings(parse_data)
        result.scopes = {f: {line: lines for line, lines in scope_data.scopes.items()}
                         for f, scope_data in parse_data.files.items()}

        for item in opened_files or []:
            test, file = item
            result.data_files.setdefault(file.replace("\\", "/"), []).append(test)
        return result

    def _extend_mappings(self, parse_data):
        # First pass, complete

        def _extend_global_usages(test_data_, parsed_file_data_):
            for name, lines in parsed_file_data_.global_usages.items():
                tests_from_usages = set()
                for lin_ in lines:
                    try:
                        tests_from_usages.update(test_data[lin_])
                    except KeyError:
                        pass  # Maybe the global was not properly detected TODO
                defined_lines = parsed_file_data_.global_definitions.get(name)
                if defined_lines:  # The whole scope of definition
                    for defined_line in defined_lines:
                        try:
                            tests_ = test_data_[defined_line]
                            tests_.update(tests_from_usages)
                        except KeyError:
                            pass  # TODO: Same as above, globals not parsed

        for file, test_data in self.py_files.items():
            # print("Extending mappings for", file)
            parsed_file_data = parse_data.files[file]
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

            _extend_global_usages(test_data, parsed_file_data)

            # Extend mappings for imports within this file
            # Every line without tests that is an import
            for import_name, import_declared_lines in parsed_file_data.imports.items():
                # Find if import is used in file
                usage_lines = parsed_file_data.imports_usages.get(import_name)
                if not usage_lines:
                    continue  # This import seems unused in this file
                import_tests = set()
                for usage_line in usage_lines:
                    lin_tests = test_data.get(usage_line)
                    if lin_tests:
                        import_tests.update(lin_tests)
                if import_tests:
                    for import_declared_line in import_declared_lines:
                        try:
                            tests = test_data[import_declared_line]
                            tests.update(import_tests)
                        except KeyError:
                            pass  # TODO, missing match

                # Project this import mappings into other files, the ones imported from
                # Brute force, search in every other file for this name
                for other_file, other_test_data in self.py_files.items():
                    if other_file == file:
                        continue
                    other_parsed_file_data = parse_data.files[other_file]
                    for global_def, global_def_lines in other_parsed_file_data.global_definitions.items():
                        if import_name == global_def:
                            for other_line in global_def_lines:  # Found match
                                other_test_data.setdefault(other_line, set()).update(import_tests)

        # Second pass, complete with global objects usages
        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files[file]
            _extend_global_usages(test_data, parsed_file_data)

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
