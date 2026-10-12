"""CPU prior from a step command when nothing has been learned yet.

Scheduler CPU is in units of 100 = 1 core. This module reads thread and
process counts out of the command the worker will run and returns that
many cores times 100. It does not look at training rows. Callers must
ignore the result when a learned estimate or an explicit ``Step.cpu_prior``
already exists.

Ambiguous short flags are not accepted globally:

- ``-c`` is a count, a config file, or coverage (``samtools view -c``,
  Nextflow ``-c``), not a thread count.
- ``-n`` is a name, a read count, or a line count (``head -n``).
- ``-w`` is a width or a window. fastp is the exception: ``-w`` is its
  worker-thread flag, and only when that executable is on the command.
- ``-p`` is a p-value (``macs2 callpeak -p``), a prefix, or a path.
  It counts as threads only for aligners that document ``-p`` that way
  (bowtie, bowtie2, HISAT2, salmon, StringTie, TopHat, Cufflinks,
  DIAMOND, RSEM).
- ``-t`` is a type, a target, or a threshold on many CLIs. It counts
  only for tools that document it as threads (BWA, BWA-MEM2, minimap2,
  kallisto, SPAdes, MEGAHIT, Flye).

``-j`` / ``-jN`` is make, GNU parallel, and cutadapt only. A global ``-j``
would treat ``squeue -j 123456`` as a thread count. ``-jar`` does not
match. ``-@`` / ``-@N`` is htslib's thread flag (samtools, bcftools,
bgzip, tabix) and is global. Long options take a separate token or ``=N``.
A number is glued to the flag only for those short forms.

``{{ThreadN}}`` is BioQueue's own token, matched exactly. The worker
replaces that spelling with ``cluster.cpu`` when a cluster type is set,
otherwise ``env.cpu``. A bare ``{{ThreadN}}`` anywhere in the command
reserves that many cores. ``{{ThreadN||8}}`` follows the job-parameter
map: the default is what runs when ThreadN is not a job parameter.
``{{threadn}}`` and ``{{ ThreadN }}`` are left alone, because the worker
does not replace them. A job parameter counts only when the command
contains its ``{{key}}`` placeholder.
"""
import os
import re

CPU_UNIT = 100

# Long options, one or two leading dashes, compared case-insensitively.
# STAR's flag is ``--runThreadN``. BLAST's is ``-num_threads``.
_LONG_NAMES = frozenset(
    {
        "threads",
        "thread",
        "thread-count",
        "thread_count",
        "nthreads",
        "num-threads",
        "num_threads",
        "numthreads",
        "workers",
        "worker",
        "nworkers",
        "max-workers",
        "max_workers",
        "processes",
        "process",
        "nprocesses",
        "cpus",
        "cpu",
        "ncpus",
        "num-cpus",
        "num_cpus",
        "num_cpu",
        "cores",
        "ncores",
        "num-cores",
        "num_cores",
        "jobs",
        "njobs",
        "runthreadn",
        "num-cpu-threads",
        "num_cpu_threads",
        "localcores",
        "local-cores",
        "local_cores",
        "multicore",
        "max-threads",
        "max_threads",
        "parallel",
    }
)

_ENV_NAMES = (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "RAYON_NUM_THREADS",
    "GOTO_NUM_THREADS",
    "BLIS_NUM_THREADS",
)

# Job-parameter keys that are themselves a core count (``threads=8``).
_CPU_PARAM_KEYS = _LONG_NAMES | {name.lower() for name in _ENV_NAMES} | {"threadn", "nproc"}

# Short flag -> executable basenames where that letter means a thread count.
# A basename prefix ``tool-`` / ``tool_`` matches too (``bowtie2-build``).
_TOOL_SHORT = {
    "bwa": "t",
    "bwa-mem2": "t",
    "minimap2": "t",
    "kallisto": "t",
    "spades": "t",
    "spades.py": "t",
    "megahit": "t",
    "flye": "t",
    "bowtie": "p",
    "bowtie2": "p",
    "hisat2": "p",
    "salmon": "p",
    "stringtie": "p",
    "tophat": "p",
    "cufflinks": "p",
    "diamond": "p",
    "rsem": "p",
    "fastp": "w",
    "featurecounts": "T",
    "iqtree": "T",
    "iqtree2": "T",
    "make": "j",
    "gmake": "j",
    "parallel": "j",
    "cutadapt": "j",
}

