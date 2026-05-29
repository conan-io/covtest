import logging
import os
import os.path
import sys

from covtest.config import read_config, config_list_info
from covtest.covtest import covtest_merge, covtest_postprocess, predict_tests, COVTEST_FOLDER
from covtest.errors import CovTestException
from covtest.git import git_commits
from covtest.output import out_info, out_verbose
from covtest.util.files import save

logger = logging.getLogger(__name__)


def _split_context_test(t):
    bracket = t.find("[")
    pipe = t.find("|", 0, bracket if bracket != -1 else len(t))
    if pipe == -1:
        return None, t
    return t[:pipe], t[pipe + 1:]


def cmd_process(args, folder):
    out_info("processing coverage data")
    try:
        covtest_postprocess(str(folder), args.covtest_file)
    except CovTestException as e:
        logger.error(e)
        return -1
    out_info("done")
    return 0


def cmd_merge(args, folder):
    out_info("merging covtest data")
    try:
        covtest_merge(str(folder))
    except CovTestException as e:
        print(f"covtest error: {e}", file=sys.stderr)
        return 1
    out_info("done")
    return 0


def cmd_upload(args, folder):
    from covtest.remote import upload
    cfg = read_config(str(folder))
    server_url = args.url or cfg.get("server_url")
    if not server_url:
        print("covtest error: no server_url configured. "
              "Pass --url, set COVTEST_URL, or add server_url to covtest.ini.",
              file=sys.stderr)
        return 1
    auth_user = args.user or cfg.get("auth_user")
    auth_password = args.password or cfg.get("auth_password")
    auth_token = args.token or cfg.get("auth_token")
    commit = git_commits(folder)[0]
    covtest_file = os.path.join(folder, COVTEST_FOLDER, commit + ".covtest")
    if not os.path.exists(covtest_file):
        raise CovTestException(f"The covtest file to upload does not exist: {covtest_file}")
    try:
        upload(server_url, covtest_file,
               user=auth_user, password=auth_password, token=auth_token)
    except CovTestException as e:
        logger.error(e)
        return 1
    return 0


def cmd_predict(args, folder):
    from covtest.covtest import get_base_commit
    out_info("predicting tests")

    cfg = read_config(folder)
    base_commit = get_base_commit(folder, cfg)
    if base_commit is None:
        out_info("no covtest data found — running all tests")
        return -1

    tests = predict_tests(folder, base_commit)
    if tests == -1:
        print("covtest error: no covtest data found — run 'covtest process' first.",
              file=sys.stderr)
        return -1
    if tests is None:
        out_info("configuration file changed — all tests must run, no covtests.tests written")
        return 1

    out_info(f"Predicted {len(tests)} tests")
    contexts = {}
    for t in tests:
        context, test = _split_context_test(t)
        contexts.setdefault(context, []).append(test)

    for context, tests in contexts.items():
        f = "covtests.tests" if not context else f"covtests.{context}.tests"
        out_info(f"Saving file with predicted tests {f}")
        filename = os.path.join(str(folder), COVTEST_FOLDER, f)
        save(filename, "\n".join(sorted(tests)))
        out_verbose(f"saved {len(tests)} tests -> {filename}")
    out_info("done")
    return 0


def cmd_diff(args, folder):
    from covtest.covtest import get_base_commit
    from covtest.util.run import run
    from covtest.util.files import chdir

    cfg = read_config(folder)
    base_commit = get_base_commit(folder, cfg)

    if base_commit is None:
        print("covtest error: no covtest data found — run 'covtest process' first.",
              file=sys.stderr)
        return -1

    out_info(f"git diff: HEAD vs {base_commit[:8]}")
    with chdir(str(folder)):
        stat_out, _ = run(f"git diff --stat {base_commit}")
    if stat_out.strip():
        for line in stat_out.strip().splitlines():
            print(f"  {line}")
    else:
        print("  (no changes since snapshot)")

    return 0


def cmd_config(args, folder):
    if args.config_command == "list":
        info = config_list_info(str(folder))
        _SENSITIVE_KEYS = {"auth_password", "auth_token"}
        _SENSITIVE_ENVS = {"COVTEST_PASSWORD", "COVTEST_TOKEN"}
        _ALL_KEYS = [
            "max_commits", "server_cache_ttl",
            "server_url", "auth_user", "auth_password", "auth_token",
        ]

        if info["config_file"]:
            print(f"Config file: {info['config_file']}")
        else:
            print("Config file: (none found)")
            print("  Searched:")
            for c in info["candidates"]:
                print(f"    {c}")
            print("  (and parent directories up to filesystem root)")

        print("\nEnvironment variables:")
        for env_var, val in info["env"].items():
            if val:
                display = "***" if env_var in _SENSITIVE_ENVS else val
                print(f"  {env_var:<20} = {display}")
            else:
                print(f"  {env_var:<20} = (not set)")

        print("\nEffective configuration:")
        cfg = info["effective"]
        for key in _ALL_KEYS:
            val = cfg.get(key)
            if val is None:
                print(f"  {key:<20} = (not set)")
            else:
                display = "***" if key in _SENSITIVE_KEYS else val
                print(f"  {key:<20} = {display}")

        return 0


def cmd_debug(args, folder):
    if args.debug_command == "source":
        import fnmatch
        from covtest.covtest_data import CovTestData
        from covtest.covtest import get_base_commit

        cfg = read_config(folder)
        base_commit = get_base_commit(folder, cfg)
        if base_commit is None:
            print("covtest error: no covtest data found — run 'covtest process' first.",
                  file=sys.stderr)
            return -1

        covtest_file = folder / COVTEST_FOLDER / (base_commit + ".covtest")
        out_info(f"snapshot: {covtest_file}")

        covdata = CovTestData.load(covtest_file)
        pattern = args.pattern

        matched = {
            fp: line_data
            for fp, line_data in covdata.py_files.items()
            if fnmatch.fnmatch(fp, pattern) or fnmatch.fnmatch(os.path.basename(fp), pattern)
        }

        if not matched:
            print(f"No files matching '{pattern}' found in snapshot.")
            return 0

        for filepath, line_data in sorted(matched.items()):
            src_path = os.path.join(str(folder), filepath.replace("/", os.sep))

            if os.path.isfile(src_path):
                with open(src_path, encoding="utf-8", errors="replace") as fh:
                    source_lines = fh.read().splitlines()
                n_lines = len(source_lines)
            else:
                source_lines = None
                n_lines = max(line_data.keys(), default=0)

            n_covered = len(line_data)
            width = len(str(n_lines))
            header = f"{filepath}  ({n_covered} lines with test coverage)"
            print(f"\n{header}")
            print("─" * len(header))

            if source_lines:
                for lineno, src_line in enumerate(source_lines, 1):
                    tests = line_data.get(lineno)
                    print(f"  {lineno:{width}} │ {src_line}")
                    if tests:
                        for t in sorted(tests):
                            print(f"  {' ' * width} │   ↳ {t}")
            else:
                print(f"  (source not found at {src_path} — snapshot data only)")
                for lineno, tests in sorted(line_data.items()):
                    print(f"  {lineno:{width}} │ <line {lineno}>")
                    for t in sorted(tests):
                        print(f"  {' ' * width} │   ↳ {t}")

        return 0
