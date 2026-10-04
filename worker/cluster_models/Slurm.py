"""Slurm backend: render a self-contained sbatch script, submit locally or over SSH."""
from __future__ import print_function

import logging
import os
import posixpath
import re
import shlex
import subprocess
import time

logger = logging.getLogger("BioQueue.cluster.slurm")

# 0 success, 1 running, 2 pending, 3 unknown/retryable, -1 failed
STATUS_UNKNOWN = 3

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
_JOB_STATE = re.compile(r"JobState=([A-Za-z_]+)")
_INVALID_JOB = re.compile(
    r"Invalid job id|invalid job id specified|unable to look up job",
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
    return text.rstrip("*")


def status_from_states(states):
    states = [_normalize_state(s) for s in (states or []) if s]
    states = [s for s in states if s]
    if not states:
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


def parse_sacct_states(stdout):
    states = []
    for raw in _decode(stdout).splitlines():
        line = raw.strip()
        if not line or line.lower().startswith("jobid"):
            continue
        if "|" in line:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 2:
                states.append(_normalize_state(parts[1]))
            continue
        cols = line.split()
        if len(cols) >= 2:
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
        if array:
            # One directory and one log file per array task. Do not pin fetch
            # to a single staged workspace that every task would clobber.
            remote.pop("result_dir", None)
            chdir = ""
            stdout_path = posixpath.join(
                log_root, "%s-%s_%%A_%%a.out" % (job_id, job_step)
            )
            stderr_path = posixpath.join(
                log_root, "%s-%s_%%A_%%a.err" % (job_id, job_step)
            )
            log_glob = posixpath.join(log_root, "%s-%s_*" % (job_id, job_step))
            root = result_root.rstrip("/")
            array_boot = 'mkdir -p %s/"$SLURM_JOB_ID"\ncd %s/"$SLURM_JOB_ID"\n' % (
                root,
                root,
            )
        else:
            chdir = _text(remote.get("chdir")) or _text(remote.get("workdir"))
            stdout_path = posixpath.join(log_root, "%s-%s.out" % (job_id, job_step))
            stderr_path = posixpath.join(log_root, "%s-%s.err" % (job_id, job_step))
            log_glob = ""
        remote["stdout_path"] = stdout_path
        remote["stderr_path"] = stderr_path
        remote["log_glob"] = log_glob
        extras["remote"] = remote
    else:
        chdir = workspace
        log_root = workspace or "."
        stdout_path = os.path.join(log_root, "%s-%s.out" % (job_id, job_step))
        stderr_path = os.path.join(log_root, "%s-%s.err" % (job_id, job_step))
    chdir_line = _flag_line("--chdir", chdir)
    prologue = array_boot + _text(extras.get("prologue"))
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


def _ssh_base(remote):
    argv = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    key = _text(remote.get("key"))
    if key:
        argv.extend(["-i", key])
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    argv.append(dest)
    return argv


def _scp_argv(remote, local_path, remote_path):
    argv = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    key = _text(remote.get("key"))
    if key:
        argv.extend(["-i", key])
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    argv.extend([local_path, "%s:%s" % (dest, remote_path)])
    return argv


def _rsync_rsh(remote):
    parts = ["ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    key = _text(remote.get("key"))
    if key:
        parts.extend(["-i", key])
    return " ".join(shlex.quote(p) for p in parts)


def _remote_spec(remote):
    dest = _text(remote.get("host"))
    user = _text(remote.get("user"))
    if user:
        dest = "%s@%s" % (user, dest)
    return dest


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
    if rc != 0 and not out.strip():
        return STATUS_UNKNOWN
    states = parse_sacct_states(out)
    if not states:
        return STATUS_UNKNOWN
    return status_from_states(states)


def query_job_status(job_id, extras=None):
    extras = _extras(extras)
    prefix = _bin_prefix(extras)
    argv = [_bin(prefix, "scontrol"), "show", "job", str(job_id)]
    try:
        rc, out = _slurm_cmd(argv, extras, timeout=60, retries=3)
    except Exception:
        logger.exception("scontrol failed for %s", job_id)
        return STATUS_UNKNOWN
    if rc != 0 and _INVALID_JOB.search(out):
        logger.info("scontrol lost job %s, asking sacct", job_id)
        return _sacct_status(job_id, extras)
    if rc != 0:
        logger.warning("scontrol rc=%s for %s: %s", rc, job_id, out)
        return STATUS_UNKNOWN
    states = _JOB_STATE.findall(out)
    if not states:
        return STATUS_UNKNOWN
    return status_from_states(states)


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
    """Ask the remote shell to expand array dirs. rsync does not expand globs over SSH."""
    root = result_root.rstrip("/")
    jid = _safe_job_id(job_id)
    inner = "find %s -mindepth 1 -maxdepth 1 \\( -name %s -o -name %s \\) -print" % (
        shlex.quote(root),
        shlex.quote(jid),
        shlex.quote(jid + "_*"),
    )
    rc, out = _run(_ssh_base(remote) + ["bash", "-lc", inner], timeout=60, retries=2)
    return _parse_ls_dirs(out if rc == 0 else "", result_root, job_id), rc, out


def _list_remote_log_files(remote, extras):
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
    if user and bq_id:
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
    argv = ["scp", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    key = _text(remote.get("key"))
    if key:
        argv.extend(["-i", key])
    argv.extend(["%s:%s" % (_remote_spec(remote), remote_path), tmp_path])
    rc, out = _run(argv, timeout=600, retries=2)
    if rc != 0:
        if "No such file" in out or "not found" in out.lower():
            return False
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
    remote_files = _list_remote_log_files(remote, extras)
    if not remote_files:
        logger.warning("remote job %s has no Slurm log files to fetch", job_id)
        return False
    synced = False
    for remote_path in remote_files:
        lower = remote_path.lower()
        if lower.endswith(".err") and err_dest:
            dest = err_dest
        elif log_dest:
            dest = log_dest
        elif err_dest:
            dest = err_dest
        else:
            continue
        if _append_remote_file(remote, remote_path, dest):
            synced = True
    if not synced:
        logger.warning("failed to fetch Slurm logs for cluster job %s", job_id)
    return synced


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
    last_out = ls_out
    for remote_dir in remote_dirs:
        argv = ["rsync", "-a", "--compress", "--partial", "-e", _rsync_rsh(remote)]
        argv.extend(["%s:%s" % (spec, remote_dir), dest_dir])
        rc, out = _run(argv, timeout=3600, retries=2)
        last_out = out
        if rc == 0:
            synced = True
        elif "No such file" not in out and "not found" not in out.lower():
            logger.warning("rsync results failed (%s): %s", remote_dir, out)
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
