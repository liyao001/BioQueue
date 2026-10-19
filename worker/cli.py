"""Argparse for ``python -m worker`` (no Django import)."""
import argparse


def build_parser():
    parser = argparse.ArgumentParser(description="BioQueue worker")
    parser.add_argument(
        "--n-retry",
        type=int,
        default=3,
        help="Number of retries allowed when a transaction to the database is failed",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=False,
        help="Enable DEBUG logging, including SSH and scheduler commands",
    )
    verbosity.add_argument(
        "--concise",
        action="store_true",
        default=False,
        help="Show warnings and errors only",
    )
    verbosity.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        type=str.upper,
        default=None,
        help="Set the logging level explicitly (default: INFO)",
    )
    parser.add_argument(
        "--slave",
        "--runner",
        dest="slave",
        default=None,
        metavar="NAME_OR_ID",
        help=(
            "Bind this worker to a runner (Slave name or id). "
            "Only fetches jobs assigned to that runner. "
            "Unpinned workers only fetch jobs with no runner assigned."
            "Overrides env.slave / cluster.slave in config."
        ),
    )
    parser.add_argument(
        "--list-runners",
        "--list-slaves",
        dest="list_runners",
        action="store_true",
        default=False,
        help="Print known runners (Slave rows) and exit",
    )
    parser.add_argument(
        "--schedule",
        choices=("greedy", "fifo"),
        default=None,
        help=(
            "Dispatch policy. greedy (default): largest CPU that fits. "
            "fifo: oldest job first; an oversized head blocks later jobs. "
            "Overrides env.schedule."
        ),
    )
    parser.add_argument(
        "--fifo",
        dest="schedule",
        action="store_const",
        const="fifo",
        help="Shortcut for --schedule fifo",
    )
    parser.add_argument(
        "--predict",
        choices=("linear", "base"),
        default=None,
        help=(
            "Resource forecast. linear (default): intercept + slope * input size. "
            "base: intercept only (smoother; does not grow with workspace size). "
            "Overrides ml.predict."
        ),
    )
    parser.add_argument(
        "--predict-base",
        "--predict-b",
        dest="predict",
        action="store_const",
        const="base",
        help="Shortcut for --predict base (use only the intercept / b term)",
    )
    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)
