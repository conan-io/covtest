import gzip
import os

import msgpack

from covtest.ast_mappings import file_scopes_up_projection, print_cov_data, \
    project_global_usages, project_imports_in_file, project_imports, \
    file_scopes_down_projection, scopes_down_projection
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
    def create(coverage_data, parse_data, opened_files, import_time_lines, folder=None):
        result = CovTestData()
        result.py_files = coverage_data
        result._extend_mappings(parse_data, import_time_lines, folder=folder)
        result.scopes = {f: {line: lines for line, lines in scope_data.scopes.items()}
                         for f, scope_data in parse_data.files.items()}

        for item in opened_files or []:
            test, file = item
            result.data_files.setdefault(file.replace("\\", "/"), []).append(test)
        return result

    def _extend_mappings(self, parse_data, import_time_lines, folder=None):
        print_cov_data(self.py_files, folder, "initial py_files (raw coverage)")

        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files[file]

            file_scopes_up_projection(test_data, parsed_file_data)

            # 2nd projection, the used global objects within this file
            project_global_usages(test_data, parsed_file_data)

            # 3rd projection: the imports
            project_imports_in_file(test_data, parsed_file_data)

            # Another pass, filling
            file_scopes_down_projection(test_data, parsed_file_data)

        print_cov_data(self.py_files, folder, "after 1st pass (same file scopes + global_usages)")

        # Third pass: import-time line projection.
        # For each import statement that has test coverage (the import line was
        # executed during a test — true for function-body / local imports), project
        # those tests onto every line that runs when the imported module is loaded.
        # This handles transitive chains through __init__.py re-exports and
        # import-time function calls that static AST analysis cannot see.

        project_imports(self.py_files, parse_data, import_time_lines)

        print_cov_data(self.py_files, folder, "after 3rd pass (import-time projection merged)")

        # Re-project globals inside file to complete after import projections
        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files.get(file)
            if parsed_file_data is None:
                continue
            project_global_usages(test_data, parsed_file_data)

        print_cov_data(self.py_files, folder, "Second extend global usages projection to complete after imports")

        scopes_down_projection(self.py_files, parse_data)

        print_cov_data(self.py_files, folder, "Last pass (reverse scope projection)")

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
