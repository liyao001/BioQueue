"""Slurm backend: render a self-contained sbatch script, submit locally or over SSH."""
from __future__ import print_function

import hashlib
import logging
import os
import posixpath
import re
import shlex
import subprocess
import threading
import time

logger = logging.getLogger("BioQueue.cluster.slurm")

# 0 success, 1 running, 2 pending, 3 unknown/retryable, -1 failed
STATUS_UNKNOWN = 3
# One squeue covers every in-flight job.
POLL_RUNNING_SECONDS = 300
POLL_PENDING_SECONDS = 300
_POLL_COALESCE_SECONDS = 0.5
_POLL_WAIT_SECONDS = POLL_RUNNING_SECONDS + 600
_SQUEUE_CHUNK = 100

TERMINAL_OK = {"COMPLETED"}
TERMINAL_FAIL = {
    "FAILED",
    "CANCELLED",
    "CANCELED",
    "TIMEOUT",
    "NODE_FAIL",
    "OUT_OF_MEMORY",
    "PREEMPTED",
    "BOOT_FAIL",
    "DEADLINE",
    "SPECIAL_EXIT",
    "REVOKED",
}
RUNNING_STATES = {
    "RUNNING",
    "COMPLETING",
    "SUSPENDED",
    "CONFIGURING",
    "RESIZING",
    "SIGNALING",
    "STAGE_OUT",
}
PENDING_STATES = {"PENDING", "REQUEUED", "RESV_DEL_HOLD", "REQUEUE_HOLD"}

_SBATCH_ID = re.compile(r"Submitted batch job\s+(\d+)", re.IGNORECASE)
_INVALID_JOB = re.compile(
    r"Invalid job id|invalid job id specified|unable to look up job",
    re.IGNORECASE,
)
_MUX_STALE = re.compile(
    r"Control socket|mux_client|muxserver|ControlSocket",
    re.IGNORECASE,
)


def _decode(blob):
    if blob is None:
        return ""
    if isinstance(blob, bytes):
        return blob.decode("utf-8", "replace")
    return str(blob)


def _text(value):
    if value is None:
        return ""
    return str(value).strip()


def _extras(extras):
    return extras or {}


def _bin(prefix, name):
    prefix = _text(prefix)
    if prefix and not prefix.endswith("/"):
        prefix += "/"
    return prefix + name


def _flag_line(flag, value):
    value = _text(value)
    if not value:
        return ""
    if value.startswith("#"):
        return value
    if value.startswith("--"):
        return "#SBATCH " + value
    return "#SBATCH %s %s" % (flag, value)


def gres_line(gpus, gres, gpu_style="gres"):
    gres = _text(gres)
    if gres:
        if gres.startswith("#"):
            return gres
        if gres.startswith("--"):
            return "#SBATCH " + gres
        if gres.startswith("gres="):
            return "#SBATCH --" + gres
        if "gpu" not in gres.lower():
            gres = "gpu:%s" % gres
        return "#SBATCH --gres=%s" % gres
    gpus = _text(gpus)
    if not gpus:
        return ""
    style = (_text(gpu_style) or "gres").lower()
    lines = []
    if style in ("gres", "both", ""):
        lines.append("#SBATCH --gres=gpu:%s" % gpus)
    if style in ("gpus", "both"):
        lines.append("#SBATCH --gpus=%s" % gpus)
    if not lines:
        lines.append("#SBATCH --gres=gpu:%s" % gpus)
    return "\n".join(lines)


def extra_header_lines(extra):
    lines = []
    for raw in _text(extra).replace(";", "\n").splitlines():
        piece = raw.strip()
        if not piece:
            continue
        if piece.startswith("#SBATCH"):
            lines.append(piece)
        elif piece.startswith("-"):
            lines.append("#SBATCH " + piece)
    return "\n".join(lines)


def _normalize_state(state):
    text = str(state or "").strip().upper()
    if "+" in text:
        text = text.split("+", 1)[0]
    text = text.rstrip("*")
    # sacct appends who cancelled: "CANCELLED by 1353245".
    if " BY " in text:
        text = text.split(" BY ", 1)[0].strip()
    return text


def status_from_states(states, requeue=True):
    states = [_normalize_state(s) for s in (states or []) if s]
    states = [s for s in states if s]
    if not states:
        return 2
    # --requeue is the default. A preempted job is expected to come back,
    # so keep watching instead of treating that state as a finished failure.
    if requeue and any(s == "PREEMPTED" for s in states):
        if any(s in RUNNING_STATES for s in states):
            return 1
        if any(s in TERMINAL_FAIL and s != "PREEMPTED" for s in states):
            return -1
        return 2
    if all(s in TERMINAL_OK or s in TERMINAL_FAIL for s in states):
        if all(s in TERMINAL_OK for s in states):
            return 0
        return -1
    if any(s in RUNNING_STATES for s in states):
        return 1
    if any(s in PENDING_STATES for s in states):
        return 2
    return 1


def parse_sbatch_job_id(stdout):
    match = _SBATCH_ID.search(_decode(stdout))
    if match:
        return match.group(1)
    return 0


def parse_squeue_states(stdout):
    """Group squeue `%A|%T` lines by job id. Array tasks share the master id."""
    grouped = {}
    for raw in _decode(stdout).splitlines():
        line = raw.strip()
        if "|" not in line:
            continue
        jid, state = line.split("|", 1)
        jid = jid.strip().split("_", 1)[0]
        state = state.strip()
        if not jid.isdigit() or not state:
            continue
        grouped.setdefault(jid, []).append(state)
    return grouped


def _sacct_job_field(field):
    """True for 42, 42_0, 42.batch, or 42_0.extern. Error text does not match."""
    head = str(field or "").split(".", 1)[0]
    if not head or not head[0].isdigit():
        return False
    job, sep, task = head.partition("_")
    if not job.isdigit():
        return False
    return not sep or task.isdigit()


