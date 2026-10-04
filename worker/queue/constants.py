"""Scheduler and worker loop timing (shared by queue and entrypoint)."""
import os

DEFAULT_PREFIX = str(os.getpid())
SCHEDULER_LOOP_INTERVAL = 5
DEPENDENCY_WAIT_INTERVAL = 10
TERMINATION_POLL_INTERVAL = 5
VERSION_CHECK_TIMEOUT = 15
MAX_MAIN_LOOP_BACKOFF = 60

PREDICT_LINEAR = "linear"
PREDICT_BASE = "base"
