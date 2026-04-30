# Getting started

## Requirements

- Python 3.9 or later
- [pytest](https://pytest.org) 7.0+
- [pytest-cov](https://pytest-cov.readthedocs.io/) 4.0+
- A git repository (covtest uses git to diff against the snapshot commit)

## Install

```bash
pip install covtest
```

For development use, add it to your project's dev dependencies:

```toml
# pyproject.toml
[project.optional-dependencies]
dev = ["covtest"]
```

---

## Step 1 — Run your full test suite with coverage contexts

covtest needs `--cov-context=test` to know which test covered which line:

```bash
pytest --cov=mypackage --cov-context=test
```

Replace `mypackage` with the name of the package you want to track. You can also use `--cov=.` to cover everything.

---

## Step 2 — Build the snapshot

```bash
covtest process
```

This reads `.coverage` and writes `.covtest/<commit-hash>.covtest` — a compact, gzip-compressed mapping of tests to lines. The commit hash ties the snapshot to the exact revision it was built from.

!!! note
    `covtest process` must be run on a **clean git commit**. If the working tree is dirty, covtest skips saving the snapshot (it cannot tie the data to a stable reference point).

![covtest process demo](assets/demo-process.gif)

Add `-v` for per-step timing:

```
covtest: processing coverage data
  extracting coverage data ...
  extract coverage :   2.3s  (148 files)
  parsing source files ...
  parse sources    :  18.4s  (312 files)
  building coverage mappings ...
  build mappings   :   8.1s
  saving snapshot ...
  save snapshot    :   3.2s  (.covtest/abc1234.covtest)
  total            :  32.0s
covtest: done
```

---

## Step 3 — Make some changes

Edit a source file. covtest will detect exactly which lines changed.

---

## Step 4 — Predict

```bash
covtest predict
```

covtest diffs the working tree against the snapshot commit and writes the affected test IDs to `.covtest/covtests.tests`:

![covtest predict demo](assets/demo-predict.gif)

---

## Step 5 — Run only the predicted tests

=== "Linux / macOS"

    ```bash
    pytest $(cat .covtest/covtests.tests)
    ```

=== "Windows"

    ```bat
    pytest @.covtest\covtests.tests
    ```

---

## Plugin mode — all in one

Instead of running `covtest process` and `covtest predict` separately, use the pytest plugins.

**Predict only** (your normal dev loop — fast):

```bash
pytest -p covtest.predict
```

This filters the collected tests down to only those affected by your changes. If no snapshot exists yet, all tests run normally.

**Predict + process** (after a clean commit — rebuilds the snapshot):

```bash
pytest --cov=mypackage --cov-context=test -p covtest.predict -p covtest.process
```

See [Plugins](plugins.md) for permanent `conftest.py` setup.

---

## Committing the snapshot

Add `.covtest/` to your repository so that teammates and CI agents start with a snapshot:

```bash
git add .covtest/
git commit -m "chore: add covtest snapshot"
```

Or use [remote caching](remote-caching.md) to share snapshots without committing them.

---

## Next steps

- [How it works](concepts.md) — understand the prediction algorithm
- [Plugins](plugins.md) — wire covtest permanently into your workflow
- [Configuration](configuration.md) — tune `max_commits`, split contexts, server URL