def parse_sacct_states(stdout):
    states = []
    for raw in _decode(stdout).splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("jobid"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2 and _sacct_job_field(parts[0]):
                states.append(_normalize_state(parts[1]))
            continue
        cols = line.split()
        if len(cols) >= 2 and _sacct_job_field(cols[0]):
            states.append(_normalize_state(cols[1]))
    return [s for s in states if s]


def _duration_seconds(value):
    """Parse Slurm duration values such as D-HH:MM:SS.sss."""
    text = _text(value)
    if not text:
        return 0.0
    days = 0.0
    if "-" in text:
        day_text, text = text.split("-", 1)
        try:
            days = float(day_text)
        except ValueError:
            return 0.0
    try:
        parts = [float(piece) for piece in text.split(":")]
    except ValueError:
        return 0.0
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours, minutes, seconds = 0.0, parts[0], parts[1]
    elif len(parts) == 1:
        hours, minutes, seconds = 0.0, 0.0, parts[0]
    else:
        return 0.0
    return days * 86400.0 + hours * 3600.0 + minutes * 60.0 + seconds


def _memory_bytes(value, default_unit="K"):
    """Convert a Slurm memory value to bytes (`sacct --units=K` by default)."""
    text = _text(value).upper().replace("IB", "").replace("B", "")
    match = re.match(r"^([0-9]+(?:\.[0-9]+)?)([KMGTPE]?)", text)
    if not match:
        return -1
    number = float(match.group(1))
    unit = match.group(2) or default_unit
    powers = {"": 0, "K": 1, "M": 2, "G": 3, "T": 4, "P": 5, "E": 6}
    return int(number * (1024 ** powers[unit]))


def parse_sacct_usage(stdout, job_id):
    """Return conservative per-task CPU and peak-memory usage from sacct rows."""
    groups = {}
    for raw in _decode(stdout).splitlines():
        parts = [piece.strip() for piece in raw.split("|")]
        if len(parts) < 7 or not parts[0]:
            continue
        row_id = parts[0]
        key = row_id.split(".", 1)[0]
        groups.setdefault(key, []).append(
            {
                "id": row_id,
                "elapsed": _duration_seconds(parts[2]),
                "cpu_seconds": _duration_seconds(parts[3]),
                "rss": _memory_bytes(parts[5]),
                "vmem": _memory_bytes(parts[6]),
            }
        )

    jid = str(job_id)
    array_keys = [key for key in groups if key.startswith(jid + "_")]
    keys = array_keys or [key for key in groups if key == jid]
    samples = []
    for key in keys:
        rows = groups[key]
        batch_rows = [row for row in rows if row["id"].endswith(".batch")]
        if batch_rows:
            samples.extend(batch_rows)
        else:
            exact_rows = [row for row in rows if row["id"] == key]
            samples.extend(exact_rows or rows)
    if not samples:
        return None

    cpu_values = [
        row["cpu_seconds"] / row["elapsed"] * 100.0
        for row in samples
        if row["elapsed"] > 0 and row["cpu_seconds"] >= 0
    ]
    rss_values = [row["rss"] for row in samples if row["rss"] >= 0]
    vmem_values = [row["vmem"] for row in samples if row["vmem"] >= 0]
    return {
        # Existing forecasting treats 100 as one fully utilized CPU core.
        "cpu": max(cpu_values) if cpu_values else -1,
        "mem": max(rss_values) if rss_values else -1,
        "vrt_mem": max(vmem_values) if vmem_values else -1,
    }


def load_template():
    path = os.path.join(os.path.split(os.path.realpath(__file__))[0], "Slurm.tpl")
    with open(path, "r") as handle:
        return handle.read()


def render_script(
    protocol,
    job_id,
    job_step,
    cpu=1,
    mem="",
    queue="",
    log_file="",
    wall_time="",
    workspace="",
    extras=None,
):
    extras = _extras(extras)
    body = extras.get("body")
    if body is None or body == "":
        body = protocol
    job_name = "%s-%s" % (job_id, job_step)
    cpu_n = cpu if cpu not in (None, "", 0) else 1
    remote = extras.get("remote") or {}
    gres = gres_line(
        extras.get("gpus"), extras.get("gres"), extras.get("gpu_style") or "gres"
    )
    partition = extras.get("partition") or queue
    array = _text(extras.get("array"))
    array_line = _flag_line("--array", array) if array else ""
    exclude = _flag_line("--exclude", extras.get("exclude"))
    extra = extra_header_lines(extras.get("extra"))
    mem_line = _flag_line("--mem", mem)
    time_line = _flag_line("--time", wall_time)
    partition_line = _flag_line("--partition", partition)
    array_boot = ""
    if remote:
        result_root = (
            _text(remote.get("result_root"))
            or _text(remote.get("workdir"))
        )
        if not result_root:
            user = _text(remote.get("user"))
            result_root = "/home/%s/workdir" % user if user else "/tmp/bioqueue-workdir"
            remote["result_root"] = result_root
        log_root = _text(remote.get("log_root")) or _text(remote.get("scripts_dir"))
        if not log_root:
            log_root = "."
        # Shared path stage_in used. Scripts may read inputs from here.
        # Never a node-local scratch directory: preflight runs on the login node.
        stage_dir = _text(remote.get("chdir")) or _text(remote.get("result_dir"))
        if array:
            # One directory and one log file per array task. Do not pin fetch
            # to a single staged workspace that every task would clobber.
            # $SLURM_JOB_ID is a different integer for each task. The name
            # squeue shows, and the directory protocols publish, is
            # ${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID} (269059_1).
            remote.pop("result_dir", None)
            chdir = ""
            stdout_path = posixpath.join(
                log_root, "%s-%s_%%A_%%a.out" % (job_id, job_step)
            )
            stderr_path = posixpath.join(
                log_root, "%s-%s_%%A_%%a.err" % (job_id, job_step)
            )
            log_glob = posixpath.join(log_root, "%s-%s_*" % (job_id, job_step))
            root = shlex.quote(result_root.rstrip("/"))
            array_boot = (
                'if [ -n "${SLURM_ARRAY_TASK_ID:-}" ]; then\n'
                '  bq_slot="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"\n'
                "else\n"
                '  bq_slot="${SLURM_JOB_ID}"\n'
                "fi\n"
                'export BQ_TASK_DIR=%s/"$bq_slot"\n'
                'mkdir -p "$BQ_TASK_DIR"\n'
                'cd "$BQ_TASK_DIR"\n'
            ) % root
        else:
            chdir = stage_dir or _text(remote.get("workdir"))
            stdout_path = posixpath.join(log_root, "%s-%s.out" % (job_id, job_step))
            stderr_path = posixpath.join(log_root, "%s-%s.err" % (job_id, job_step))
            log_glob = ""
        remote["stdout_path"] = stdout_path
        remote["stderr_path"] = stderr_path
        remote["log_glob"] = log_glob
        extras["remote"] = remote
        # Batch bodies run on a compute node. These point at shared storage
        # the login node and the compute node can both see.
        shared_boot = "export BQ_RESULT_ROOT=%s\n" % shlex.quote(result_root)
        if stage_dir:
            shared_boot += "export BQ_STAGE_DIR=%s\n" % shlex.quote(stage_dir)
    else:
        chdir = workspace
        log_root = workspace or "."
        stdout_path = os.path.join(log_root, "%s-%s.out" % (job_id, job_step))
        stderr_path = os.path.join(log_root, "%s-%s.err" % (job_id, job_step))
        shared_boot = ""
    chdir_line = _flag_line("--chdir", chdir)
    prologue = shared_boot + array_boot + _text(extras.get("prologue"))
    epilogue = _text(extras.get("epilogue"))
    template = load_template()
    return (
        template.replace("{JOBNAME}", job_name)
        .replace("{CPU}", str(cpu_n))
        .replace("{MEM}", mem_line)
        .replace("{WALLTIME}", time_line)
        .replace("{PARTITION}", partition_line)
        .replace("{GRES}", gres)
        .replace("{EXCLUDE}", exclude)
        .replace("{ARRAY}", array_line)
        .replace("{EXTRA}", extra)
        .replace("{CHDIR}", chdir_line)
        .replace("{STDOUT}", stdout_path)
        .replace("{STDERR}", stderr_path)
        .replace("{PROLOGUE}", prologue)
        .replace("{PROTOCOL}", _text(body) if isinstance(body, str) else _decode(body))
        .replace("{EPILOGUE}", epilogue)
    )


def _ssh_control_path(remote):
    """Short private socket shared by every ssh/scp/rsync to this login.

    A fresh TCP login per status poll trips MaxStartups on the submit node.
    The path stays under UNIX socket limits; host, user, and key are hashed.
    """
    ident = "\0".join(
        (
            _text(remote.get("user")),
            _text(remote.get("host")),
            _text(remote.get("key")),
        )
    )
    digest = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:16]
    directory = "/tmp/bq-ssh-%s" % os.getuid()
    try:
        os.makedirs(directory, mode=0o700)
    except OSError:
        pass
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return os.path.join(directory, digest)