# ``-@`` is htslib. ``-j`` is tool-specific (make, GNU parallel, cutadapt).
_GLOBAL_SHORT = frozenset({"@"})

_VALUE = (
    r"(?:\"[^\"]*\"|'[^']*'|\{\{[^{}]*\}\}|\$\([^)\n]*\)|`[^`\n]*`|[^\s\"';|&<>]+)"
)
_BOUNDARY = r"$|[\s\"';|&<>]"

_LONG_FLAG = re.compile(
    r"(?:^|(?<=[\s\"';|&<>]))"
    r"-{1,2}(?P<name>[A-Za-z][\w-]*)"
    r"(?:=(?P<eq>" + _VALUE + r")|[ \t]+(?P<sep>" + _VALUE + r"))",
    re.IGNORECASE | re.MULTILINE,
)

_ENV_ASSIGN = re.compile(
    r"(?:^|(?<=[\s\"';|&<>]))"
    r"(?:export[ \t]+)?"
    r"(?P<name>" + "|".join(_ENV_NAMES) + r")"
    r"=(?P<value>" + _VALUE + r")",
    re.IGNORECASE | re.MULTILINE,
)

# Glued counts (``-j8``, ``-@8``) must end at a token boundary so ``-jar``
# and ``-j8abc`` do not match. The other form is ``-j 8`` or ``-j=8``.
_SHORT_FLAG = re.compile(
    r"(?:^|(?<=[\s\"';|&<>]))"
    r"-(?P<flag>[@jtpwT])"
    r"(?:"
    r"(?P<glued>[0-9]+|\{\{[^{}]*\}\}|\$\([^)\n]*\)|`[^`\n]*`)"
    r"(?=" + _BOUNDARY + r")"
    r"|(?:[ \t]*=[ \t]*|[ \t]+)(?P<sep>" + _VALUE + r")"
    r")",
    re.MULTILINE,
)

_PLACEHOLDER = re.compile(r"\{\{([^{}]+)\}\}")
# ``||`` before a single ``|`` so a pipeline splits and a shell OR still splits.
# Placeholders are masked first, so ``{{key||default}}`` is not a separator.
_SEGMENT = re.compile(r"&&|\|\||\||;|\n")
_PLACEHOLDER_SLOT = re.compile(r"\0(\d+)\0")


def configured_cpu_budget_units(settings):
    """Smallest configured machine or cluster CPU budget, in CPU-units.

    ``env.cpu`` is the configured machine size in cores. When a cluster
    type is set, ``cluster.cpu`` is the allocation cap. A prior above
    either one cannot start: the scheduler treats ``required > budget``
    as permanently blocked. Returns None when neither value is set.
    """
    settings = settings or {}
    env = settings.get("env") or {}
    cluster = settings.get("cluster") or {}
    limits = []
    env_cores = _positive_cores(env.get("cpu"))
    if env_cores is not None:
        limits.append(env_cores * CPU_UNIT)
    if str(cluster.get("type") or "").strip():
        cluster_cores = _positive_cores(cluster.get("cpu"))
        if cluster_cores is not None:
            limits.append(cluster_cores * CPU_UNIT)
    if not limits:
        return None
    return int(min(limits))


def user_cpu_prior_units(cpu_prior, budget_units=None):
    """Stored ``Step.cpu_prior`` in CPU-units, or None when it is unset.

    The column default is -1. Zero and negative values mean the user did
    not set a prior. A positive value is already in scheduler units
    (100 = 1 core), the same unit learned estimates use. Values above
    ``budget_units`` are capped to that budget so they cannot wedge the
    queue; they are not replaced by a command parse.
    """
    try:
        value = int(cpu_prior)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return _cap_units(value, budget_units)


def estimate_cpu_units(text, parameters=None, software="", budget_units=None):
    """Return CPU-units implied by ``text``, or None if no count is named.

    ``text`` is a command string or a list of them (unsubstituted parameter,
    translated command, shell body). ``parameters`` is the job parameter
    dict from ``Task.build_special_parameter_dict`` (``threads=8``).
    Several counts become the max. Zero, negatives, paths, and unresolved
    placeholders are ignored. ``budget_units`` caps the result and is also
    what ``nproc`` and ``{{ThreadN}}`` expand to.
    """
    if isinstance(text, (list, tuple)):
        parts = [part for part in text if part]
    else:
        parts = [text] if text else []
    parts = [_join_continuations(str(part)) for part in parts]
    counts = []
    for part in parts:
        counts.extend(_counts_in_text(part, parameters, software, budget_units))
    counts.extend(_parameter_key_counts(parameters, budget_units, parts))
    positive = [count for count in counts if count is not None and count > 0]
    if not positive:
        return None
    units = int(round(max(positive) * CPU_UNIT))
    return _cap_units(units, budget_units)


