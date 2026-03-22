import json
import os

from covtest.util.files import save, load


class CovTestData:
    FILENAME = "covtest.db"

    def __init__(self, data_files=None, py_files=None, last_failed=None):
        # the relation between the files in the project that have been opened
        # and the tests that cover/use them
        self.data_files = data_files or {}  # filepath: set(tests)
        self.py_files = py_files or {}
        self.last_failed = last_failed or []

    @staticmethod
    def create(coverage_data, parse_data, last_failed, opened_files):
        result = CovTestData()
        result.py_files = coverage_data
        result.last_failed = last_failed
        result._extend_mappings(parse_data)

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
                    tests_from_usages.update(test_data[lin_])
                defined_lines = parsed_file_data_.global_definitions.get(name)
                if defined_lines:  # The whole scope of definition
                    for defined_line in defined_lines:
                        tests_ = test_data_[defined_line]
                        tests_.extend(t for t in tests_from_usages if t not in tests_)

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
                for lin in range(line, endline+1):
                    lin_tests = test_data.get(lin, [])
                    tests.extend(t for t in lin_tests if t not in tests)

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
                        tests = test_data[import_declared_line]
                        tests.extend(t for t in import_tests if t not in tests)

                # Project this import mappings into other files, the ones imported from
                # Brute force, search in every other file for this name
                for other_file, other_test_data in self.py_files.items():
                    if other_file == file:
                        continue
                    other_parsed_file_data = parse_data.files[other_file]
                    for global_def, global_def_lines in other_parsed_file_data.global_definitions.items():
                        if import_name == global_def:
                            for other_line in global_def_lines:  # Found match
                                other_test_data.setdefault(other_line, []).extend(import_tests)

        # Second pass, complete with global objects usages
        for file, test_data in self.py_files.items():
            parsed_file_data = parse_data.files[file]
            _extend_global_usages(test_data, parsed_file_data)

    def save(self, folder):
        p = os.path.join(folder, CovTestData.FILENAME)
        data_files = {path: list(tests) for path, tests in self.data_files.items()}
        result = {"data_files": data_files,
                  "py_files": self.py_files,
                  "last_failed": self.last_failed}
        save(p, json.dumps(result))

    @staticmethod
    def load(folder):
        p = os.path.join(folder, CovTestData.FILENAME)
        if not os.path.exists(p):
            return None
        content = load(p)
        data = json.loads(content)
        data_files = {k: set(v) for k, v in data["data_files"].items()}
        py_files = {k: {int(line): v for line, v in lines.items()} for k, lines in data["py_files"].items()}
        last_failed = data["last_failed"]
        return CovTestData(data_files=data_files, py_files=py_files, last_failed=last_failed)
