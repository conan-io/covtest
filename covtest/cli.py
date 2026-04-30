import argparse
import logging
import os
import os.path
import sys
from pathlib import Path

from covtest.config import read_server_url
from covtest.covtest import covtest_postprocess, predict_tests, covtest_file_location, sync_covtest_data, \
    COVTEST_FOLDER
from covtest.errors import CovTestException
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
        "--verbose", "-v",
        action="store_true",
        help="Show debug logging",
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

    if args.command == "upload":
        from covtest.remote import upload
        server_url = read_server_url(str(folder))
        if not server_url:
            print("covtest error: no server_url configured. Add it to pyproject.toml [tool.covtest] "
                  "or pytest.ini as covtest_server.", file=sys.stderr)
            return 1
        base = covtest_file_location(str(folder))
        if base is None:
            print("covtest error: no local covtest data found. Run 'covtest process' first.",
                  file=sys.stderr)
            return 1
        covtest_file, commit = base
        try:
            upload(server_url, commit, covtest_file)
        except CovTestException as e:
            logger.error(e)
            return 1
        return 0

    if args.command == "predict":
        out_info("predicting tests")
        if not args.covtest_file:
            server_url = read_server_url(str(folder))
            if server_url:
                sync_covtest_data(str(folder), server_url)
        tests = predict_tests(str(folder), args.covtest_file)
        if tests == -1:
            print("covtest error: no covtest data found — run 'covtest process' first.",
                  file=sys.stderr)
            return -1
        if tests is None:
            out_info("configuration file changed — all tests must run, no covtests.tests written")
            return 1

        # group tests by context:
        contexts = {}
        for t in tests:
            context, test = _split_context_test(t)
            contexts.setdefault(context, []).append(test)

        for context, tests in contexts.items():
            f = "covtests.tests" if not context else f"covtests.{context}.tests"
            filename = os.path.join(str(folder), COVTEST_FOLDER, f)
            save(filename, "\n".join(sorted(tests)))
            out_verbose(f"saved {len(tests)} tests -> {filename}")
        out_info("done")
        return 0

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
