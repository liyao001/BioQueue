#!/usr/bin/env python
# coding=utf-8
"""BioQueue worker entrypoint (modular layout under ``worker3.queue``)."""
import logging
import os
import sys

# Repo root on path so ``import worker3`` works when executed as a script.
# Drop this directory from sys.path: ``python bioqueue.py`` would otherwise
# let ``worker3/queue`` shadow the stdlib ``queue`` module (Django/asgiref crash).
_SCRIPT_DIR = os.path.realpath(os.path.abspath(os.path.dirname(__file__)))
_REPO_ROOT = os.path.abspath(os.path.join(_SCRIPT_DIR, ".."))
sys.path[:] = [
    p
    for p in sys.path
    if os.path.realpath(os.path.abspath(p or os.getcwd())) != _SCRIPT_DIR
]
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import worker3._bootstrap  # noqa: F401 — stdlib queue visible; repo root on path

import worker3.django_initial  # noqa: F401 — Django setup before QueueDB imports

from worker3.cli import parse_args
from worker3.queue.constants import DEFAULT_PREFIX
from worker3.queue.job_queue import format_runner_list, resolve_slave
from worker3.queue.scheduler import run_worker_main

logging.basicConfig(
    format="%(name)s - %(asctime)s - %(levelname)s: %(message)s",
    datefmt="%d-%b-%y %H:%M:%S",
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(os.getcwd(), "%s.log" % DEFAULT_PREFIX)),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("BioQueue")


def main(n_retries: int = 3, slave=None, schedule=None, predict=None) -> None:
    """CLI-compatible alias for :func:`run_worker_main`."""
    run_worker_main(n_retries=n_retries, slave=slave, schedule=schedule, predict=predict)


def cli(argv=None) -> None:
    args = parse_args(argv)

    if args.log_level:
        level = getattr(logging, args.log_level)
    elif args.verbose:
        level = logging.DEBUG
    elif args.concise:
        level = logging.WARNING
    else:
        level = logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    logger.setLevel(level)
    for handler in root_logger.handlers:
        handler.setLevel(level)

    if args.list_runners:
        try:
            print(format_runner_list())
        except Exception:
            logger.exception("Failed to list runners")
            raise SystemExit(1)
        return

    if args.slave not in (None, ""):
        try:
            resolve_slave(args.slave)
        except ValueError as exc:
            logger.error("%s", exc)
            raise SystemExit(2)

    main(
        n_retries=args.n_retry,
        slave=args.slave,
        schedule=args.schedule,
        predict=args.predict,
    )


if __name__ == "__main__":
    cli()
