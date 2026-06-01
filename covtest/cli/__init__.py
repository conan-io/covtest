import argparse
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
from covtest.output import INFO, SILENT, TRACE, set_level


def _add_verbosity_args(p, *, add_defaults=True):
    """Add -v / -q flags to a parser or subparser.

    For the top-level parser use add_defaults=True so the namespace always
    contains verbosity/quietness even when neither flag is supplied.
    For subparsers use add_defaults=False (argparse.SUPPRESS): this lets the
    flag be given *after* the subcommand while never resetting a value that
    was already set by the top-level parser.
    """
    default = 0 if add_defaults else argparse.SUPPRESS
    p.add_argument(
        "-v", dest="verbosity", action="count", default=default,
        help="Increase verbosity: -v VERBOSE, -vv DEBUG, -vvv TRACE",
    )
    p.add_argument(
        "-q", dest="quietness", action="count", default=default,
        help="Decrease verbosity: -q warnings+errors only, -qq errors only",
    )


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="covtest")
    _add_verbosity_args(parser, add_defaults=True)

    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser(
        "process",
        help="Process .coverage and store .covtest data",
    )
    p_process.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory containing .coverage",
    )
    _add_verbosity_args(p_process, add_defaults=False)

    p_predict = sub.add_parser(
        "predict",
        help="Predict tests to run from git diff and stored covtest data",
    )
    p_predict.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory",
    )
    _add_verbosity_args(p_predict, add_defaults=False)

    p_merge = sub.add_parser(
        "merge",
        help="Merge partial covtest data with the base snapshot to create a new snapshot",
    )
    p_merge.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory",
    )
    _add_verbosity_args(p_merge, add_defaults=False)

    p_upload = sub.add_parser(
        "upload",
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
    _add_verbosity_args(p_upload, add_defaults=False)

    p_diff = sub.add_parser(
        "diff",
        help="Show what covtest would predict: snapshot source, diff summary, and selected tests",
    )
    p_diff.add_argument(
        "path",
        nargs="?",
        type=Path,
        help="Project directory (defaults to current directory)",
    )
    _add_verbosity_args(p_diff, add_defaults=False)

    p_config = sub.add_parser(
        "config",
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
    _add_verbosity_args(p_config, add_defaults=False)
    _add_verbosity_args(p_config_list, add_defaults=False)

    p_debug = sub.add_parser(
        "debug",
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
    _add_verbosity_args(p_debug, add_defaults=False)
    _add_verbosity_args(p_debug_source, add_defaults=False)

    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    level = max(SILENT, min(TRACE, INFO + args.verbosity - args.quietness))
    set_level(level)
    delattr(args, "verbosity")
    delattr(args, "quietness")

    folder = args.path.resolve() if args.path else Path.cwd()
    delattr(args, "path")
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
    delattr(args, "command")
    if handler is None:
        raise AssertionError(f"unknown command: {args.command}")
    cmd_args = {k: v for k, v in vars(args).items()}
    return handler(folder, **cmd_args)


if __name__ == "__main__":
    sys.exit(main())