def _ssh_options(remote):
    control = _ssh_control_path(remote)
    options = [
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "ControlMaster=auto",
        "-o",
        "ControlPersist=600",
        "-o",
        "ControlPath=%s" % control,
    ]
    key = _text(remote.get("key"))
    if key:
        options.extend(["-i", key])
    return options


def _ssh_base(remote):
    argv = ["ssh"] + _ssh_options(remote)
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    argv.append(dest)
    return argv


def _scp_argv(remote, local_path, remote_path):
    argv = ["scp"] + _ssh_options(remote)
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    argv.extend([local_path, "%s:%s" % (dest, remote_path)])
    return argv


def _rsync_rsh(remote):
    parts = ["ssh"] + _ssh_options(remote)
    return " ".join(shlex.quote(p) for p in parts)


def _remote_spec(remote):
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    return dest


def _drop_stale_mux(argv, output):
    """OpenSSH will not replace a dead ControlMaster socket. Remove ours and retry."""
    if not output or not _MUX_STALE.search(output):
        return
    for part in argv:
        text = str(part)
        if not text.startswith("ControlPath=") or "/bq-ssh-" not in text:
            continue
        path = text.split("=", 1)[1]
        try:
            os.unlink(path)
            logger.warning("removed stale ssh control socket %s", path)
        except OSError:
            pass


def _run(argv, timeout=60, cwd=None, retries=3):
    last_rc, last_out = 1, ""
    attempts = max(1, int(retries))
    for attempt in range(attempts):
        try:
            logger.debug("cluster cmd: %s", " ".join(str(p) for p in argv))
            proc = subprocess.run(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                cwd=cwd,
                check=False,
            )
            last_rc, last_out = proc.returncode, _decode(proc.stdout)
            if last_rc == 0:
                return last_rc, last_out
            if _INVALID_JOB.search(last_out):
                return last_rc, last_out
            _drop_stale_mux(argv, last_out)
        except subprocess.TimeoutExpired as exc:
            last_rc, last_out = 1, "timeout: %s" % exc
            logger.warning("cluster cmd timed out: %s", argv[0] if argv else "")
        except OSError as exc:
            last_rc, last_out = 1, str(exc)
            logger.warning("cluster cmd OSError: %s", exc)
        if attempt + 1 < attempts:
            time.sleep(min(8, 2 ** attempt))
    return last_rc, last_out


