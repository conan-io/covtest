# How covtest works

covtest has two phases — **process** and **predict** — that together give you exact test selection with no configuration and no false negatives.

---

## The core idea

Every line of production code is covered by some set of tests. If you know exactly which tests cover which lines, and you know exactly which lines changed, the set of tests you need to run is simply the intersection.

covtest makes that mapping precise and fast.

---

## Phase 1 — Process

After a full test run with coverage contexts enabled, covtest reads the `.coverage` database and builds a compact snapshot:

```bash
pytest --cov=mypackage --cov-context=test   # run with context tracking
covtest process                             # build the snapshot
```

Internally, `process` does four things:

### 1. Extract coverage data

`pytest-cov` with `--cov-context=test` stores which test covered which line in the `.coverage` SQLite database. covtest reads this and builds a map:

```
{ "mypackage/math.py": { 12: {"test_add", "test_sum"}, 18: {"test_sub"}, ... } }
```

### 2. Parse source files

covtest walks the project source with Python's `ast` module to understand code structure — which lines belong to which function or class scope, which names are imported and where they are used. This lets it handle cases where a line itself has no direct coverage but is logically part of a covered scope.

### 3. Build extended mappings

Using the AST data, covtest extends the raw coverage map:

- **Scope propagation** — if a class or function definition line has no test, it inherits the tests of lines inside it.
- **Import propagation** — if `from mypackage.utils import helper` is used by tests A and B, the definition of `helper` in `utils.py` is tagged with those tests.
- **File-open tracking** — if a test opens a data file (e.g. `cities.txt`), that file is recorded as a dependency via the optional `patch_open` fixture.

### 4. Save the snapshot

The result is gzip-compressed JSON stored in `.covtest/<commit-hash>.covtest`. The commit hash is used so that predictions are always made relative to the exact revision the data was collected from.

---

## Phase 2 — Predict

```bash
covtest predict         # or: pytest -p covtest.predict
```

### 1. Load the snapshot

Find the nearest ancestor commit that has a snapshot and load it. With the default `max_commits = 20`, covtest tolerates up to 20 commits of drift before giving up.

### 2. Compute the git diff

Run `git diff <snapshot-commit>` against the current working tree to get the exact set of modified and inserted lines per file.

### 3. Select tests

For each changed line, look up which tests cover it. For inserted lines (new code with no direct coverage entry), covtest finds the enclosing scope in the snapshot and uses its tests — so adding a line inside an existing function correctly predicts the tests for that function.

The result is a list of test node IDs written to `.covtest/covtests.tests`.

---

## What makes it safe

- **Data-driven, not heuristic.** Selection is based on real execution traces, not file names, import graphs, or folder conventions.
- **Line-level granularity.** Changing one line in a 500-line file selects only the tests that executed that specific line.
- **No false negatives by construction.** If a test never executed a changed line during the reference run, it cannot appear in the prediction — and if it could not have been affected, this is correct.
- **Config-file guard.** Changes to `pyproject.toml`, `conftest.py`, `.coveragerc`, or other configuration files trigger a full run automatically, because their impact cannot be predicted from line coverage alone.

---

## Limitations

- The snapshot must be rebuilt when the codebase changes significantly (renamed files, major refactors). covtest detects drift and degrades gracefully: if no snapshot is found within `max_commits`, all tests run.
- Test files themselves are treated carefully: new test functions added since the snapshot are always included in the prediction.
- Dynamic code (eval, importlib, metaprogramming) may not be fully captured by static AST analysis.