def _positive_cores(value):
    try:
        cores = float(value)
    except (TypeError, ValueError):
        return None
    if cores <= 0:
        return None
    return cores


def _budget_cores(budget_units):
    try:
        units = float(budget_units)
    except (TypeError, ValueError):
        return None
    if units <= 0:
        return None
    return units / float(CPU_UNIT)


def _cap_units(units, budget_units):
    try:
        budget = int(budget_units)
    except (TypeError, ValueError):
        return int(units)
    if budget <= 0 or units <= budget:
        return int(units)
    return budget


def _positive_int(token):
    if isinstance(token, bool) or token is None:
        return None
    if isinstance(token, int):
        return token if token > 0 else None
    if isinstance(token, float):
        if token > 0 and token.is_integer():
            return int(token)
        return None
    text = str(token).strip().strip("'\"")
    text = text.rstrip(",;")
    if not re.fullmatch(r"[1-9]\d*", text or ""):
        return None
    return int(text)


def _is_nproc(token):
    text = str(token).strip().strip("'\"")
    compact = re.sub(r"\s+", "", text).lower()
    if compact.startswith("`") and compact.endswith("`"):
        compact = compact[1:-1]
    compact = compact.replace("$(", "").replace(")", "")
    return compact in {"nproc", "nproc--all"}


def _cores_from_token(token, parameters, budget_units, allow_placeholder=True):
    if token is None:
        return None
    if isinstance(token, bool):
        return None
    if isinstance(token, (int, float)):
        return _positive_int(token)
    text = str(token).strip().strip("'\"")
    text = text.rstrip(",;")
    if not text:
        return None
    if _is_nproc(text):
        return _budget_cores(budget_units)
    if allow_placeholder and text.startswith("{{") and text.endswith("}}"):
        return _cores_from_placeholder(text[2:-2], parameters, budget_units)
    return _positive_int(text)


def _cores_from_placeholder(body, parameters, budget_units):
    """Resolve ``key`` or ``key||default`` the same way step substitution does.

    A non-empty job parameter wins, including when that value is not a
    count (a path must not fall through to the default). ``{{ThreadN}}``
    with no override is the configured core budget.
    """
    key, separator, default = body.partition("||")
    default = default.strip()
    params = parameters or {}
    override = None
    if key in params:
        override = params[key]
    elif body in params:
        override = params[body]
    if override is not None and str(override).strip() != "":
        return _cores_from_token(override, params, budget_units, allow_placeholder=False)
    # The worker looks up the placeholder key exactly and only replaces
    # the exact substring {{ThreadN}}. Spaced or lower-case spellings stay
    # in the command, so they are not a core count.
    if key == "ThreadN":
        if separator:
            parsed = _cores_from_token(default, params, budget_units, allow_placeholder=False)
            if parsed is not None:
                return parsed
        return _budget_cores(budget_units)
    if separator:
        return _cores_from_token(default, params, budget_units, allow_placeholder=False)
    return None


def _join_continuations(text):
    """Shell backslash-newline is one command, not a new segment."""
    return re.sub(r"\\\r?\n", " ", text or "")