def _slurm_cmd(argv, extras, timeout=60, retries=3):
    extras = _extras(extras)
    remote = extras.get("remote")
    if remote:
        remote_cmd = " ".join(shlex.quote(str(p)) for p in argv)
        return _run(_ssh_base(remote) + [remote_cmd], timeout=timeout, retries=retries)
    return _run(list(argv), timeout=timeout, retries=retries)


def _requeue_enabled(extras):
    flag = _text(extras.get("requeue")).lower()
    return flag not in ("0", "false", "no", "off")


def _sbatch_argv(bin_prefix, script_path, extras):
    argv = [_bin(bin_prefix, "sbatch")]
    if _requeue_enabled(extras):
        argv.append("--requeue")
    extra_cli = _text(extras.get("sbatch_cli"))
    if extra_cli:
        argv.extend(shlex.split(extra_cli))
    argv.append(script_path)
    return argv


def _write_script(workspace, job_id, job_step, content):
    if workspace and not os.path.exists(workspace):
        try:
            os.makedirs(workspace)
        except OSError:
            pass
    name = "%s-%s.sbatch" % (job_id, job_step)
    path = os.path.join(workspace or ".", name)
    with open(path, "w") as handle:
        handle.write(content)
    return path


def _bin_prefix(extras):
    extras = _extras(extras)
    remote = extras.get("remote") or {}
    if remote:
        return remote.get("bin_prefix") or extras.get("bin_prefix") or ""
    return extras.get("bin_prefix") or ""


def _normalize_local(path):
    text = _text(path)
    if not text:
        return ""
    return os.path.normpath(text.rstrip("/\\"))


def _path_variants(path):
    """Host path spellings that may appear in a rendered shell body."""
    norm = _normalize_local(path)
    if not norm:
        return []
    variants = []
    raw = _text(path)
    if raw:
        variants.append(raw)
    variants.append(norm)
    variants.append(norm + os.sep)
    seen = set()
    ordered = []
    for item in variants:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _replace_staged_path(extras, local_path, remote_path):
    """Rewrite host paths embedded in a rendered command to cluster paths."""
    body = extras.get("body")
    if not isinstance(body, str) or not local_path:
        return
    updated = body
    for variant in _path_variants(local_path):
        updated = updated.replace(variant, remote_path)
    extras["body"] = updated


def _body_references_local_path(body, local_path):
    if not isinstance(body, str):
        return False
    for variant in _path_variants(local_path):
        if variant in body:
            return True
    return False


def _is_under_path(child, parent):
    child_norm = _normalize_local(child)
    parent_norm = _normalize_local(parent)
    if not child_norm or not parent_norm:
        return False
    if child_norm == parent_norm:
        return True
    prefix = parent_norm + os.sep
    return child_norm.startswith(prefix)


def _local_to_remote_posix(local_path):
    return local_path.replace(os.sep, "/")


def _rsync_to_remote(remote, local_path, remote_path, is_dir=False):
    mkdir_path = remote_path if is_dir else posixpath.dirname(remote_path)
    rc, out = _run(
        _ssh_base(remote) + ["mkdir -p %s" % shlex.quote(mkdir_path)],
        retries=3,
    )
    if rc != 0:
        return rc, out
    source = local_path
    target = remote_path
    if is_dir:
        source = local_path.rstrip(os.sep) + os.sep
        target = remote_path.rstrip("/") + "/"
    argv = ["rsync", "-a", "--compress", "--partial", "-e", _rsync_rsh(remote)]
    argv.extend([source, "%s:%s" % (_remote_spec(remote), target)])
    return _run(argv, timeout=3600, retries=2)


def _stage_workspace(workspace, job_id, extras):
    extras = _extras(extras)
    remote = extras.get("remote") or {}
    if not remote or not workspace:
        return True
    workspace_norm = _normalize_local(workspace)
    if not workspace_norm or not os.path.isdir(workspace_norm):
        logger.error("workspace stage-in skipped; missing locally: %s", workspace)
        return False
    flag = _text(extras.get("stage_in") or remote.get("stage_in")).lower()
    if flag not in ("1", "true", "yes", "on"):
        return True
    scripts_dir = _text(remote.get("scripts_dir")) or "/tmp/bioqueue-scripts"
    workdir = _text(remote.get("workdir"))
    stage_dir = _text(remote.get("chdir")) or posixpath.join(
        workdir or scripts_dir, "jobs", str(job_id)
    )
    remote_workspace = posixpath.join(stage_dir, "workspace")
    rc, out = _rsync_to_remote(remote, workspace_norm, remote_workspace, is_dir=True)
    if rc != 0:
        logger.error("workspace stage-in failed: %s", out)
        return False

    staged_inputs = []
    for input_path in extras.get("stage_inputs") or []:
        local_path = _normalize_local(input_path)
        if local_path:
            staged_inputs.append((input_path, local_path))
    staged_inputs.sort(key=lambda item: len(item[1]), reverse=True)

    for index, (input_path, local_path) in enumerate(staged_inputs):
        if local_path == workspace_norm:
            continue
        if _is_under_path(local_path, workspace_norm):
            rel = os.path.relpath(local_path, workspace_norm)
            if not os.path.exists(local_path):
                logger.info(
                    "stage-in skip missing workspace-relative path (leave as cluster/NFS): %s",
                    local_path,
                )
                continue
            remote_path = posixpath.join(
                remote_workspace, _local_to_remote_posix(rel)
            )
            _replace_staged_path(extras, input_path, remote_path)
            continue
        if not os.path.exists(local_path):
            logger.info(
                "stage-in skip missing local path (leave as cluster/NFS): %s",
                local_path,
            )
            continue
        name = os.path.basename(local_path) or "input"
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        remote_path = posixpath.join(
            stage_dir, "inputs", "%d_%s" % (index + 1, safe_name)
        )
        rc, out = _rsync_to_remote(
            remote, local_path, remote_path, is_dir=os.path.isdir(local_path)
        )
        if rc != 0:
            logger.error("input stage-in failed for %s: %s", local_path, out)
            return False
        _replace_staged_path(extras, input_path, remote_path)

    # Rewrite {{Workspace}} expansions last so we do not corrupt longer input paths
    # that share the same directory prefix.
    _replace_staged_path(extras, workspace, remote_workspace)

    remote["chdir"] = remote_workspace
    remote["result_dir"] = remote_workspace
    extras["remote"] = remote
    return True


