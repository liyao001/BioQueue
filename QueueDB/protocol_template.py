"""Expand a protocol template (samples, blocks, map) into a flat step list.

The worker still runs an ordered list of commands. A template is the shorter
form: one body per replicate, then join steps that see every replicate.
Expansion fills sample names and file slots. Job placeholders such as
{{JobName}} and {{InputFile:N}} are left for the runner.
"""

import hashlib
import json
import re

TOKEN_RE = re.compile(r"\{\{([^{}]+)\}\}")
MAX_SAMPLES = 500
MAX_STEPS = 5000
_SUBSTITUTE_PASSES = 6


class ProtocolTemplateError(ValueError):
    """The template or sample sheet cannot be expanded."""


class ExpandedStep:
    """One runnable step. Attribute names match QueueDB Step where the runner reads them."""

    def __init__(self, software, parameter, version_check, step_hash, step_order):
        self.software = software
        self.parameter = parameter
        self.version_check = version_check or ""
        self.hash = step_hash
        self.step_order = step_order
        self.specify_output = ""
        self.env = None
        self.env_name = ""
        self.force_local = 0
        self.gpu_step = 0

    def __repr__(self):
        return f"ExpandedStep({self.software} {self.parameter})"


def step_template_hash(software, parameter):
    """Hash the unbound command so replicates share one resource checkpoint."""
    payload = "{} {}".format(software or "", (parameter or "").strip())
    return hashlib.md5(payload.encode()).hexdigest()


def split_input_files(text):
    return [part.strip() for part in (text or "").split(";") if part.strip()]


