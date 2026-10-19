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

# User stop request. Not a process exit status: those are 0–255, and a
# signal death is negative. Exit code 2 must stay a normal step failure.
STEP_USER_INTERRUPTED = 256
