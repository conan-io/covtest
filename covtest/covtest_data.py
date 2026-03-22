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
        result.extend_mappings2(parse_data)

        for item in opened_files or []:
            test, file = item
            result.data_files.setdefault(file.replace("\\", "/"), []).append(test)
        return result

    def extend_mappings(self, parse_data):
        for file, parsed_file_data in parse_data.line_mappings().items():
            cov_file = self.py_files.get(file)
            if not cov_file:
                continue  # If there is no test data for this fil
            for line, target in parsed_file_data.items():
                original_tests = cov_file.get(line)
                if not original_tests:
                    continue
                for target_file, target_lines in target.items():
                    target_cov_file = self.py_files.get(target_file)
                    if not target_cov_file:
                        continue
                    for target_line in target_lines:
                        target_cov_file.setdefault(target_line, set()).extend(original_tests)

    def extend_mappings2(self, parse_data):
        # First pass, complete

        def _extend_global_usages(test_data_, parsed_file_data_):
            print("   PARSED ", parsed_file_data_.global_usages)
            for name, lines in parsed_file_data_.global_usages.items():
                print("    GLOBAL USAGES", name, lines)
                tests_from_usages = set()
                for lin_ in lines:
                    print("      GATHERING FROM LINE", lin_, test_data_[lin_])
                    tests_from_usages.update(test_data[lin_])
                print("    TESTS FROM USAGES", tests_from_usages)
                defined_lines = parsed_file_data_.global_definitions.get(name)
                print("    DEFINED IN LINES", defined_lines)
                if defined_lines:  # The whole scope of definition
                    for defined_line in defined_lines:
                        tests_ = test_data_[defined_line]
                        tests_.extend(t for t in tests_from_usages if t not in tests)

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
                #print("   Line", line, "extended to", tests)

            _extend_global_usages(test_data, parsed_file_data)

            # Extend mappings for imports within this file
            # Every line without tests that is an import
            for import_name, import_declared_lines in parsed_file_data.imports.items():
                # Find if import is used in file
                usage_lines = parsed_file_data.imports_usages.get(import_name)
                if not usage_lines:
                    continue  # This import seems unused in this file
                for usage_line in usage_lines:
                    lin_tests = test_data.get(usage_line)
                    if lin_tests:
                        for import_declared_line in import_declared_lines:
                            tests = test_data[import_declared_line]
                            tests.extend(t for t in lin_tests if t not in tests)

                # Project this import mappings into other files, the ones imported from
                # print("   Project imports")
                # Brute force, search in every other file for this name
                for other_file, other_test_data in self.py_files.items():
                    other_parsed_file_data = parse_data.files[other_file]
                    for global_def, global_def_lines in other_parsed_file_data.global_definitions.items():
                        # print("        OTher file", other_file, global_def, global_def_lines)
                        if import_name == global_def:
                            for other_line in global_def_lines:  # Found match
                                # FIXME: Avoid duplicates
                                other_test_data.setdefault(other_line, []).extend(tests)

        # Second pass, complete with global objects usages
        print("_-------------SECOND-PASS_----------------------------")
        for file, test_data in self.py_files.items():
            print("Extending mappings objects usages", file)
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