def _inactive_spans(text):
    """Interiors of quotes, and ``#`` comments through end of line.

    The quote marks themselves stay active so ``--threads \"8\"`` still
    has a flag outside the quotes and a quoted value.
    """
    spans = []
    i = 0
    n = len(text or "")
    quote = None
    start = 0
    while i < n:
        ch = text[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                i += 2
                continue
            if ch == quote:
                spans.append((start, i))
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            start = i + 1
            i += 1
            continue
        if ch == "#":
            comment = i
            while i < n and text[i] != "\n":
                i += 1
            spans.append((comment, i))
            continue
        i += 1
    return spans


def _in_span(pos, spans):
    for start, end in spans:
        if start <= pos < end:
            return True
    return False


def _text_references_key(texts, key):
    """True when a live ``{{key}}`` or ``{{key||default}}`` is in the command."""
    needles = ("{{" + key + "}}", "{{" + key + "||")
    for text in texts:
        spans = _inactive_spans(text)
        start = 0
        while start <= len(text):
            positions = [text.find(needle, start) for needle in needles]
            positions = [pos for pos in positions if pos >= 0]
            if not positions:
                break
            pos = min(positions)
            if not _in_span(pos, spans):
                return True
            start = pos + 1
    return False


def _parameter_key_counts(parameters, budget_units, texts):
    """``threads=8`` counts when the command still contains ``{{threads}}``.

    Job parameters are job-wide. A step that never mentions the key does
    not run that many threads, so the key is not a prior for that step.
    """
    found = []
    for key, value in (parameters or {}).items():
        name = str(key).split("||", 1)[0].strip()
        if name.lower() not in _CPU_PARAM_KEYS:
            continue
        if not _text_references_key(texts, name):
            continue
        cores = _cores_from_token(value, parameters, budget_units, allow_placeholder=False)
        if cores is not None and cores > 0:
            found.append(cores)
    return found


def _placeholder_counts(text, parameters, budget_units, spans):
    found = []
    for match in _PLACEHOLDER.finditer(text or ""):
        if _in_span(match.start(), spans):
            continue
        body = match.group(1)
        key = body.split("||", 1)[0]
        if key != key.strip():
            continue
        if key != "ThreadN" and key.lower() not in _CPU_PARAM_KEYS:
            continue
        cores = _cores_from_placeholder(body, parameters, budget_units)
        if cores is not None and cores > 0:
            found.append(cores)
    return found


def _matched_value(match):
    groups = match.groupdict()
    for key in ("eq", "sep", "glued", "value"):
        raw = groups.get(key)
        if raw is not None:
            return raw
    return None


def _flag_counts(pattern, text, parameters, budget_units, accept_name, spans):
    found = []
    for match in pattern.finditer(text or ""):
        if _in_span(match.start(), spans):
            continue
        if not accept_name(match):
            continue
        cores = _cores_from_token(_matched_value(match), parameters, budget_units)
        if cores is not None and cores > 0:
            found.append(cores)
    return found


def _tool_short_flags(names):
    enabled = set(_GLOBAL_SHORT)
    for name in names:
        flag = _TOOL_SHORT.get(name)
        if flag is None:
            for tool, tool_flag in _TOOL_SHORT.items():
                if name.startswith(tool + "-") or name.startswith(tool + "_"):
                    flag = tool_flag
                    break
        if flag:
            enabled.add(flag)
    return enabled


def _basenames(text, software):
    names = set()
    if software:
        base = os.path.basename(str(software).strip().strip("'\""))
        if base:
            names.add(base.lower())
    for token in re.split(r"[\s\"';|&<>()]+", text or ""):
        base = os.path.basename(token.strip().strip("'\""))
        if base:
            names.add(base.lower())
    return names


def _mask_placeholders(text):
    saved = []

    def hold(match):
        saved.append(match.group(0))
        return "\0%d\0" % (len(saved) - 1)

    return _PLACEHOLDER.sub(hold, text or ""), saved


def _restore_placeholders(text, saved):
    def put(match):
        return saved[int(match.group(1))]

    return _PLACEHOLDER_SLOT.sub(put, text)


def _short_counts(segment, software, parameters, budget_units, spans):
    enabled = _tool_short_flags(_basenames(segment, software))

    def accept(match):
        return match.group("flag") in enabled

    return _flag_counts(_SHORT_FLAG, segment, parameters, budget_units, accept, spans)


def _counts_in_text(text, parameters, software, budget_units):
    found = []
    spans = _inactive_spans(text)
    found.extend(
        _flag_counts(
            _LONG_FLAG,
            text,
            parameters,
            budget_units,
            lambda match: match.group("name").lower() in _LONG_NAMES,
            spans,
        )
    )
    found.extend(
        _flag_counts(
            _ENV_ASSIGN,
            text,
            parameters,
            budget_units,
            lambda match: True,
            spans,
        )
    )
    found.extend(_placeholder_counts(text, parameters, budget_units, spans))
    masked, saved = _mask_placeholders(text or "")
    segments = _SEGMENT.split(masked) or [""]
    for index, segment in enumerate(segments):
        # The step executable applies to the first simple command. Later
        # commands enable short flags only from their own executable, so
        # ``bowtie2 -p 2 && macs2 -p 8`` does not read the p-value as threads.
        segment = _restore_placeholders(segment, saved)
        extra = software if index == 0 else ""
        found.extend(_short_counts(segment, extra, parameters, budget_units, _inactive_spans(segment)))
    return found
