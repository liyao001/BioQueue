"""Build per-step cluster extras from settings, job fields, and special parameters.

Later sources win: cluster config → job/step GPU flags → Job.array_setting →
``Cluster*`` keys in the job parameter string (``key=value;...``).
"""
from __future__ import annotations


PARAM_TO_EXTRA = {
    "ClusterGpus": "gpus",
    "ClusterGres": "gres",
    "ClusterPartition": "partition",
    "ClusterQueue": "partition",
    "ClusterTime": "walltime",
    "ClusterMem": "mem",
    "ClusterExclude": "exclude",
    "ClusterExtra": "extra",
    "ClusterArray": "array",
    "ClusterPrologue": "prologue",
    "ClusterEpilogue": "epilogue",
}


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _opt(mapping, *keys):
    if not mapping:
        return ""
    for key in keys:
        if key in mapping:
            text = _text(mapping.get(key))
            if text:
                return text
        lower = key.lower()
        if lower != key and lower in mapping:
            text = _text(mapping.get(lower))
            if text:
                return text
    return ""


def _user_options(job):
    options = getattr(job, "user_options", None)
    if not isinstance(options, dict):
        return {}
    cleaned = {}
    for key, value in options.items():
        name = _text(key)
        if name:
            cleaned[name] = value
    return cleaned


def _job_db(job):
    return getattr(job, "db_obj", None)


def _truthy_gpu(value):
    if value in (True, 1, "1"):
        return True
    try:
        return int(value) == 1
    except (TypeError, ValueError):
        return False


def _remote_from_slave_and_settings(slave, cluster):
    host = _opt(cluster, "remote_host")
    user = _opt(cluster, "remote_user")
    key = _opt(cluster, "remote_key")
    bin_prefix = _opt(cluster, "bin_prefix")
    scripts_dir = _opt(cluster, "remote_scripts_dir")
    result_root = _opt(cluster, "remote_result_root")
    log_root = _opt(cluster, "remote_log_root")
    workdir = _opt(cluster, "remote_workdir")
    if slave is not None:
        host = _text(getattr(slave, "ssh_connection", None)) or host
        user = _text(getattr(slave, "ssh_user", None)) or user
        key = _text(getattr(slave, "ssh_key", None)) or key
        bin_prefix = _text(getattr(slave, "cluster_manager_path", None)) or bin_prefix
    if not host:
        return None
    if not scripts_dir:
        if user:
            scripts_dir = "/home/%s/bioqueue-scripts" % user
        else:
            scripts_dir = "/tmp/bioqueue-scripts"
    # Same convention as worker/bioqueue_remote.py: /home/<user>/workdir/<slurm_id>/
    if not result_root:
        result_root = "/home/%s/workdir" % user if user else "/tmp/bioqueue-workdir"
    return {
        "host": host,
        "user": user,
        "key": key,
        "bin_prefix": bin_prefix,
        "scripts_dir": scripts_dir,
        "result_root": result_root,
        "log_root": log_root,
        "workdir": workdir,
    }


def _split_array_setting(setting, array):
    sbatch_cli = ""
    text = _text(setting)
    if text.startswith("-"):
        sbatch_cli = text
    elif text and not array:
        array = text
    return array, sbatch_cli


def walltime_to_seconds(text):
    """Best-effort parse of Slurm/LSF-ish time strings to seconds."""
    text = _text(text)
    if not text:
        return 0
    days = 0
    if "-" in text:
        day_part, text = text.split("-", 1)
        try:
            days = int(day_part)
        except ValueError:
            days = 0
    parts = text.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return days * 86400
    if len(nums) == 3:
        hours, minutes, seconds = nums
    elif len(nums) == 2:
        hours, minutes = nums
        seconds = 0
    elif len(nums) == 1:
        return days * 86400 + nums[0] * 60
    else:
        return 0
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def resolve_cluster_type(cluster, job=None):
    cluster = cluster or {}
    declared = _text(cluster.get("type"))
    if declared:
        return declared
    db = _job_db(job) if job is not None else None
    slave = getattr(db, "slave", None) if db is not None else None
    if slave is not None and getattr(slave, "cluster_manager", 0) == 1:
        return "Slurm"
    return ""


def build_cluster_request(job, step, cluster, allocate_cpu, allocate_mem, allocate_vrt, queue, walltime):
    """Merge config / job / step into submit args plus a backend extras dict."""
    cluster = cluster or {}
    user = _user_options(job)
    db = _job_db(job)

    partition = (
        _opt(user, "ClusterPartition", "ClusterQueue")
        or _opt(cluster, "partition", "new_queue", "queue")
        or _text(queue)
    )
    walltime = _opt(user, "ClusterTime") or _text(walltime) or _opt(cluster, "walltime")
    mem = _opt(user, "ClusterMem") or _text(allocate_mem) or _opt(cluster, "mem")
    gpus = _opt(user, "ClusterGpus") or _opt(cluster, "gpus")
    gres = _opt(user, "ClusterGres") or _opt(cluster, "gres")
    exclude = _opt(user, "ClusterExclude") or _opt(cluster, "exclude")
    extra = _opt(user, "ClusterExtra") or _opt(cluster, "extra")
    prologue = _opt(user, "ClusterPrologue") or _opt(cluster, "prologue")
    epilogue = _opt(user, "ClusterEpilogue") or _opt(cluster, "epilogue")
    array = _opt(user, "ClusterArray") or _opt(cluster, "array")

    setting = ""
    if db is not None:
        setting = _text(getattr(db, "array_setting", None))
    if not setting:
        setting = _text(getattr(job, "array_setting", None))
    array, sbatch_cli = _split_array_setting(setting, array)

    if not gpus and not gres:
        gpu_step = getattr(step, "gpu_step", False)
        is_gpu_job = False
        if db is not None:
            is_gpu_job = _truthy_gpu(getattr(db, "is_gpu_job", 0))
        if not is_gpu_job:
            is_gpu_job = _truthy_gpu(getattr(job, "is_gpu_job", 0))
        if gpu_step or is_gpu_job:
            gpus = "1"

    slave = None
    if db is not None:
        slave = getattr(db, "slave", None)
    remote = _remote_from_slave_and_settings(slave, cluster)

    gpu_style = _opt(cluster, "gpu_style") or "gres"
    poll_max = _opt(cluster, "poll_max_seconds") or str(walltime_to_seconds(walltime) + 3600 if walltime_to_seconds(walltime) else 24 * 3600)
    extras = {
        "gpus": gpus,
        "gres": gres,
        "exclude": exclude,
        "extra": extra,
        "partition": partition,
        "array": array,
        "sbatch_cli": sbatch_cli,
        "prologue": prologue,
        "epilogue": epilogue,
        "requeue": _opt(cluster, "requeue") or "1",
        "bin_prefix": _opt(cluster, "bin_prefix"),
        "gpu_style": gpu_style,
        "poll_max_seconds": poll_max,
        # Opt-in. bioqueue_remote uploaded the script and ran in place (NFS /
        # cluster paths). Staging host workspaces by default broke those sites.
        "stage_in": _opt(cluster, "stage_in") or "0",
        "stage_inputs": list(getattr(job, "job_input_files", None) or []),
        "remote": remote,
        "body": None,
    }
    return {
        "cpu": allocate_cpu,
        "mem": mem,
        "vrt": allocate_vrt,
        "queue": partition,
        "walltime": walltime,
        "extras": extras,
        "cluster_type": resolve_cluster_type(cluster, job),
    }
