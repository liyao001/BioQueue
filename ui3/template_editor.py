"""Form bindings for template drafts. Draft edits never write to the database."""
import copy
import json

from QueueDB.protocol_template import (
    ProtocolTemplateError,
    expand_document,
    outline_document,
)


def blank_template_document():
    """Starter template for the create page: one sample map calling one block."""
    return {
        "samples": {"group": 1, "name": "rep{{index}}", "fields": {}},
        "blocks": {
            "process_sample": {
                "steps": [
                    {
                        "software": "echo",
                        "parameter": "Processing {{sample.name}} with {{sample.r1}}",
                    },
                ],
            },
        },
        "pipeline": [
            {"map": "samples", "steps": [{"call": "process_sample"}]},
        ],
    }


def _path(value):
    path = json.loads(value)
    if not isinstance(path, list) or not path or any(type(key) not in (str, int) for key in path):
        raise ProtocolTemplateError("Invalid editor field path.")
    return path


def _get(document, path):
    for key in path:
        document = document[key]
    return document


def read_template_form(form):
    raw = form.get("template") or ""
    if len(raw.encode()) > 1024 * 1024:
        raise ProtocolTemplateError("Template is too large (max 1 MB).")
    document = json.loads(raw)
    if not isinstance(document, dict):
        raise ProtocolTemplateError("Template must be a JSON object.")
    if form.get("template_mode") != "visual":
        return document
    for name, value in form.items():
        prefix, _, encoded = name.partition(":")
        if prefix not in ("tf", "tj", "ti", "tb"):
            continue
        path = _path(encoded)
        if prefix == "tj":
            value = json.loads(value or "{}")
            if not isinstance(value, dict):
                raise ProtocolTemplateError(f"{path[-1]} must be a JSON object.")
        elif prefix == "ti":
            value = int(value)
        elif prefix == "tb":
            value = value == "1"
        _get(document, path[:-1])[path[-1]] = value
    _apply_pair_fields(document, form)
    return document


def _apply_pair_fields(document, form):
    """Replace dicts edited as name/value rows. A marker is sent even when every row was removed."""
    grouped = {}
    managed = []
    for name in form:
        if name.startswith("tpset:"):
            path = _path(name[len("tpset:"):])
            managed.append(path)
            grouped.setdefault(tuple(path), {})
        elif name.startswith("tp:"):
            try:
                path_json, index, side = name[len("tp:"):].rsplit(":", 2)
            except ValueError:
                raise ProtocolTemplateError("Invalid field row.")
            if side not in ("k", "v"):
                raise ProtocolTemplateError("Invalid field row.")
            path = _path(path_json)
            grouped.setdefault(tuple(path), {}).setdefault(index, {})[side] = form.get(name) or ""
    for path in managed:
        rows = grouped.get(tuple(path), {})
        result = {}
        order = sorted(rows, key=lambda item: int(item) if str(item).isdigit() else str(item))
        for index in order:
            slot = rows[index]
            key = (slot.get("k") or "").strip()
            value = slot.get("v") if slot.get("v") is not None else ""
            if not key and not str(value).strip():
                continue
            if not key:
                raise ProtocolTemplateError("Enter a name for each field.")
            if key in result:
                raise ProtocolTemplateError(f"Duplicate name '{key}'.")
            result[key] = value
        _get(document, path[:-1])[path[-1]] = result


def _rename_calls(value, old, new):
    if isinstance(value, dict):
        if value.get("call") == old:
            value["call"] = new
        for item in value.values():
            _rename_calls(item, old, new)
    elif isinstance(value, list):
        for item in value:
            _rename_calls(item, old, new)


