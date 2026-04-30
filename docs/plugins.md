# Plugins

covtest ships two independent pytest plugins. Use either or both depending on your workflow.

---

## covtest.predict

Filters collected tests to only those predicted to be affected by your current changes.

```bash
pytest -p covtest.predict
```

**What it does:**

1. Before collection finishes, calls `predict_tests()` against the nearest snapshot.
2. Deselects all tests not in the predicted set.
3. If no snapshot is found, logs a message and lets all tests run — no error, no interruption.
4. If a configuration file was modified (see [Configuration](configuration.md#config-file-guard)), skips filtering and runs all tests.

**Typical output:**

```
covtest: predicting tests
covtest: selected 3 test(s)
```

With `--covtest-verbose`:

```
covtest: predicting tests
  loading snapshot ...
  load snapshot    :   2.9s  (.covtest/abc1234.covtest)
  computing git diff ...
  compute diff     :   0.2s  (2 files, 5 lines changed)
  selecting tests ...
  select tests     :   0.1s  (3 tests selected)
  total            :   3.2s
covtest: selected 3 test(s)
```

---

## covtest.process

Tracks which files each test opens during the session and, after the session ends, reads `.coverage` and writes an updated snapshot.

```bash
pytest --cov=mypackage --cov-context=test -p covtest.process
```

**What it does:**

1. Installs an autouse `patch_open` fixture that intercepts `builtins.open` calls and records which test opened which file. This lets covtest track data-file dependencies (e.g. a test that reads `cities.txt`).
2. After the session, runs `covtest_postprocess` — the same operation as `covtest process` on the command line.
3. Requires a **clean git commit**. If the working tree is dirty, covtest prints a message and skips saving. There is no error — the session still passes.

**Typical output (appended to pytest output):**

```
covtest: processing coverage data
covtest: done
```

With `--covtest-verbose`:

```
covtest: processing coverage data
  extracting coverage data ...
  extract coverage :   2.3s  (148 files)
  ...
  total            :  32.0s
covtest: done
```

---

## Combined mode

Use both plugins together for a single-command workflow:

```bash
pytest --cov=mypackage --cov-context=test -p covtest.predict -p covtest.process
```

Order does not matter — `covtest.predict` runs at collection time, `covtest.process` runs after the session.

The first time (no snapshot yet), all tests run and the snapshot is created. On subsequent runs with `covtest.predict` alone, only affected tests run.

---

## Permanent setup via conftest.py

Instead of passing `-p` flags every time, wire the plugins into `conftest.py`.

**Predict-only (recommended for daily development):**

```python
# conftest.py
from covtest.predict import covtest_modifyitems

def pytest_collection_modifyitems(session, config, items):
    return covtest_modifyitems(session, config, items)
```

**Full mode (predict + process, for CI or snapshot refresh runs):**

```python
# conftest.py
pytest_plugins = ["covtest.predict", "covtest.process"]
```

**File-open tracking only** (if you use `covtest process` on the CLI but still want data-file dependencies tracked):

```python
# conftest.py
from covtest.process import patch_open  # registers the autouse fixture
```

---

## Split contexts

When the same codebase runs on multiple platforms or configurations, use `.coveragerc` context tags together with `covtest.process`. See [Configuration — Split contexts](configuration.md#split-contexts).

---

## Options reference

| Option | Plugin | Default | Description |
|--------|--------|---------|-------------|
| `--covtest-verbose` | both | `false` | Print per-step timing output |
| `covtest_context` | both | `None` | Context name for multi-configuration tracking |
