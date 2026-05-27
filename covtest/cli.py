import argparse
import logging
import os
import os.path
import sys
from pathlib import Path

from covtest.config import read_config, config_list_info
from covtest.covtest import covtest_merge, covtest_postprocess, predict_tests, COVTEST_FOLDER
from covtest.errors import CovTestException
from covtest.git import git_commits
from covtest.output import out_info, out_verbose, set_verbose
from covtest.util.files import save


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="covtest")
    sub = parser.add_subparsers(dest="command", required=True)

    ctx = argparse.ArgumentParser(add_help=False)

    p_process = sub.add_parser(
        "process",
        parents=[ctx],
        help="Process .coverage and store .covtest data",
    )
    p_process.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory containing .coverage",
    )
    p_process.add_argument(
        "-cf", "--covtest-file",
        help="Covtest file location"
    )
    p_process.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-step timing and debug logging",
    )

    p_predict = sub.add_parser(
        "predict",
        parents=[ctx],
        help="Predict tests to run from git diff and stored covtest data",
    )
    p_predict.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory",
    )
    p_predict.add_argument(
        "-cf", "--covtest-file",
        help="Covtest file location"
    )
    p_predict.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-step timing and debug logging",
    )

    p_merge = sub.add_parser(
        "merge",
        parents=[ctx],
        help="Merge partial covtest data with the base snapshot to create a new snapshot",
    )
    p_merge.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory",
    )
    p_merge.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-step timing",
    )

    p_upload = sub.add_parser(
        "upload",
        parents=[ctx],
        help="Upload .covtest data for the current commit to the configured server",
    )
    p_upload.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory containing .covtest data",
    )
    p_upload.add_argument(
        "--url", "-U",
        metavar="URL",
        help="Server URL (overrides covtest.ini; env: COVTEST_URL)",
    )
    p_upload.add_argument(
        "--user", "-u",
        metavar="USER",
        help="Username for HTTP basic auth (env: COVTEST_USER)",
    )
    p_upload.add_argument(
        "--password", "-p",
        metavar="PASSWORD",
        help="Password for HTTP basic auth (env: COVTEST_PASSWORD)",
    )
    p_upload.add_argument(
        "--token", "-t",
        metavar="TOKEN",
        help="Bearer token for token-based auth, e.g. JFrog Artifactory access token or API key "
             "(env: COVTEST_TOKEN)",
    )
    p_upload.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show debug logging",
    )

    p_diff = sub.add_parser(
        "diff",
        parents=[ctx],
        help="Show what covtest would predict: snapshot source, diff summary, and selected tests",
    )
    p_diff.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory (defaults to current directory)",
    )
    p_diff.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show extra debug output",
    )

    p_config = sub.add_parser(
        "config",
        parents=[ctx],
        help="Inspect covtest configuration",
    )
    config_sub = p_config.add_subparsers(dest="config_command", required=True)
    p_config_list = config_sub.add_parser(
        "list",
        help="Show effective configuration values and the files/env vars they come from",
    )
    p_config_list.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory (defaults to current directory)",
    )

    p_debug = sub.add_parser(
        "debug",
        parents=[ctx],
        help="Debugging and introspection commands",
    )
    debug_sub = p_debug.add_subparsers(dest="debug_command", required=True)
    p_debug_source = debug_sub.add_parser(
        "source",
        help="Show a source file line by line with the tests covering each line",
    )
    p_debug_source.add_argument(
        "pattern",
        help="File pattern to match against the snapshot, e.g. '*mysource.py'",
    )
    p_debug_source.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory (defaults to current directory)",
    )

    return parser.parse_args(argv)