def submit_job(
    protocol,
    job_id,
    job_step,
    cpu=0,
    mem="",
    vrt_mem="",
    queue="",
    log_file="",
    wall_time="",
    workspace="",
    extras=None,
):
    extras = _extras(extras)
    if extras.get("remote") and not _stage_workspace(workspace, job_id, extras):
        return 0
    content = render_script(
        protocol,
        job_id,
        job_step,
        cpu=cpu,
        mem=mem,
        queue=queue,
        log_file=log_file,
        wall_time=wall_time,
        workspace=workspace,
        extras=extras,
    )
    local_path = _write_script(workspace, job_id, job_step, content)
    remote = extras.get("remote")
    try:
        if remote:
            scripts_dir = _text(remote.get("scripts_dir")) or "/tmp/bioqueue-scripts"
            remote_path = posixpath.join(scripts_dir, os.path.basename(local_path))
            mkdir_cmd = "mkdir -p %s" % shlex.quote(scripts_dir)
            rc, out = _run(_ssh_base(remote) + [mkdir_cmd])
            if rc != 0:
                logger.error("remote mkdir failed: %s", out)
                return 0
            rc, out = _run(_scp_argv(remote, local_path, remote_path))
            if rc != 0:
                logger.error("scp sbatch failed: %s", out)
                return 0
            sbatch = _sbatch_argv(remote.get("bin_prefix"), remote_path, extras)
            remote_cmd = " ".join(shlex.quote(part) for part in sbatch)
            rc, out = _run(_ssh_base(remote) + [remote_cmd])
        else:
            sbatch = _sbatch_argv(extras.get("bin_prefix") or "", local_path, extras)
            rc, out = _run(sbatch, cwd=workspace or None)
        if rc != 0:
            logger.error("sbatch failed: %s", out)
            return 0
        cluster_id = parse_sbatch_job_id(out)
        if not cluster_id:
            logger.error("sbatch produced no job id: %s", out)
            return 0
        return cluster_id
    except Exception:
        logger.exception("sbatch submit failed")
        return 0


def _sacct_status(job_id, extras):
    prefix = _bin_prefix(extras)
    argv = [
        _bin(prefix, "sacct"),
        "-j",
        str(job_id),
        "-n",
        "-P",
        "-X",
        "-o",
        "JobID,State,ExitCode",
    ]
    rc, out = _slurm_cmd(argv, extras, timeout=60, retries=2)
    states = parse_sacct_states(out)
    if not states:
        if rc != 0 and out.strip():
            logger.info("sacct rc=%s for %s: %s", rc, job_id, out)
        return STATUS_UNKNOWN
    return status_from_states(states, requeue=_requeue_enabled(extras))


def _chunks(items, size):
    items = list(items)
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _squeue_argv(prefix, job_ids=None):
    argv = [_bin(prefix, "squeue"), "-h", "-o", "%A|%T"]
    if job_ids:
        argv = [
            _bin(prefix, "squeue"),
            "-h",
            "-j",
            ",".join(job_ids),
            "-o",
            "%A|%T",
        ]
    return argv


def _unwrap_states(payload):
    """Accept a status dict or (dict, transport-failed ids)."""
    if (
        isinstance(payload, tuple)
        and len(payload) == 2
        and isinstance(payload[0], dict)
    ):
        states, transport = payload
        return states, set(transport or ())
    if isinstance(payload, dict):
        return payload, set()
    return {}, set()


def _query_job_states(job_ids, extras):
    """One squeue for many ids. sacct only for ids that have left the queue.

    Returns (status_by_id, transport_failed_ids). A transport failure is not
    treated as the job leaving the queue.
    """
    ids = []
    seen = set()
    for raw in job_ids:
        jid = str(raw).strip()
        if jid and jid not in seen:
            seen.add(jid)
            ids.append(jid)
    result = {jid: STATUS_UNKNOWN for jid in ids}
    if not ids:
        return result, set()
    extras = _extras(extras)
    prefix = _bin_prefix(extras)
    grouped = {}
    transport_failed = set()

    def consider(chunk):
        if not chunk:
            return
        rc, out = _slurm_cmd(
            _squeue_argv(prefix, chunk), extras, timeout=60, retries=3
        )
        parsed = parse_squeue_states(out)
        if rc == 0:
            grouped.update(parsed)
            return
        if _INVALID_JOB.search(out):
            grouped.update(parsed)
            missing = [jid for jid in chunk if jid not in grouped]
            # One finished id can make `squeue -j` reject the list and print
            # nothing. Split until the dead id is alone, then ask sacct for it.
            # Do not list every job on the cluster: that call can time out and
            # mark the healthy ids unknown.
            if len(missing) > 1 and not parsed:
                mid = len(missing) // 2
                consider(missing[:mid])
                consider(missing[mid:])
            return
        logger.warning("squeue rc=%s for %s: %s", rc, ",".join(chunk), out)
        transport_failed.update(chunk)

    try:
        for chunk in _chunks(ids, _SQUEUE_CHUNK):
            consider(chunk)
    except Exception:
        logger.exception("squeue failed for %s", ",".join(ids))
        return result, set(ids)
    requeue = _requeue_enabled(extras)
    for jid in ids:
        states = grouped.get(jid)
        if states:
            result[jid] = status_from_states(states, requeue=requeue)
        elif jid in transport_failed:
            result[jid] = STATUS_UNKNOWN
        else:
            logger.info("squeue lost job %s, asking sacct", jid)
            result[jid] = _sacct_status(jid, extras)
    return result, transport_failed


