"""Refactored queue system: job table, scheduling, and step execution.

Submodules are imported lazily so ``from worker3.queue.checkpoints import CheckPoints``
does not pull Django.
"""

__all__ = [
    "CheckPoints",
    "JobQueue",
    "Protocol",
    "Task",
    "ProcessRunner",
    "check_settings",
    "validate_worker_settings",
    "run_worker_main",
    "main",
]

_LAZY_ATTRS = {
    "CheckPoints": ("worker3.queue.checkpoints", "CheckPoints"),
    "JobQueue": ("worker3.queue.job_queue", "JobQueue"),
    "Protocol": ("worker3.queue.protocol", "Protocol"),
    "Task": ("worker3.queue.task", "Task"),
    "ProcessRunner": ("worker3.queue.process_runner", "ProcessRunner"),
    "check_settings": ("worker3.queue.scheduler", "check_settings"),
    "validate_worker_settings": ("worker3.queue.scheduler", "validate_worker_settings"),
    "run_worker_main": ("worker3.queue.scheduler", "run_worker_main"),
    "main": ("worker3.queue.scheduler", "main"),
}


def __getattr__(name):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    import importlib

    value = getattr(importlib.import_module(module_name), attr)
    globals()[name] = value
    return value