def _split_context_test(t):
    """Split a test string into (context, test_id).

    The format is either ``context|test_path[params]`` or plain ``test_path[params]``.
    The context separator ``|`` is always at the outermost level — before the first
    ``[`` — while ``|`` characters inside ``[...]`` belong to parametrize arguments
    and must not be treated as separators.

    Examples::

        "windows|test_file.py::test_func"         -> ("windows", "test_file.py::test_func")
        "windows|test_file.py::test_func[a | b]"  -> ("windows", "test_file.py::test_func[a | b]")
        "test_file.py::test_func[a | b]"          -> (None,      "test_file.py::test_func[a | b]")
        "test_file.py::test_func"                 -> (None,      "test_file.py::test_func")
    """
    bracket = t.find("[")
    # Only look for the separator before the first '['; if no '[' exists, search the whole string
    pipe = t.find("|", 0, bracket if bracket != -1 else len(t))
    if pipe == -1:
        return None, t
    return t[:pipe], t[pipe + 1:]


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    verbose = getattr(args, "verbose", False)
    set_verbose(verbose)
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    folder = args.path.resolve() if args.path else Path.cwd()
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 1

    if args.command == "process":
        out_info("processing coverage data")
        try:
            covtest_postprocess(str(folder), args.covtest_file)
        except CovTestException as e:
            logger.error(e)
            return -1
        out_info("done")
        return 0

    if args.command == "merge":
        out_info("merging covtest data")
        try:
            covtest_merge(str(folder))
        except CovTestException as e:
            print(f"covtest error: {e}", file=sys.stderr)
            return 1
        out_info("done")
        return 0

    if args.command == "upload":
        from covtest.remote import upload
        cfg = read_config(str(folder))
        # CLI flag > env var (already merged into cfg) > covtest.ini
        server_url = args.url or cfg.get("server_url")
        if not server_url:
            print("covtest error: no server_url configured. "
                  "Pass --url, set COVTEST_URL, or add server_url to covtest.ini.",
                  file=sys.stderr)
            return 1
        auth_user = args.user or cfg.get("auth_user")
        auth_password = args.password or cfg.get("auth_password")
        auth_token = args.token or cfg.get("auth_token")
        commit = git_commits(folder)[0]  # just the last, current commit
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

    if args.command == "predict":
        from covtest.covtest import get_base_commit
        out_info("predicting tests")

        project_folder = folder
        cfg = read_config(project_folder)
        base_commit = get_base_commit(project_folder, cfg)
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
        # group tests by context:
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

    if args.command == "diff":
        from covtest.covtest import get_base_commit
        from covtest.util.run import run
        from covtest.util.files import chdir

        project_folder = folder
        cfg = read_config(project_folder)
        base_commit = get_base_commit(project_folder, cfg)

        if base_commit is None:
            print("covtest error: no covtest data found — run 'covtest process' first.",
                  file=sys.stderr)
            return -1

        # Diff summary
        out_info(f"git diff: HEAD vs {base_commit[:8]}")
        with chdir(str(folder)):
            stat_out, _ = run(f"git diff --stat {base_commit}")
        if stat_out.strip():
            for line in stat_out.strip().splitlines():
                print(f"  {line}")
        else:
            print("  (no changes since snapshot)")

        return 0

    if args.command == "config":
        if args.config_command == "list":
            info = config_list_info(str(folder))
            _SENSITIVE_KEYS = {"auth_password", "auth_token"}
            _SENSITIVE_ENVS = {"COVTEST_PASSWORD", "COVTEST_TOKEN"}
            _ALL_KEYS = [
                "max_commits", "server_cache_ttl",
                "server_url", "auth_user", "auth_password", "auth_token",
            ]

            # Config file
            if info["config_file"]:
                print(f"Config file: {info['config_file']}")
            else:
                print("Config file: (none found)")
                print("  Searched:")
                for c in info["candidates"]:
                    print(f"    {c}")
                print("  (and parent directories up to filesystem root)")

            # Environment variables
            print("\nEnvironment variables:")
            for env_var, val in info["env"].items():
                if val:
                    display = "***" if env_var in _SENSITIVE_ENVS else val
                    print(f"  {env_var:<20} = {display}")
                else:
                    print(f"  {env_var:<20} = (not set)")

            # Effective values
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

    if args.command == "debug":
        if args.debug_command == "source":
            import fnmatch
            from covtest.covtest_data import CovTestData
            from covtest.covtest import get_base_commit

            project_folder = folder
            cfg = read_config(project_folder)
            base_commit = get_base_commit(project_folder, cfg)
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

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
