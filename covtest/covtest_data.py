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
        result.extend_mappings(parse_data)
        # clean ducplicated and empty
        for f, mapping in result.py_files.items():
            for line, tests in mapping.items():
                tests[:] = [t for t in set(tests) if t]

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
