# Configuration

## covtest.ini

Create `covtest.ini` in your project root (or `test/covtest.ini` / `tests/covtest.ini`):

```ini
[covtest]
# How many past commits to search for a snapshot (default: 20)
max_commits = 20

# Seconds to cache "not found on server" responses (default: 3600)
server_cache_ttl = 3600

# Remote server URL for upload/download (optional)
server_url = https://covtest.example.com/myproject
```

The same options are supported in `pyproject.toml`:

```toml
[tool.covtest]
max_commits = 20
server_cache_ttl = 3600
server_url = "https://covtest.example.com/myproject"
```

Or in `pytest.ini` / `setup.cfg` as `covtest_server` (for the server URL only).

---

## Options

### max_commits

**Default:** `20`

How far back in git history covtest searches for a snapshot when none exists for the current commit. If you make 5 commits before refreshing the snapshot, covtest still finds the snapshot 5 commits back and predicts relative to that.

```ini
max_commits = 50
```

Increase this in long-running feature branches where the snapshot may be many commits behind.

---

### server_cache_ttl

**Default:** `3600` (one hour)

When a commit is checked against the remote server and not found, covtest caches that negative result for this many seconds. This prevents hammering the server on repeated `covtest predict` calls in a session.

```ini
server_cache_ttl = 7200
```

---

### server_url

**Default:** not set

Base URL of the remote covtest server. When set, `covtest predict` (and `-p covtest.predict`) will attempt to download a snapshot for the current commit if none is found locally.

```ini
server_url = https://covtest.example.com/myproject
```

See [Remote caching](remote-caching.md) for server setup.

---

## Split contexts

When the same codebase is tested under multiple configurations — different operating systems, Python versions, or feature flags — you can tag each run with a context name so covtest tracks them independently.

**Step 1 — Tag the coverage run:**

```ini
# .coveragerc  (or pytest.ini [coverage:run] section)
[run]
context = windows
```

**Step 2 — Process each run separately:**

```bash
# On Windows CI after running the windows test suite
covtest process --covtest-file=.covtest/windows.covtest

# On Linux CI
covtest process --covtest-file=.covtest/linux.covtest
```

**Step 3 — Predict per context:**

```bash
covtest predict --covtest-file=.covtest/windows.covtest
# writes .covtest/covtests.windows.tests

covtest predict --covtest-file=.covtest/linux.covtest
# writes .covtest/covtests.linux.tests
```

**Step 4 — Run per context:**

```bash
pytest @.covtest/covtests.windows.tests -m windows
pytest @.covtest/covtests.linux.tests   -m linux
```

With the plugin, pass `covtest_context` via a pytest ini option or fixture to route to the right file automatically.

---

## Config-file guard

When any of the following files is modified, covtest cannot safely predict which tests are affected and skips filtering — all tests run:

```
requirements*.txt    pyproject.toml    setup.py    setup.cfg
pytest.ini           tox.ini           .coveragerc  conftest.py
```

`covtest predict` exits with code `1` in this case. The `-p covtest.predict` plugin simply deselects nothing and lets the full suite run.