def _poll_after(status_code):
    if status_code == 2:
        return POLL_PENDING_SECONDS
    return POLL_RUNNING_SECONDS


def _board_extras(extras):
    extras = _extras(extras)
    remote = extras.get("remote") if isinstance(extras.get("remote"), dict) else {}
    snapshot = {}
    if remote.get("host"):
        snapshot["remote"] = {
            "host": remote.get("host"),
            "user": remote.get("user"),
            "key": remote.get("key"),
            "bin_prefix": remote.get("bin_prefix"),
        }
    prefix = _text(remote.get("bin_prefix")) or _text(extras.get("bin_prefix"))
    if prefix:
        snapshot["bin_prefix"] = prefix
    return snapshot


def _board_key(extras):
    snapshot = _board_extras(extras)
    remote = snapshot.get("remote") or {}
    return (
        _text(remote.get("host")),
        _text(remote.get("user")),
        _text(remote.get("key")),
        _text(snapshot.get("bin_prefix")),
    )


class _BoardClosed(Exception):
    pass


class _StatusBoard(object):
    """One poller per login node. Threads wait here instead of calling squeue."""

    def __init__(self, key, extras):
        self.key = key
        self.extras = extras
        self.cv = threading.Condition()
        self.members = {}
        self._stopped = False
        self._thread = None

    def start(self):
        self._thread = threading.Thread(
            target=self._loop, name="slurm-status", daemon=True
        )
        self._thread.start()

    def stop(self):
        with self.cv:
            self._stopped = True
            self.members.clear()
            self.cv.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1)

    def release(self, job_id):
        with self.cv:
            self.members.pop(str(job_id).strip(), None)
            self.cv.notify_all()

    def wait_status(self, job_id):
        jid = str(job_id).strip()
        with self.cv:
            if self._stopped:
                raise _BoardClosed()
            slot = self.members.get(jid)
            if slot is None:
                slot = {
                    "status": STATUS_UNKNOWN,
                    "seq": 0,
                    "next_due": time.time(),
                }
                self.members[jid] = slot
            seen = slot["seq"]
            self.cv.notify_all()
            deadline = time.time() + _POLL_WAIT_SECONDS
            while slot["seq"] == seen:
                if self._stopped:
                    raise _BoardClosed()
                remaining = deadline - time.time()
                if remaining <= 0:
                    logger.warning("status wait timed out for %s", jid)
                    return STATUS_UNKNOWN
                self.cv.wait(timeout=remaining)
            return slot["status"]

    def _loop(self):
        while True:
            try:
                if not self._poll_once():
                    return
            except Exception:
                logger.exception("slurm status poller failed")
                time.sleep(1)
                if self._stopped:
                    return

    def _poll_once(self):
        with self.cv:
            while not self.members and not self._stopped:
                self.cv.wait()
            if self._stopped:
                return False
            now = time.time()
            soonest = min(slot["next_due"] for slot in self.members.values())
            if soonest > now:
                self.cv.wait(timeout=soonest - now)
                return True
        time.sleep(_POLL_COALESCE_SECONDS)
        with self.cv:
            if self._stopped:
                return False
            now = time.time()
            ids = [
                jid
                for jid, slot in self.members.items()
                if slot["next_due"] <= now
            ]
        if not ids:
            return True
        ids.sort(key=lambda jid: int(jid) if jid.isdigit() else jid)
        try:
            payload = _query_job_states(ids, self.extras)
        except Exception:
            logger.exception("squeue batch failed")
            payload = ({}, set(ids))
        statuses, transport = _unwrap_states(payload)
        now = time.time()
        with self.cv:
            for jid in ids:
                slot = self.members.get(jid)
                if slot is None:
                    continue
                status = statuses.get(jid, STATUS_UNKNOWN)
                # One login-node blip must not advance the vanish streak for
                # every job. Keep the last real state and try again shortly.
                if jid in transport and slot["seq"] > 0:
                    status = slot["status"]
                    slot["next_due"] = now + POLL_RUNNING_SECONDS
                else:
                    slot["next_due"] = now + _poll_after(status)
                slot["status"] = status
                slot["seq"] += 1
                if status in (0, -1):
                    self.members.pop(jid, None)
            self.cv.notify_all()
        return True


_status_boards = {}
_status_boards_lock = threading.Lock()


def _board_for(extras):
    key = _board_key(extras)
    with _status_boards_lock:
        board = _status_boards.get(key)
        if board is None or board._stopped:
            board = _StatusBoard(key, _board_extras(extras))
            _status_boards[key] = board
            board.start()
        return board


def _reset_status_boards_for_tests():
    with _status_boards_lock:
        boards = list(_status_boards.values())
        _status_boards.clear()
    for board in boards:
        board.stop()


def _status_due_in(job_id, extras=None):
    with _status_boards_lock:
        board = _status_boards.get(_board_key(extras))
    if board is None:
        return None
    with board.cv:
        slot = board.members.get(str(job_id).strip())
        if not slot:
            return None
        return slot["next_due"] - time.time()


def query_job_status(job_id, extras=None):
    """Block until the shared poller publishes a new state for this id."""
    snapshot = _board_extras(extras)
    for _attempt in range(2):
        board = _board_for(snapshot)
        try:
            return board.wait_status(job_id)
        except _BoardClosed:
            continue
    return STATUS_UNKNOWN


def release_job_status(job_id, extras=None):
    """Drop a finished id so later polls do not keep asking about it."""
    with _status_boards_lock:
        board = _status_boards.get(_board_key(extras))
    if board is not None:
        board.release(job_id)


