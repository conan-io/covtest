# covtest

**Coverage-guided test selection for pytest.** Run only the tests affected by your changes.

covtest maps which tests exercise which lines of code, then uses git diffs to predict the minimal set of tests that need to run. In large projects this can reduce CI time from minutes to seconds.

---

## How it works

1. **Process** — after a full test run, covtest reads the `.coverage` database and stores a compact test-to-line mapping in a `.covtest` file.
2. **Predict** — when you make changes, covtest diffs the current working tree against the last processed commit and returns only the tests that cover the modified lines.

The prediction is exact: if a test never executed a changed line, it will not be selected.

---

## Installation

```bash
pip install covtest
```

Requires Python 3.9+ and a project that uses [pytest-cov](https://pytest-cov.readthedocs.io/) with **context tracking enabled**.

---

## Quick start

### Step 1 — run your full test suite with coverage contexts

```bash
pytest --cov=mypackage --cov-context=test
```

The `--cov-context=test` flag is what lets covtest know which test covered which line.

### Step 2 — process the coverage data

```bash
covtest process
```

This reads `.coverage` and writes `.covtest/<commit>.covtest`.

### Step 3 — make some changes, then predict

```bash
# edit src/mypackage/math.py ...
covtest predict
```

covtest writes the affected test IDs to `.covtest/covtests.tests` (one per line).

### Step 4 — run only the affected tests

```bash
pytest $(cat .covtest/covtests.tests)   # Linux / macOS
pytest @.covtest/covtests.tests         # Windows
```

---

## Plugin mode

covtest ships two independent pytest plugins that can be used together or separately.

### Predict only (fast — normal dev loop)

```bash
pytest -p covtest.predict
```

Filters the collected tests down to only those affected by your current changes. On the first run (no `.covtest` data yet) all tests execute normally.

You can also wire it permanently via `conftest.py`:

```python
from covtest.predict import covtest_modifyitems

def pytest_collection_modifyitems(session, config, items):
    return covtest_modifyitems(session, config, items)
```

### Process (collect coverage and update snapshot)

```bash
pytest --cov=mypackage --cov-context=test -p covtest.process
```

Tracks which files each test opens (`patch_open` fixture) and, after the session, reads `.coverage` and writes an updated `.covtest` snapshot. Requires a clean git commit — aborts with a message if the working tree is dirty.

### Combined (full automatic mode)

```bash
pytest --cov=mypackage --cov-context=test -p covtest.predict -p covtest.process
```

Predicts which tests to run **and** refreshes the snapshot afterwards in one invocation. Typical usage: run this after merging or rebasing to keep the snapshot current, then use `-p covtest.predict` alone during normal development.

On the first run (no `.covtest` data yet) all tests execute normally.

---

## Split contexts (multi-OS / multi-configuration)

When the same test suite runs on multiple platforms or configurations, you can tag each run with a context name so that covtest tracks them independently.

Pass `--cov-context=<name>` to pytest and the matching `--covtest-context=<name>` to both `covtest process` and `covtest predict` (or the plugin option).

Example `.coveragerc` for a Linux/Windows split:

```ini
[run]
context = linux
```

Predictions for each context are written to `covtests.<context>.tests`.

---

## Remote caching

In a CI/CD environment every branch has its own coverage snapshot. covtest can push and pull these snapshots to/from a simple HTTP file server so developers always get predictions even on a fresh checkout.

**Upload** (in CI, after processing):

```bash
covtest upload
```

**Download** (automatic) — `covtest predict` and the plugin both pull from the server automatically when `server_url` is configured.

The server protocol is plain HTTP PUT/GET. Any static file server that supports PUT will work (nginx with `dav_methods PUT`, an S3 bucket with a pre-signed URL proxy, etc.).

---

## Configuration

Create `covtest.ini` in the project root (or `test/covtest.ini` / `tests/covtest.ini`):

```ini
[covtest]
# How many past commits to search for a .covtest snapshot (default: 20)
max_commits = 20

# How long to cache downloaded .covtest files in seconds (default: 3600)
server_cache_ttl = 3600

# Remote server URL for upload/download (optional)
server_url = https://covtest.example.com/myproject
```

The `server_url` can also be set in `pyproject.toml`:

```toml
[tool.covtest]
server_url = "https://covtest.example.com/myproject"
```

Or in `pytest.ini` / `setup.cfg` as `covtest_server`.

### Configuration files that force a full run

When any of the following files is modified, covtest cannot safely predict which tests are affected and returns `None` (all tests must run):

`requirements*.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `pytest.ini`, `tox.ini`, `.coveragerc`, `conftest.py`

---

## CLI reference

```
covtest process [path] [-cf COVTEST_FILE] [-v]
```
Reads `.coverage` in `path` (default: current directory) and writes a `.covtest` snapshot.

```
covtest predict [path] [-cf COVTEST_FILE]
```
Diffs the working tree against the last snapshot and writes affected test IDs to `covtests.tests` (or `covtests.<context>.tests` for split contexts). Exits with code `1` when a config file was changed and all tests must run.

```
covtest upload [path] [-v]
```
Uploads the current snapshot to the configured `server_url`.

---

## Running covtest's own tests

```bash
pip install -e ".[dev]"

# Fast: unit + integration
pytest test/unittest test/integration

# End-to-end (slower, requires git)
pytest test/e2e

# Benchmark (clones the Conan repository — very slow)
pytest test/benchmark
```

---

## License

Free for open source projects, educational institutions, NGOs, public research, and individual developers (including those at commercial companies) running covtest locally.

Commercial CI/CD use by for-profit organizations requires a sponsorship. See the full [LICENSE](LICENSE) and the [License & Sustainability](https://memsharded.github.io/covtest/license/) page for details.
