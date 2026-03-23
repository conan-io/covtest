import argparse
import logging
import os.path
import sys
from pathlib import Path

from covtest.covtest import covtest_postprocess, predict_tests
from covtest.errors import CovTestException
from covtest.util.files import save


def _parse_args(argv):
    parser = argparse.ArgumentParser(prog="covtest")
    sub = parser.add_subparsers(dest="command", required=True)

    ctx = argparse.ArgumentParser(add_help=False)
    ctx.add_argument(
        "--context",
        default=None,
        metavar="TEXT",
        help="Covtest context (same as pytest --covtest-context)",
    )

    p_process = sub.add_parser(
        "process",
        parents=[ctx],
        help="Process .coverage and store .covtest data",
    )
    p_process.add_argument(
        "path",
        type=Path,
        help="Project directory containing .coverage",
    )
    p_process.add_argument(
        "-cf", "--covtest-file",
        help="Covtest fiel location"
    )
    p_process.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )

    p_predict = sub.add_parser(
        "predict",
        parents=[ctx],
        help="Predict tests to run from git diff and stored covtest data",
    )
    p_predict.add_argument(
        "path",
        type=Path,
        help="Project directory",
    )
    p_predict.add_argument(
        "-cf", "--covtest-file",
        help="Covtest fiel location"
    )

    return parser.parse_args(argv)


def main(argv=None):
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")
    logger = logging.getLogger(__name__)

    folder = args.path.resolve()
    if not folder.is_dir():
        print(f"Not a directory: {folder}", file=sys.stderr)
        return 1

    context = args.context

    if args.command == "process":
        logger.info("Processing coverage data")
        try:
            covtest_postprocess(str(folder), context, args.covtest_file)
        except CovTestException as e:
            logger.error(e)
            return -1
        logger.info("Processing done")
        return 0

    if args.command == "predict":
        tests = predict_tests(str(folder), context, args.covtest_file)
        if tests is None:
            print(
                "covtest: no stored data for this repo/context (run tests with covtest first)",
                file=sys.stderr,
            )
            return 1
        filename = os.path.abspath("covtests.tests")
        save(filename, "\n".join(sorted(tests)))
        logging.info(f"Saved tests to run in: {filename}")
        return 0

    raise AssertionError(f"unknown command: {args.command}")


if __name__ == "__main__":
    sys.exit(main())