def edit_template_document(document, action, encoded_path="", block_name="", rename_to=""):
    if action in ("show_json", "show_forms", "format"):
        return document
    if action == "add_block":
        name = block_name.strip()
        if not name or name in document.setdefault("blocks", {}):
            raise ProtocolTemplateError("Enter a new, unique block name.")
        document["blocks"][name] = {"steps": []}
        return document
    if action == "rename_block":
        path = _path(encoded_path)
        if path[:1] != ["blocks"] or len(path) != 2:
            raise ProtocolTemplateError("Choose a block to rename.")
        old = path[1]
        new = (rename_to or "").strip()
        blocks = document.setdefault("blocks", {})
        if old not in blocks:
            raise ProtocolTemplateError("That block is no longer in the template.")
        if not new:
            raise ProtocolTemplateError("Enter a block name.")
        if new != old and new in blocks:
            raise ProtocolTemplateError("Enter a new, unique block name.")
        if new != old:
            document["blocks"] = {(new if key == old else key): value for key, value in blocks.items()}
            _rename_calls(document, old, new)
        return document
    path = _path(encoded_path)
    if action in ("add_step", "add_call", "add_map"):
        items = _get(document, path)
        if not isinstance(items, list):
            raise ProtocolTemplateError("Choose a steps list.")
        if action == "add_step":
            items.append({"software": "", "parameter": ""})
        elif action == "add_call":
            items.append({"call": next(iter(document.get("blocks") or {}), ""), "args": {}})
        else:
            if path != ["pipeline"]:
                raise ProtocolTemplateError("Sample maps belong in the pipeline.")
            items.append({"map": "samples", "steps": []})
    elif action == "remove":
        parent = _get(document, path[:-1])
        if path[:1] == ["blocks"] and len(path) == 2:
            def calls(value):
                if isinstance(value, dict):
                    return value.get("call") == path[1] or any(calls(item) for item in value.values())
                return isinstance(value, list) and any(calls(item) for item in value)
            if calls(document):
                raise ProtocolTemplateError("Remove calls to this block before deleting it.")
        del parent[path[-1]]
    elif action in ("up", "down"):
        parent, index = _get(document, path[:-1]), path[-1]
        target = index + (-1 if action == "up" else 1)
        if 0 <= target < len(parent):
            parent[index], parent[target] = parent[target], parent[index]
    else:
        raise ProtocolTemplateError("Unknown editor action.")
    return document


def _one_line(value, limit=72):
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def _pair_rows(value):
    if not isinstance(value, dict):
        return []
    return [{"key": str(key), "value": "" if item is None else str(item)} for key, item in value.items()]


def _preview_count(value):
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = 2
    return min(8, max(1, count))


def _template_tokens(document):
    samples = document.get("samples") or {}
    try:
        group = max(1, int(samples.get("group") or 1))
    except (TypeError, ValueError):
        group = 1
    tokens = ["sample.index", "sample.name", "sample.prefix", "sample.files"]
    tokens.extend("sample.r{}".format(slot) for slot in range(1, group + 1))
    fields = set()
    declared = samples.get("fields") or {}
    if isinstance(declared, dict):
        fields.update(str(key) for key in declared)
    args = set()

    def visit(items):
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            outputs = item.get("outputs") or {}
            if isinstance(outputs, dict):
                fields.update(str(key) for key in outputs)
            call_args = item.get("args") or {}
            if isinstance(call_args, dict):
                args.update(str(key) for key in call_args if str(key).isidentifier())
            if "map" in item or "call" in item:
                visit(item.get("steps"))

    visit(document.get("pipeline"))
    for block in (document.get("blocks") or {}).values():
        if isinstance(block, dict):
            visit(block.get("steps"))
    for key in sorted(fields):
        tokens.extend([
            "sample.{}".format(key),
            "samples.{}".format(key),
            "samples.first.{}".format(key),
            "samples.last.{}".format(key),
            "shared.{}".format(key),
        ])
    for key in ("name", "prefix", "index", "files"):
        tokens.extend(["samples.{}".format(key), "samples.first.{}".format(key), "samples.last.{}".format(key)])
    tokens.extend(sorted(args))
    return sorted(set(tokens), key=str.lower)


def _template_preview(document, preview_samples):
    samples = document.get("samples") if isinstance(document.get("samples"), dict) else {}
    try:
        group = max(1, int(samples.get("group") or 1))
    except (TypeError, ValueError):
        group = 1
    dummy = ";".join("file{}".format(index) for index in range(1, group * preview_samples + 1))
    try:
        preview = expand_document(document, dummy, "")
        error = ""
    except ProtocolTemplateError as exc:
        preview = []
        error = str(exc)
    try:
        outline = outline_document(document)
    except ProtocolTemplateError as exc:
        outline = []
        error = error or str(exc)
    return preview, outline, error