def query_job_usage(job_id, extras=None):
    """Collect completed-job telemetry from Slurm accounting."""
    extras = _extras(extras)
    prefix = _bin_prefix(extras)
    argv = [
        _bin(prefix, "sacct"),
        "-j",
        str(job_id),
        "-n",
        "-P",
        "--units=K",
        "-o",
        "JobIDRaw,State,ElapsedRaw,TotalCPU,AllocCPUS,MaxRSS,MaxVMSize",
    ]
    last_rc, last_out = 1, ""
    for attempt in range(4):
        last_rc, last_out = _slurm_cmd(argv, extras, timeout=60, retries=3)
        if last_rc == 0:
            usage = parse_sacct_usage(last_out, job_id)
            if usage is not None:
                return usage
        # Accounting records may trail the terminal state by a few seconds.
        if attempt < 3:
            time.sleep(2 ** (attempt + 1))
    if last_rc != 0:
        logger.warning(
            "sacct telemetry rc=%s for %s: %s", last_rc, job_id, last_out
        )
    else:
        logger.warning("sacct returned no telemetry for cluster job %s", job_id)
    return None


def cancel_job(job_id, extras=None):
    extras = _extras(extras)
    argv = [_bin(_bin_prefix(extras), "scancel"), str(job_id)]
    try:
        _slurm_cmd(argv, extras, timeout=60, retries=2)
        return 1
    except Exception:
        logger.exception("scancel failed for %s", job_id)
        return 0


def _safe_job_id(job_id):
    text = str(job_id).strip()
    return "".join(ch for ch in text if ch.isalnum() or ch in "._-")


def _parse_ls_dirs(stdout, result_root, job_id):
    root = result_root.rstrip("/")
    jid = _safe_job_id(job_id)
    prefix = root + "/" + jid
    found = []
    for raw in _decode(stdout).splitlines():
        path = raw.strip().rstrip("/")
        if not path:
            continue
        base = posixpath.basename(path)
        if base == jid or base.startswith(jid + "_"):
            found.append(path + "/")
    if not found:
        found.append(prefix + "/")
    return found


def _list_remote_result_dirs(remote, result_root, job_id):
    """Expand <id> and <id>_* in the remote shell. rsync will not do that over SSH.

    A ``find`` of the whole workdir has timed out on a busy home directory and
    then the only fallback was ``<id>/``, which is not where array tasks publish.
    """
    root = result_root.rstrip("/")
    jid = _safe_job_id(job_id)
    quoted = shlex.quote(root)
    inner = (
        "shopt -s nullglob; "
        "for d in %s/%s %s/%s_*; do printf '%%s\\n' \"$d\"; done"
    ) % (quoted, jid, quoted, jid)
    rc, out = _run(_ssh_base(remote) + ["bash", "-lc", inner], timeout=60, retries=2)
    return _parse_ls_dirs(out if rc == 0 else "", result_root, job_id), rc, out


def _array_task_dir(remote_dir, job_id):
    """True when the remote directory is ``<sbatch id>_<task>``."""
    base = posixpath.basename(_text(remote_dir).rstrip("/"))
    jid = _safe_job_id(job_id)
    return bool(jid) and base.startswith(jid + "_")


def _missing_remote(output):
    text = output or ""
    return "No such file" in text or "not found" in text.lower()


def _submission_log_remote(remote, cluster_id):
    """Limit an array log glob to the Slurm id of this submission.

    The glob is ``{job}-{step}_*``. Earlier reruns leave ``{job}-{step}_{oldId}_*``
    in the same directory, and fetching those would mix runs.
    """
    remote = dict(remote or {})
    glob = _text(remote.get("log_glob"))
    cluster_id = _safe_job_id(cluster_id)
    if glob.endswith("*") and cluster_id:
        remote["log_glob"] = "%s%s_*" % (glob[:-1], cluster_id)
    return remote


def _list_remote_log_files(remote, extras, include_legacy=True):
    """Resolve remote Slurm stdout/stderr paths, including array expansions."""
    stdout_path = _text(remote.get("stdout_path"))
    stderr_path = _text(remote.get("stderr_path"))
    log_glob = _text(remote.get("log_glob"))
    paths = []
    searches = []
    if log_glob:
        root = posixpath.dirname(log_glob) or "."
        prefix = posixpath.basename(log_glob)
        searches.append((root, prefix + "*.out"))
        searches.append((root, prefix + "*.err"))
    for path in (stdout_path, stderr_path):
        if not path or "%" in path:
            continue
        searches.append((posixpath.dirname(path) or ".", posixpath.basename(path)))
    user = _text(remote.get("user"))
    bq_id = _safe_job_id(extras.get("bq_job_id"))
    if include_legacy and user and bq_id:
        legacy_root = "/home/%s/slurm_outputs" % user
        searches.append((legacy_root, "%s.out" % bq_id))
        searches.append((legacy_root, "%s.err" % bq_id))
    for log_root, name in searches:
        inner = "find %s -maxdepth 1 -type f -name %s -print" % (
            shlex.quote(log_root),
            shlex.quote(name),
        )
        rc, out = _run(_ssh_base(remote) + ["bash", "-lc", inner], timeout=60, retries=2)
        if rc == 0:
            paths.extend(
                line.strip() for line in _decode(out).splitlines() if line.strip()
            )
    seen = set()
    ordered = []
    for path in sorted(paths):
        if path not in seen:
            seen.add(path)
            ordered.append(path)
    return ordered