def parse_sample_sheet(text):
    raw = (text or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise ProtocolTemplateError("Sample sheet is not valid JSON.")
    if not isinstance(data, list):
        raise ProtocolTemplateError("Sample sheet must be a JSON list of records.")
    for index, row in enumerate(data, start=1):
        if not isinstance(row, dict):
            raise ProtocolTemplateError(f"Sample {index} must be a JSON object.")
    return data


def template_input_files(input_file, sample_sheet):
    """Effective input slots for templates; explicit sheet files take precedence."""
    sheet = parse_sample_sheet(sample_sheet)
    explicit = [_row_has_files(row) for row in sheet]
    if any(explicit):
        if not all(explicit):
            raise ProtocolTemplateError(
                "Every sample row must include files, or none of them."
            )
        return [
            path
            for number, row in enumerate(sheet, 1)
            for path in _files_from_row(row, number)
        ]
    return split_input_files(input_file)


def is_template_payload(payload):
    return isinstance(payload, dict) and isinstance(payload.get("pipeline"), list)


def canonical_template(document):
    """Stable JSON for storage and the protocol version hash."""
    kept = {}
    for key in ("samples", "blocks", "pipeline"):
        if key in document:
            kept[key] = document[key]
    return json.dumps(kept, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def normalize_template(payload):
    """Validate a template document and return its canonical JSON."""
    if not isinstance(payload, dict):
        raise ProtocolTemplateError("Protocol template must be a JSON object.")
    if not isinstance(payload.get("pipeline"), list):
        raise ProtocolTemplateError("Protocol template needs a pipeline list.")
    if payload.get("blocks") is not None and not isinstance(
        payload.get("blocks"), dict
    ):
        raise ProtocolTemplateError("blocks must be a JSON object.")
    document = json.loads(canonical_template(payload))
    _validate_document(document)
    for step in template_step_items(document):
        if step.get("env") is not None and not isinstance(step["env"], str):
            raise ProtocolTemplateError("Step env must be an environment name or null.")
        for key in ("force_local", "gpu_step"):
            if key in step and (not isinstance(step[key], (bool, int)) or step[key] not in (0, 1)):
                raise ProtocolTemplateError(f"Step {key} must be true or false.")
    return canonical_template(document)


def template_step_items(document):
    """Visit step definitions once, including steps in unused blocks."""
    def visit(items):
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            if "software" in item:
                yield item
            if "map" in item:
                yield from visit(item.get("steps"))
    yield from visit(document.get("pipeline"))
    for block in (document.get("blocks") or {}).values():
        if isinstance(block, dict):
            yield from visit(block.get("steps"))


def resolve_template_environments(document, owner_id):
    """Resolve portable names in the protocol owner's environment scope."""
    names = {item.get("env") for item in template_step_items(document) if item.get("env")}
    if not names:
        return {}
    from django.db.models import Q
    from QueueDB.models import VirtualEnvironment

    available = list(VirtualEnvironment.objects.filter(
        Q(user_id=owner_id) | Q(user_id=None), name__in=names,
    ))
    resolved = {}
    for name in sorted(names):
        own = [env for env in available if env.name == name and env.user_id == owner_id]
        choices = own or [env for env in available if env.name == name and env.user_id is None]
        if len(choices) != 1:
            raise ProtocolTemplateError(f"Environment '{name}' is missing, inaccessible, or ambiguous. Choose an available environment.")
        resolved[name] = choices[0]
    return resolved


def expand_job(protocol, input_file, sample_sheet):
    """
    Expand protocol.template for this job.

    Returns a list of ExpandedStep, or None when the protocol has no template.
    """
    raw = (getattr(protocol, "template", None) or "").strip()
    if not raw:
        return None
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        raise ProtocolTemplateError("Stored protocol template is not valid JSON.")
    if not isinstance(document, dict):
        raise ProtocolTemplateError("Stored protocol template is not a JSON object.")
    environments = resolve_template_environments(document, getattr(protocol, "user_id", None))
    steps = expand_document(document, input_file, sample_sheet)
    for step in steps:
        step.env = environments.get(step.env_name)
    return steps


def expand_document(document, input_file, sample_sheet):
    records = build_records(
        document.get("samples") or {},
        split_input_files(input_file),
        parse_sample_sheet(sample_sheet),
    )
    ctx = _ExpandContext(document.get("blocks") or {}, records)
    _expand_items(document.get("pipeline") or [], ctx, sample=None)
    if not ctx.steps:
        raise ProtocolTemplateError("Template expanded to zero steps.")
    if len(ctx.steps) > MAX_STEPS:
        raise ProtocolTemplateError(
            f"Template expanded to more than {MAX_STEPS} steps."
        )
    return ctx.steps


def outline_document(document):
    """Read-only lines describing the template, for the protocol page."""
    if not isinstance(document, dict):
        return []
    lines = []
    _outline_items(
        document.get("pipeline") or [], document.get("blocks") or {}, 0, lines, ()
    )
    return lines


def build_records(schema, input_files, sheet):
    if schema is None:
        schema = {}
    if not isinstance(schema, dict):
        raise ProtocolTemplateError("samples must be a JSON object.")
    group = _group_size(schema)
    name_template = schema.get("name") or "rep{{index}}"
    if not isinstance(name_template, str):
        raise ProtocolTemplateError("samples.name must be a string.")
    fields = schema.get("fields") or {}
    if not isinstance(fields, dict):
        raise ProtocolTemplateError("samples.fields must be a JSON object.")
    sheet = sheet or []
    rows_with_files = [index for index, row in enumerate(sheet) if _row_has_files(row)]
    if rows_with_files and len(rows_with_files) != len(sheet):
        raise ProtocolTemplateError(
            "Every sample row must include files, or none of them."
        )
    if rows_with_files:
        count = len(sheet)
    else:
        if group and len(input_files) % group != 0:
            raise ProtocolTemplateError(
                f"Input file count ({len(input_files)}) is not divisible by files per sample ({group})."
            )
        count = len(input_files) // group if group else 0
        if count == 0:
            raise ProtocolTemplateError(
                "Add input files, or put r1/r2 on each sample row."
            )
        if len(sheet) > count:
            raise ProtocolTemplateError("Sample sheet has more rows than input groups.")
    if count > MAX_SAMPLES:
        raise ProtocolTemplateError(f"At most {MAX_SAMPLES} samples are supported.")

    records = []
    for index in range(count):
        row = sheet[index] if index < len(sheet) else {}
        number = index + 1
        if rows_with_files:
            files = _files_from_row(row, number)
        else:
            files = [
                f"{{{{InputFile:{index * group + slot + 1}}}}}" for slot in range(group)
            ]
        name = row.get("name")
        if name is None or str(name).strip() == "":
            name = _substitute(
                name_template,
                _Bind(records=[], sample={"index": str(number)}, shared={}, args={}),
            )
        else:
            name = str(name).strip()
        record = {
            "index": str(number),
            "name": name,
            "prefix": str(row.get("prefix") or f"{{{{JobName}}}}_{name}"),
            "files": " ".join(files),
        }
        for slot, path in enumerate(files, start=1):
            record[f"r{slot}"] = path
        for key, value in fields.items():
            if key in record:
                continue
            record[str(key)] = "" if value is None else str(value)
        for key, value in row.items():
            if key in ("name", "prefix", "r1", "r2", "r3", "files", "index"):
                continue
            if _row_file_key(key):
                continue
            record[str(key)] = "" if value is None else str(value)
        _resolve_self_refs(record)
        records.append(record)
    return records


class _Bind:
    def __init__(self, records, sample, shared, args):
        self.records = records
        self.sample = sample
        self.shared = shared
        self.args = args


class _ExpandContext:
    def __init__(self, blocks, records):
        self.blocks = blocks
        self.records = records
        self.shared = {}
        self.steps = []
        self.stack = []


def _validate_document(document):
    """Check structure without requiring a particular job's samples or metadata."""
    schema = document.get("samples") or {}
    if not isinstance(schema, dict):
        raise ProtocolTemplateError("samples must be a JSON object.")
    _group_size(schema)
    if not isinstance(schema.get("name") or "rep{{index}}", str):
        raise ProtocolTemplateError("samples.name must be a string.")
    if not isinstance(schema.get("fields") or {}, dict):
        raise ProtocolTemplateError("samples.fields must be a JSON object.")
    blocks = document.get("blocks") or {}
    if not isinstance(blocks, dict):
        raise ProtocolTemplateError("blocks must be a JSON object.")

    def check_tokens(value, in_map):
        for body in TOKEN_RE.findall(str(value)):
            parts = body.split("||", 1)[0].strip().split(".")
            if parts[0] == "sample":
                if not in_map:
                    raise ProtocolTemplateError(
                        "{{sample}} is only valid inside a sample map."
                    )
                if len(parts) != 2:
                    raise ProtocolTemplateError("Use {{sample.field}}.")
            elif parts[0] == "shared" and len(parts) != 2:
                raise ProtocolTemplateError("Use {{shared.field}}.")
            elif parts[0] == "samples":
                if len(parts) not in (2, 3):
                    raise ProtocolTemplateError(
                        "Use {{samples.field}} or {{samples.first.field}}."
                    )
                if (
                    len(parts) == 3
                    and parts[1] not in ("first", "last")
                    and not parts[1].isdigit()
                ):
                    raise ProtocolTemplateError(
                        f"Unknown samples selector '{parts[1]}'."
                    )

    has_step = False

    def check_items(items, in_map=False, stack=()):
        nonlocal has_step
        if not isinstance(items, list):
            raise ProtocolTemplateError("steps must be a list.")
        for item in items:
            if not isinstance(item, dict):
                raise ProtocolTemplateError(
                    "Each pipeline entry must be a JSON object."
                )
            if "map" in item:
                if in_map or stack:
                    raise ProtocolTemplateError("Nested maps are not supported.")
                if item.get("map") != "samples":
                    raise ProtocolTemplateError('Only map: "samples" is supported.')
                check_items(item.get("steps"), True, stack)
            elif "call" in item:
                name = str(item.get("call") or "").strip()
                if name in stack:
                    raise ProtocolTemplateError(f"Block '{name}' calls itself.")
                block = blocks.get(name)
                if not isinstance(block, dict):
                    raise ProtocolTemplateError(f"Unknown block '{name}'.")
                args = item.get("args") or {}
                if not isinstance(args, dict):
                    raise ProtocolTemplateError("call args must be a JSON object.")
                for value in args.values():
                    check_tokens(value, in_map)
                check_items(block.get("steps"), in_map, stack + (name,))
            elif "software" in item:
                if not str(item.get("software") or "").strip():
                    raise ProtocolTemplateError("A step is missing software.")
                has_step = True
                outputs = item.get("outputs") or {}
                if not isinstance(outputs, dict):
                    raise ProtocolTemplateError("outputs must be a JSON object.")
                for value in [
                    item.get("parameter", ""),
                    item.get("version_check", ""),
                    *outputs.values(),
                ]:
                    check_tokens(value, in_map)
            else:
                raise ProtocolTemplateError("Each entry needs software, call, or map.")

    check_items(document.get("pipeline"))
    if not has_step:
        raise ProtocolTemplateError("Template expanded to zero steps.")
    _reject_field_typos(document, blocks)


def _edit_distance(left, right):
    if abs(len(left) - len(right)) > 1:
        return 2
    previous = list(range(len(right) + 1))
    for i, char in enumerate(left, start=1):
        current = [i]
        for j, other in enumerate(right, start=1):
            current.append(min(previous[j] + 1, current[-1] + 1, previous[j - 1] + (char != other)))
        previous = current
    return previous[-1]


def _closest_field(name, known):
    """A known field one edit away, for catching misspelled placeholders."""
    if len(name) < 2 or name in known:
        return ""
    for candidate in sorted(known):
        if abs(len(candidate) - len(name)) > 1:
            continue
        if _edit_distance(name, candidate) <= 1:
            return candidate
    return ""


def _output_names(items, blocks, stack=()):
    names = set()
    if not isinstance(items, list):
        return names
    for item in items:
        if not isinstance(item, dict):
            continue
        outputs = item.get("outputs") or {}
        if isinstance(outputs, dict):
            names.update(str(key) for key in outputs)
        if "map" in item:
            names |= _output_names(item.get("steps"), blocks, stack)
        elif "call" in item:
            name = str(item.get("call") or "").strip()
            block = blocks.get(name) if name and name not in stack else None
            if isinstance(block, dict):
                names |= _output_names(block.get("steps"), blocks, stack + (name,))
    return names


def _known_sample_fields(document, blocks):
    schema = document.get("samples") or {}
    if not isinstance(schema, dict):
        schema = {}
    try:
        group = _group_size(schema)
    except ProtocolTemplateError:
        group = 1
    known = {"index", "name", "prefix", "files"}
    known.update("r{}".format(slot) for slot in range(1, group + 1))
    fields = schema.get("fields") or {}
    if isinstance(fields, dict):
        known.update(str(key) for key in fields)
    known |= _output_names(document.get("pipeline"), blocks)
    for block in blocks.values():
        if isinstance(block, dict):
            known |= _output_names(block.get("steps"), blocks)
    return known


def _reject_field_typos(document, blocks):
    """Reject a placeholder that is one edit from a real sample, output, or shared name.

    A name with no near match can still be required metadata filled in on the job.
    """
    known = _known_sample_fields(document, blocks)

    def visit(value):
        if isinstance(value, str):
            for body in TOKEN_RE.findall(value):
                base = body.split("||", 1)[0].strip()
                parts = [part.strip() for part in base.split(".") if part.strip()]
                if len(parts) < 2 or parts[0] not in ("sample", "samples", "shared"):
                    continue
                key = parts[-1]
                if key in known or key in ("first", "last") or key.isdigit():
                    continue
                match = _closest_field(key, known)
                if match:
                    kind = "shared" if parts[0] == "shared" else "sample"
                    raise ProtocolTemplateError(
                        f"Unknown {kind} field '{key}'. Did you mean '{match}'?"
                    )
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(document)


def _group_size(schema):
    try:
        group = int(schema.get("group") or 1)
    except (TypeError, ValueError):
        raise ProtocolTemplateError("samples.group must be an integer.")
    if group < 1:
        raise ProtocolTemplateError("samples.group must be at least 1.")
    return group


def _row_file_key(key):
    return key == "files" or (
        isinstance(key, str) and re.match(r"^r\d+$", key) is not None
    )


def _row_has_files(row):
    if not isinstance(row, dict):
        return False
    if isinstance(row.get("files"), list) and row.get("files"):
        return True
    return any(str(row.get(f"r{slot}") or "").strip() for slot in range(1, 9))


def _files_from_row(row, number):
    if isinstance(row.get("files"), list) and row.get("files"):
        files = [str(item).strip() for item in row["files"] if str(item).strip()]
    else:
        files = []
        for slot in range(1, 9):
            value = row.get(f"r{slot}")
            if value is None or str(value).strip() == "":
                if slot > 1 and files:
                    break
                if slot == 1:
                    continue
            else:
                files.append(str(value).strip())
    if not files:
        raise ProtocolTemplateError(f"Sample {number} is missing files.")
    return files


def _resolve_self_refs(record):
    bind = _Bind(records=[], sample=record, shared={}, args={})
    for _ in range(_SUBSTITUTE_PASSES):
        changed = False
        for key, value in list(record.items()):
            updated = _substitute(str(value), bind)
            if updated != value:
                record[key] = updated
                changed = True
        if not changed:
            return


def _expand_items(items, ctx, sample):
    if not isinstance(items, list):
        raise ProtocolTemplateError("steps must be a list.")
    for item in items:
        if not isinstance(item, dict):
            raise ProtocolTemplateError("Each pipeline entry must be a JSON object.")
        if "map" in item:
            _expand_map(item, ctx, sample)
        elif "call" in item:
            _expand_call(item, ctx, sample)
        elif "software" in item:
            _expand_software(item, ctx, sample)
        else:
            raise ProtocolTemplateError("Each entry needs software, call, or map.")


def _expand_map(item, ctx, sample):
    if item.get("map") != "samples":
        raise ProtocolTemplateError('Only map: "samples" is supported.')
    if sample is not None:
        raise ProtocolTemplateError("Nested maps are not supported.")
    body = item.get("steps")
    if not isinstance(body, list):
        raise ProtocolTemplateError("map.steps must be a list.")
    for record in ctx.records:
        _expand_items(body, ctx, sample=record)


def _expand_call(item, ctx, sample):
    name = str(item.get("call") or "").strip()
    if not name:
        raise ProtocolTemplateError("call is missing a block name.")
    if name in ctx.stack:
        raise ProtocolTemplateError(f"Block '{name}' calls itself.")
    block = ctx.blocks.get(name)
    if not isinstance(block, dict):
        raise ProtocolTemplateError(f"Unknown block '{name}'.")
    body = block.get("steps")
    if not isinstance(body, list):
        raise ProtocolTemplateError(f"Block '{name}' needs a steps list.")
    raw_args = item.get("args") or {}
    if not isinstance(raw_args, dict):
        raise ProtocolTemplateError("call args must be a JSON object.")
    bind = _Bind(ctx.records, sample, ctx.shared, {})
    args = {}
    for key, value in raw_args.items():
        args[str(key)] = _substitute("" if value is None else str(value), bind)
    ctx.stack.append(name)
    try:
        # Arguments are visible as {{name}} inside the block, alongside {{sample.*}}.
        _expand_items_with_args(body, ctx, sample, args)
    finally:
        ctx.stack.pop()


def _expand_items_with_args(items, ctx, sample, args):
    """Like _expand_items, but software/call substitution sees block arguments."""
    if not isinstance(items, list):
        raise ProtocolTemplateError("steps must be a list.")
    for item in items:
        if not isinstance(item, dict):
            raise ProtocolTemplateError("Each pipeline entry must be a JSON object.")
        if "map" in item:
            raise ProtocolTemplateError("Nested maps are not supported.")
        if "call" in item:
            # Resolve this call's args in the current argument scope, then enter the block
            # with only the callee's arguments so names do not leak across blocks.
            inner = dict(item)
            raw_args = inner.get("args") or {}
            if not isinstance(raw_args, dict):
                raise ProtocolTemplateError("call args must be a JSON object.")
            bind = _Bind(ctx.records, sample, ctx.shared, args)
            resolved = {}
            for key, value in raw_args.items():
                resolved[str(key)] = _substitute(
                    "" if value is None else str(value), bind
                )
            inner["args"] = resolved
            _expand_call(inner, ctx, sample)
        elif "software" in item:
            _expand_software(item, ctx, sample, args)
        else:
            raise ProtocolTemplateError("Each entry needs software, call, or map.")


def _expand_software(item, ctx, sample, args=None):
    software = str(item.get("software") or "").strip()
    if not software:
        raise ProtocolTemplateError("A step is missing software.")
    raw_parameter = "" if item.get("parameter") is None else str(item.get("parameter"))
    raw_version = (
        "" if item.get("version_check") is None else str(item.get("version_check"))
    )
    bind = _Bind(ctx.records, sample, ctx.shared, args or {})
    parameter = _substitute(raw_parameter, bind)
    version = _substitute(raw_version, bind)
    outputs = item.get("outputs") or {}
    if outputs:
        if not isinstance(outputs, dict):
            raise ProtocolTemplateError("outputs must be a JSON object.")
        target = sample if sample is not None else ctx.shared
        for key, value in outputs.items():
            target[str(key)] = _substitute("" if value is None else str(value), bind)
    if len(ctx.steps) >= MAX_STEPS:
        raise ProtocolTemplateError(
            f"Template expanded to more than {MAX_STEPS} steps."
        )
    ctx.steps.append(
        ExpandedStep(
            software=software,
            parameter=parameter,
            version_check=version,
            step_hash=step_template_hash(software, raw_parameter),
            step_order=len(ctx.steps) + 1,
        )
    )
    ctx.steps[-1].env_name = item.get("env") or ""
    ctx.steps[-1].force_local = int(bool(item.get("force_local", False)))
    ctx.steps[-1].gpu_step = int(bool(item.get("gpu_step", False)))


def _substitute(text, bind):
    current = "" if text is None else str(text)

    def replace(match):
        resolved, ok = _lookup(match.group(1).strip(), bind)
        if ok:
            return resolved
        return match.group(0)

    for _ in range(_SUBSTITUTE_PASSES):
        updated = TOKEN_RE.sub(replace, current)
        if updated == current:
            return current
        current = updated
    return current


def _lookup(body, bind):
    default = None
    base = body
    if "||" in body:
        base, default = body.split("||", 1)
        base = base.strip()
    parts = [part.strip() for part in base.split(".") if part.strip()]
    if not parts:
        return None, False
    root = parts[0]
    if len(parts) == 1 and root in bind.args:
        return str(bind.args[root]), True
    if root == "sample":
        if bind.sample is None:
            raise ProtocolTemplateError(
                "{{{{sample}}}} is only valid inside a sample map.".format()
            )
        if len(parts) != 2:
            raise ProtocolTemplateError("Use {{{{sample.field}}}}.".format())
        key = parts[1]
        if key not in bind.sample:
            if default is not None:
                return default, True
            raise ProtocolTemplateError(f"Unknown sample field '{key}'.")
        return str(bind.sample[key]), True
    if root == "samples":
        return _lookup_samples(parts, bind, default), True
    if root == "shared":
        if len(parts) != 2:
            raise ProtocolTemplateError("Use {{{{shared.field}}}}.".format())
        key = parts[1]
        if key not in bind.shared:
            if default is not None:
                return default, True
            raise ProtocolTemplateError(f"Unknown shared field '{key}'.")
        return str(bind.shared[key]), True
    if (
        root == "index"
        and len(parts) == 1
        and bind.sample is not None
        and "index" in bind.sample
    ):
        return str(bind.sample["index"]), True
    return None, False


def _lookup_samples(parts, bind, default):
    records = bind.records
    if len(parts) == 2:
        key = parts[1]
        values = []
        for record in records:
            if key not in record:
                if default is not None:
                    values.append(default)
                else:
                    raise ProtocolTemplateError(f"Unknown sample field '{key}'.")
            else:
                values.append(str(record[key]))
        return " ".join(values)
    if len(parts) != 3:
        raise ProtocolTemplateError(
            "Use {{{{samples.field}}}} or {{{{samples.first.field}}}}.".format()
        )
    selector, key = parts[1], parts[2]
    if selector == "first":
        record = records[0] if records else None
    elif selector == "last":
        record = records[-1] if records else None
    elif selector.isdigit():
        position = int(selector) - 1
        record = records[position] if 0 <= position < len(records) else None
    else:
        raise ProtocolTemplateError(f"Unknown samples selector '{selector}'.")
    if record is None:
        raise ProtocolTemplateError(f"Sample selector '{selector}' is out of range.")
    if key not in record:
        if default is not None:
            return default
        raise ProtocolTemplateError(f"Unknown sample field '{key}'.")
    return str(record[key])


def _outline_items(items, blocks, depth, lines, stack):
    if not isinstance(items, list):
        return
    for item in items:
        if not isinstance(item, dict):
            continue
        if "map" in item:
            lines.append({"depth": depth, "text": "for each sample"})
            _outline_items(item.get("steps") or [], blocks, depth + 1, lines, stack)
        elif "call" in item:
            name = str(item.get("call") or "").strip() or "(block)"
            args = item.get("args") or {}
            label = f"call {name}"
            if isinstance(args, dict) and args:
                rendered = ", ".join(f"{key}={args[key]}" for key in args)
                if len(rendered) > 80:
                    rendered = rendered[:79] + "…"
                label = f"call {name}({rendered})"
            lines.append({"depth": depth, "text": label})
            block = blocks.get(name) if isinstance(blocks, dict) else None
            if isinstance(block, dict) and name not in stack:
                _outline_items(
                    block.get("steps") or [], blocks, depth + 1, lines, stack + (name,)
                )
        elif "software" in item:
            parameter = str(item.get("parameter") or "").strip()
            if len(parameter) > 90:
                parameter = parameter[:89] + "…"
            text = str(item.get("software") or "").strip()
            if parameter:
                text = (text + " " + parameter).strip()
            lines.append({"depth": depth, "text": text})
