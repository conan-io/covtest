import argparse
import logging
import sys
from pathlib import Path

from covtest.cli.commands import (
    _split_context_test,
    cmd_config,
    cmd_debug,
    cmd_diff,
    cmd_merge,
    cmd_predict,
    cmd_process,
    cmd_upload,
)
from covtest.output import set_verbose


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


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    verbose = getattr(args, "verbose", False)
    set_verbose(verbose)
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")

    folder = args.path.resolve() if args.path else Path.cwd()
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 1

    dispatch = {
        "process": cmd_process,
        "merge": cmd_merge,
        "upload": cmd_upload,
        "predict": cmd_predict,
        "diff": cmd_diff,
        "config": cmd_config,
        "debug": cmd_debug,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        raise AssertionError(f"unknown command: {args.command}")
    return handler(args, folder)


if __name__ == "__main__":
    sys.exit(main())