def _append_remote_file(remote, remote_path, local_path):
    """Download one remote file and append it to a local log."""
    if not remote_path or not local_path:
        return False
    parent = os.path.dirname(local_path)
    if parent:
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            pass
    tmp_path = local_path + ".bq_pull"
    argv = ["scp"] + _ssh_options(remote)
    argv.extend(["%s:%s" % (_remote_spec(remote), remote_path), tmp_path])
    rc, out = _run(argv, timeout=600, retries=2)
    if rc != 0:
        if "No such file" in out or "not found" in out.lower():
            return None
        logger.warning("scp log failed (%s): %s", remote_path, out)
        return False
    try:
        with open(tmp_path, "rb") as src, open(local_path, "ab") as dest:
            dest.write(
                ("\n===== %s =====\n" % remote_path).encode("utf-8", "replace")
            )
            dest.write(src.read())
        return True
    except OSError as exc:
        logger.warning("cannot write local log %s: %s", local_path, exc)
        return False
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _copy_listed_logs(remote, listed, known, log_dest, err_dest):
    synced = False
    for remote_path in listed:
        if remote_path in known:
            continue
        known.add(remote_path)
        if _copy_log(remote, remote_path, log_dest, err_dest) is True:
            synced = True
    return synced


def fetch_logs(job_id, extras=None):
    """Pull Slurm stdout/stderr into the worker's local job log files."""
    extras = _extras(extras)
    remote = extras.get("remote") or {}
    if not remote:
        return True
    log_dest = _text(extras.get("fetch_log"))
    err_dest = _text(extras.get("fetch_err"))
    if not log_dest and not err_dest:
        return True
    # The batch script already names these files. Copy them directly. A timed-out
    # `find` used to drop the logs even though the path was known.
    concrete = []
    for path in (_text(remote.get("stdout_path")), _text(remote.get("stderr_path"))):
        if path and "%" not in path:
            concrete.append(path)
    synced = False
    absent = []
    transport_failed = False
    for remote_path in concrete:
        copied = _copy_log(remote, remote_path, log_dest, err_dest)
        if copied is True:
            synced = True
        elif copied is None:
            absent.append(remote_path)
        else:
            transport_failed = True
    if transport_failed:
        if not synced:
            logger.warning("failed to fetch Slurm logs for cluster job %s", job_id)
        return synced
    listing_remote = _submission_log_remote(remote, job_id)
    if not (synced and not listing_remote.get("log_glob")):
        known = set(concrete)
        listed = _list_remote_log_files(listing_remote, extras, include_legacy=False)
        if _copy_listed_logs(listing_remote, listed, known, log_dest, err_dest):
            synced = True
        if not synced:
            legacy = _list_remote_log_files(listing_remote, extras, include_legacy=True)
            if _copy_listed_logs(listing_remote, legacy, known, log_dest, err_dest):
                synced = True
    if not synced:
        logger.warning(
            "remote job %s has no Slurm log files to fetch%s",
            job_id,
            (": " + ", ".join(absent)) if absent else "",
        )
    return synced


def _copy_log(remote, remote_path, log_dest, err_dest):
    lower = remote_path.lower()
    if lower.endswith(".err") and err_dest:
        dest = err_dest
    elif log_dest:
        dest = log_dest
    elif err_dest:
        dest = err_dest
    else:
        return None
    return _append_remote_file(remote, remote_path, dest)


def fetch_results(job_id, extras=None):
    extras = _extras(extras)
    remote = extras.get("remote") or {}
    dest = _text(extras.get("fetch_dest"))
    if not remote:
        return True
    # Always try logs first so failures still leave diagnostics on the worker.
    fetch_logs(job_id, extras)
    result_dir = _text(remote.get("result_dir"))
    result_root = _text(remote.get("result_root")) or _text(remote.get("workdir"))
    if not result_root:
        user = _text(remote.get("user"))
        result_root = "/home/%s/workdir" % user if user else "/tmp/bioqueue-workdir"
        logger.info("remote job %s: defaulting result_root to %s", job_id, result_root)
    if not dest:
        logger.error("remote job %s has no fetch_dest; cannot fetch", job_id)
        return False
    dest_dir = dest if dest.endswith(os.sep) else dest + os.sep
    try:
        os.makedirs(dest, exist_ok=True)
    except OSError:
        pass
    spec = _remote_spec(remote)
    remote_dirs = []
    ls_out = ""
    if result_dir:
        remote_dirs.append(result_dir.rstrip("/") + "/")
    listed, _ls_rc, ls_out = _list_remote_result_dirs(remote, result_root, job_id)
    for path in listed:
        if path not in remote_dirs:
            remote_dirs.append(path)
    synced = False
    failed = False
    last_out = ls_out
    for remote_dir in remote_dirs:
        # Array tasks share one sbatch id and publish side by side
        # (269059_0, 269059_1, ...). Unpacking every task into the job
        # folder overwrites the previous task. Keep each task directory.
        target = dest_dir
        if _array_task_dir(remote_dir, job_id):
            target = os.path.join(
                dest_dir, posixpath.basename(remote_dir.rstrip("/"))
            )
            target = target if target.endswith(os.sep) else target + os.sep
            try:
                os.makedirs(target, exist_ok=True)
            except OSError:
                pass
        argv = ["rsync", "-a", "--compress", "--partial", "-e", _rsync_rsh(remote)]
        argv.extend(["%s:%s" % (spec, remote_dir), target])
        rc, out = _run(argv, timeout=3600, retries=2)
        last_out = out
        if rc == 0:
            synced = True
            continue
        if _missing_remote(out):
            logger.info("remote result dir absent: %s", remote_dir)
            continue
        logger.warning("rsync results failed (%s): %s", remote_dir, out)
        failed = True
    if failed:
        return False
    if synced:
        return True
    stage_on = _text(extras.get("stage_in") or remote.get("stage_in")).lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    missing_only = (
        "No such file" in (last_out or "")
        or "not found" in (last_out or "").lower()
        or not (last_out or ls_out)
    )
    if not stage_on and missing_only and dest and os.path.isdir(dest):
        logger.info(
            "no remote result dir for job %s; using in-place workspace %s",
            job_id,
            dest,
        )
        return True
    logger.error(
        "rsync found no results for job %s under %s: %s",
        job_id,
        result_root if not result_dir else result_dir,
        last_out or ls_out,
    )
    return False