def template_editor_context(document, environments, mode="visual", preview_samples=2):
    document = copy.deepcopy(document)
    if not isinstance(document, dict) or not isinstance(document.get("pipeline"), list):
        raise ProtocolTemplateError("Template needs a pipeline list.")
    if not isinstance(document.setdefault("blocks", {}), dict) or not isinstance(document.setdefault("samples", {}), dict):
        raise ProtocolTemplateError("Samples and blocks must be JSON objects.")
    preview_samples = _preview_count(preview_samples)

    def action(name, path):
        return json.dumps({"editor_action": name, "editor_path": json.dumps(path)})

    def field(path):
        return json.dumps(path)

    block_anchors = {
        name: "tpl-block-{}".format(index)
        for index, name in enumerate(document["blocks"], start=1)
    }

    def items_context(items, path):
        if not isinstance(items, list):
            raise ProtocolTemplateError("Steps must be a list.")
        nodes = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                raise ProtocolTemplateError("Steps must be JSON objects.")
            if item.get("env") is not None and not isinstance(item["env"], str):
                raise ProtocolTemplateError("Step env must be an environment name.")
            here = path + [index]
            kind = "map" if "map" in item else "call" if "call" in item else "step"
            if kind == "step":
                summary = _one_line(item.get("parameter")) or (item.get("env") or "Default environment")
            elif kind == "call":
                args = item.get("args") or {}
                if isinstance(args, dict) and args:
                    summary = _one_line(", ".join("{}={}".format(key, value) for key, value in args.items())) or "Block call"
                else:
                    summary = "Block call"
            else:
                summary = "Runs once per sample"
            node = {
                "kind": kind, "item": item, "number": index + 1, "summary": summary,
                "key": json.dumps(here),
                "anchor": block_anchors.get(item.get("call"), "") if kind == "call" else "",
                "paths": {key: field(here + [key]) for key in ("software", "parameter", "env", "version_check", "force_local", "gpu_step", "outputs", "call", "args")},
                "output_rows": _pair_rows(item.get("outputs")),
                "arg_rows": _pair_rows(item.get("args")),
                "up": action("up", here), "down": action("down", here), "remove": action("remove", here),
            }
            if kind == "map":
                node["children"] = items_context(item.get("steps", []), here + ["steps"])
            nodes.append(node)
        return {"nodes": nodes, "add_step": action("add_step", path), "add_call": action("add_call", path), "add_map": action("add_map", path) if path == ["pipeline"] else ""}

    blocks = []
    for name, block in document["blocks"].items():
        if not isinstance(block, dict):
            raise ProtocolTemplateError("Each block must be an object with a steps list.")
        blocks.append({
            "name": name,
            "anchor": block_anchors[name],
            "body": items_context(block.get("steps", []), ["blocks", name, "steps"]),
            "remove": action("remove", ["blocks", name]),
            "rename": action("rename_block", ["blocks", name]),
        })
    envs = []
    seen = set()
    for env in sorted(environments, key=lambda env: env.user_id is None):
        if env.name not in seen:
            envs.append(env)
            seen.add(env.name)
    preview, outline, preview_error = _template_preview(document, preview_samples)
    return {"editor": {
        "source": json.dumps(document, indent=2), "mode": mode,
        "blocks": blocks, "block_names": list(document["blocks"]),
        "pipeline": items_context(document["pipeline"], ["pipeline"]),
        "environments": envs, "environment_names": seen,
        "group": document["samples"].get("group", 1),
        "sample_name": document["samples"].get("name", "rep{{index}}"),
        "sample_field_rows": _pair_rows(document["samples"].get("fields")),
        "sample_fields_path": json.dumps(["samples", "fields"]),
        "preview": preview,
        "preview_samples": preview_samples,
        "preview_error": preview_error,
        "outline": outline,
        "tokens": _template_tokens(document),
    }}
