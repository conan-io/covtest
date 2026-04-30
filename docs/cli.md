# CLI reference

The `covtest` command-line tool has three subcommands.

---

## covtest process

Read the `.coverage` database in the project directory and write a `.covtest` snapshot.

```
covtest process [PATH] [-cf FILE] [-v]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `PATH` | current directory | Project directory containing `.coverage` |
| `-cf`, `--covtest-file FILE` | `.covtest/<commit>.covtest` | Custom output path for the snapshot |
| `-v`, `--verbose` | off | Show per-step timing and debug logging |

**Notes:**

- Requires a clean git working tree. If the tree is dirty, covtest prints a message and exits without saving.
- The default snapshot path embeds the current HEAD commit hash, e.g. `.covtest/a3f9c12.covtest`.
- Use `-cf` to write to an explicit path — useful when testing or when the default folder structure is not desired.

**Examples:**

```bash
# Standard usage
covtest process

# Custom output file
covtest process --covtest-file=mydata.covtest

# Verbose — show per-step timing
covtest process -v
```

---

## covtest predict

Diff the working tree against the snapshot commit and write predicted test IDs to `.covtest/covtests.tests`.

```
covtest predict [PATH] [-cf FILE] [-v]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `PATH` | current directory | Project directory |
| `-cf`, `--covtest-file FILE` | auto-discovered | Use this specific snapshot instead of searching |
| `-v`, `--verbose` | off | Show per-step timing and debug logging |

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | Prediction succeeded, `covtests.tests` written |
| `1` | A configuration file was modified — all tests must run, no file written |
| `-1` | No snapshot found |

**Output files:**

| Scenario | File written |
|----------|-------------|
| No split context | `.covtest/covtests.tests` |
| Split context `windows` | `.covtest/covtests.windows.tests` |

**Examples:**

```bash
# Standard usage
covtest predict

# Then run predicted tests
pytest @.covtest/covtests.tests          # Windows
pytest $(cat .covtest/covtests.tests)    # Linux / macOS

# Verbose
covtest predict -v
```

---

## covtest upload

Upload the current snapshot to the configured remote server.

```
covtest upload [PATH] [-v]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `PATH` | current directory | Project directory containing `.covtest` data |
| `-v`, `--verbose` | off | Enable debug logging |

**Requirements:**

- `server_url` must be configured (see [Configuration — Remote caching](configuration.md#remote-caching)).
- A local snapshot for the current commit must exist. Run `covtest process` first.

**Example:**

```bash
# In CI, after covtest process
covtest upload
```

See [Remote caching](remote-caching.md) for the full CI/CD workflow.
