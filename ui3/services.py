"""Query helpers shared by ui3 views. Mirrors ui2 ownership and search rules."""

from __future__ import annotations

import difflib
import hashlib
import json
import operator
import os
import re
from functools import reduce

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q

from QueueDB.models import (
    Audition,
    FileArchive,
    Job,
    JobStatus,
    ProtocolList,
    ProtocolShortcut,
    Reference,
    Slave,
    Step,
    VirtualEnvironment,
    Workspace,
)

from .http import csv_ints, delegate_for, int_or_none


PAGE_SIZE_DEFAULT = 12
PAGE_SIZE_MAX = 100

STATUS_BADGE = {
    JobStatus.WRONG: "badge-error",
    JobStatus.RESOURCELOCK: "badge-warning",
    JobStatus.FINISHED: "badge-success",
    JobStatus.WAITING: "badge-ghost",
    JobStatus.RUNNING: "badge-info",
    JobStatus.INTERRUPTED: "badge-warning",
}


def paginate(queryset, request, page_size=PAGE_SIZE_DEFAULT, params=None):
    src = params if params is not None else request.GET
    try:
        size = int(src.get("page_size") or page_size)
    except (TypeError, ValueError):
        size = page_size
    size = max(1, min(size, PAGE_SIZE_MAX))
    try:
        page_number = int(src.get("page") or 1)
    except (TypeError, ValueError):
        page_number = 1
    paginator = Paginator(queryset, size)
    page = paginator.get_page(page_number)
    return page, paginator


def split_tokens(value):
    return [t for t in re.split(r"[\s,]+", (value or "").strip()) if t]


def visible_protocols(user):
    delegate = delegate_for(user)
    return ProtocolList.objects.filter(Q(user=delegate) | Q(user=None)).order_by("-id")


def filter_named_choices(queryset, q, limit=40, extra_fields=()):
    q = (q or "").strip()
    if not q:
        return queryset[:limit]
    filters = Q(name__icontains=q)
    for field in extra_fields:
        filters |= Q(**{"{}__icontains".format(field): q})
    if q.isdigit():
        filters = filters | Q(id=int(q))
    return queryset.filter(filters)[:limit]


def filter_environment_choices(queryset, q, limit=40):
    q = (q or "").strip()
    if not q:
        return queryset[:limit]
    filters = Q(name__icontains=q) | Q(ve_type__icontains=q)
    if q.isdigit():
        filters = filters | Q(id=int(q))
    return queryset.filter(filters)[:limit]


def visible_references(user):
    delegate = delegate_for(user)
    return Reference.objects.filter(Q(user=delegate) | Q(user=None)).order_by("-id")


def visible_workspaces(user):
    delegate = delegate_for(user)
    return Workspace.objects.filter(user=delegate).order_by("name")


def assignable_workspaces(user):
    """Workspaces a user may attach to a job. Staff may assign any workspace."""
    if getattr(user, "is_staff", False):
        return Workspace.objects.all().order_by("name")
    return visible_workspaces(user)


def visible_environments(user):
    delegate = delegate_for(user)
    return VirtualEnvironment.objects.filter(Q(user=delegate) | Q(user=None)).order_by("name")


def visible_runners(_user=None):
    """All cluster nodes. Slaves have no owner; matches ui2 runner picker."""
    return Slave.objects.all().order_by("name")


def assignable_runners(user):
    """Runners a user may attach to a job. Same global set as ui2 (no per-user slaves)."""
    return visible_runners(user)


def owned_jobs(user, scope="own"):
    delegate = delegate_for(user)
    scope = (scope or "own").lower()
    from QueueDB.models import CrossAccess

    owner_ids = []
    if scope in ("shared", "all"):
        owner_ids = list(
            CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True)
        )
    if scope == "shared":
        return Job.objects.filter(user_id__in=owner_ids)
    if scope == "all":
        return Job.objects.filter(Q(user=delegate) | Q(user_id__in=owner_ids))
    return Job.objects.filter(user=delegate)


def search_jobs(user, params):
    """
    Job search compatible with ui2 /jobs/search/ query params.

    Supported keys: job_name, job_name_not, parameter, parameter_not,
    input_file, input_file_not, protocol, protocol_name, protocol_name_not,
    workspace, workspace_name, workspace_name_not, status, status_not,
    visibility, id, id_not, parent_job, scope, mode, q
    """
    qs = owned_jobs(user, scope=params.get("scope", "own"))
    apply_vis_filter = True
    ws_id = int_or_none(params.get("workspace"))
    if ws_id is not None:
        qs = qs.filter(workspace_id=ws_id)
        apply_vis_filter = False

    parent_job_param = params.get("parent_job") or params.get("parent")
    listing_array_children = bool(parent_job_param and str(parent_job_param).isdigit())
    if listing_array_children:
        qs = qs.filter(parent_job_id=int(parent_job_param))
    else:
        qs = qs.filter(parent_job__isnull=True)

    combine_mode = (params.get("mode", "all") or "all").lower()
    use_or = combine_mode == "any"
    group_qs = []

    # ui2 nameOrId box: numeric tokens are ids, the rest are job-name keywords.
    q_ids = []
    q_names = []
    for token in split_tokens(params.get("q", "")):
        if token.isdigit():
            q_ids.append(int(token))
        else:
            q_names.append(token)

    field_map = {
        "job_name": "job_name__icontains",
        "parameter": "parameter__icontains",
        "input_file": "input_file__icontains",
    }
    extra_pos = {"job_name": q_names}
    for qp, lookup in field_map.items():
        tokens = split_tokens(params.get(qp, "")) + list(extra_pos.get(qp, []))
        neg_tokens = split_tokens(params.get(f"{qp}_not", "") or "")
        field_q = None
        if tokens:
            field_q = reduce(operator.and_, [Q(**{lookup: t}) for t in tokens])
            apply_vis_filter = False
        if neg_tokens:
            neg_q = reduce(operator.and_, [~Q(**{lookup: t}) for t in neg_tokens])
            field_q = neg_q if field_q is None else (field_q & neg_q)
            apply_vis_filter = False
        if field_q is not None:
            group_qs.append(field_q)

    proto = int_or_none(params.get("protocol"))
    if proto is not None:
        group_qs.append(Q(protocol_id=proto))

    ptokens = split_tokens(params.get("protocol_name", ""))
    if ptokens:
        group_qs.append(reduce(operator.and_, [Q(protocol__name__icontains=t) for t in ptokens]))
    pn_tokens = split_tokens(params.get("protocol_name_not", "") or "")
    if pn_tokens:
        group_qs.append(reduce(operator.and_, [~Q(protocol__name__icontains=t) for t in pn_tokens]))

    wtokens = split_tokens(params.get("workspace_name", ""))
    if wtokens:
        group_qs.append(reduce(operator.and_, [Q(workspace__name__icontains=t) for t in wtokens]))
    wn_tokens = split_tokens(params.get("workspace_name_not", "") or "")
    if wn_tokens:
        group_qs.append(reduce(operator.and_, [~Q(workspace__name__icontains=t) for t in wn_tokens]))

    stokens = csv_ints(params.get("status", ""))
    if stokens:
        group_qs.append(Q(status__in=stokens))
        apply_vis_filter = False
    sneg = csv_ints(params.get("status_not", ""))
    if sneg:
        group_qs.append(~Q(status__in=sneg))

    idtokens = csv_ints(params.get("id", "")) + q_ids
    if idtokens:
        group_qs.append(Q(id__in=idtokens))
        apply_vis_filter = False
    idneg = csv_ints(params.get("id_not", ""))
    if idneg:
        group_qs.append(~Q(id__in=idneg))

    if group_qs:
        qs = qs.filter(reduce(operator.or_ if use_or else operator.and_, group_qs))

    vtokens = [v for v in csv_ints(params.get("visibility", "")) if v in (0, 1, 2)]
    if vtokens:
        qs = qs.filter(visibility__in=vtokens)
    elif not listing_array_children:
        if apply_vis_filter:
            qs = qs.filter(visibility=1)
        else:
            qs = qs.filter(visibility__gte=1)

    return qs.select_related("protocol", "workspace", "slave").order_by("-create_time", "-pk")


def get_readable_job(user, pk):
    """Job visible under scope=all (own + CrossAccess read grants)."""
    return owned_jobs(user, scope="all").filter(pk=pk).select_related("protocol", "workspace", "slave").first()


def get_writable_job(user, pk):
    """
    Job the user may mutate: delegate owns it, or staff.

    CrossAccess read grants are not sufficient for writes.
    """
    job = Job.objects.filter(pk=pk).select_related("protocol", "workspace", "slave").first()
    if job is None:
        return None
    if getattr(user, "is_staff", False):
        return job
    delegate = delegate_for(user)
    try:
        if job.check_owner(delegate, read_only=False):
            return job
    except Exception:
        pass
    if job.user_id == getattr(delegate, "id", None):
        return job
    return None


def get_owned_job(user, pk, read_only=True):
    """READ uses scope=all; WRITES require ownership (or staff)."""
    if read_only:
        return get_readable_job(user, pk)
    return get_writable_job(user, pk)


def accessible_job_q(user):
    """Q matching jobs readable by user (own + CrossAccess read)."""
    delegate = delegate_for(user)
    from QueueDB.models import CrossAccess

    cross_ids = list(
        CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True)
    )
    if cross_ids:
        return Q(user=delegate) | Q(user_id__in=cross_ids)
    return Q(user=delegate)


def audit_operation(job, operation, comment=""):
    """Create an Audition record for a job operation (never raises)."""
    try:
        Audition(
            operation=operation,
            related_job=job,
            job_name=job.job_name,
            job_ver=job.version,
            prev_par=job.parameter,
            new_par=job.parameter,
            prev_input=job.input_file,
            current_input=job.input_file,
            protocol=job.protocol.name if job.protocol_id else "",
            protocol_ver=job.protocol_ver,
            resume_point=job.resume,
            user=job.user,
            comments=comment or None,
        ).save()
    except Exception:
        pass


def job_history(job):
    return (
        Audition.objects.filter(Q(related_job=job) | Q(job_name=job.job_name))
        .order_by("-create_time")
    )


def find_dependents(user, job, depth=1):
    """Jobs that reference this job via History/CrossAccess tags (ui2 port)."""
    depth = max(1, min(int(depth or 1), 10))
    accessible_q = accessible_job_q(user)
    visited_ids = {job.id}
    all_found_ids = set()
    frontier_info = {job.id: job.user_id}

    for _ in range(depth):
        if not frontier_info:
            break
        or_q = None
        for jid, uid in frontier_info.items():
            needle_h = "{{{{History:{}-".format(jid)
            piece = Q(parameter__icontains=needle_h) | Q(input_file__icontains=needle_h)
            needle_ca = "{{{{CrossAccess:{}-{}-".format(uid, jid)
            piece |= Q(parameter__icontains=needle_ca) | Q(input_file__icontains=needle_ca)
            or_q = piece if or_q is None else (or_q | piece)
        if or_q is None:
            break
        level_pairs = list(
            Job.objects.filter(accessible_q)
            .exclude(id__in=visited_ids)
            .filter(or_q)
            .values_list("id", "user_id")
        )
        if not level_pairs:
            break
        new_frontier = {jid: uid for jid, uid in level_pairs}
        level_ids = set(new_frontier.keys())
        all_found_ids |= level_ids
        visited_ids |= level_ids
        frontier_info = new_frontier

    return Job.objects.filter(id__in=list(all_found_ids)).select_related("protocol").order_by("-id")


def parent_job_ids(job):
    """Parent job IDs from {{History:JID-…}} and {{CrossAccess:UID-JID-…}} tags."""
    text = "{} {}".format(job.parameter or "", job.input_file or "")
    ids = set()
    try:
        for m in re.finditer(r"\{\{History:(\d+)-.*?\}\}", text, flags=re.IGNORECASE | re.DOTALL):
            try:
                ids.add(int(m.group(1)))
            except Exception:
                continue
        for m in re.finditer(r"\{\{CrossAccess:\d+-(\d+)-.*?\}\}", text, flags=re.IGNORECASE | re.DOTALL):
            try:
                ids.add(int(m.group(1)))
            except Exception:
                continue
    except Exception:
        return set()
    return ids


def find_dependencies(user, job):
    """Jobs this job references via History/CrossAccess tags (ui2 port)."""
    ids = parent_job_ids(job)
    if not ids:
        return Job.objects.none()
    return (
        Job.objects.filter(accessible_job_q(user), id__in=list(ids))
        .select_related("protocol")
        .order_by("-id")
    )


def _clamp_int(value, lo, hi, default):
    try:
        iv = int(value)
    except (TypeError, ValueError):
        iv = default
    return max(lo, min(hi, iv))


def build_job_dag(user, root_id, up=1, down=1, max_nodes=300):
    """
    Job dependency DAG around root (ui2 /jobs/dag/ port).

    An edge a→b means b references a via History/CrossAccess.
    Returns None if the root is not readable. Otherwise a dict with
    root, nodes, edges, truncated, max_nodes.
    """
    accessible_q = accessible_job_q(user)
    root_job = Job.objects.filter(accessible_q, pk=root_id).first()
    if root_job is None:
        return None

    up_depth = _clamp_int(up, 0, 10, 1)
    down_depth = _clamp_int(down, 0, 10, 1)
    max_nodes = _clamp_int(max_nodes, 1, 10000, 300)

    nodes_ids = {root_job.id}
    edges = set()

    if up_depth > 0:
        visited_up = {root_job.id}
        frontier_up = {root_job.id}
        for _ in range(up_depth):
            if not frontier_up or len(nodes_ids) >= max_nodes:
                break
            frontier_jobs = {j.id: j for j in Job.objects.filter(accessible_q, id__in=list(frontier_up))}
            next_frontier = set()
            for jid, job_obj in frontier_jobs.items():
                parent_ids = parent_job_ids(job_obj)
                if not parent_ids:
                    continue
                for pid in Job.objects.filter(accessible_q, id__in=list(parent_ids)).values_list("id", flat=True):
                    if len(nodes_ids) >= max_nodes:
                        break
                    nodes_ids.add(pid)
                    edges.add((pid, jid))
                    if pid not in visited_up:
                        next_frontier.add(pid)
            visited_up |= next_frontier
            frontier_up = next_frontier

    if down_depth > 0:
        visited_down = {root_job.id}
        frontier_down = {root_job.id}
        frontier_uid_map = {root_job.id: root_job.user_id}
        for _ in range(down_depth):
            if not frontier_down or len(nodes_ids) >= max_nodes:
                break
            or_q = None
            for jid in frontier_down:
                needle_h = "{{{{History:{}-".format(jid)
                piece = Q(parameter__icontains=needle_h) | Q(input_file__icontains=needle_h)
                uid = frontier_uid_map.get(jid)
                if uid is not None:
                    needle_ca = "{{{{CrossAccess:{}-{}-".format(uid, jid)
                    piece |= Q(parameter__icontains=needle_ca) | Q(input_file__icontains=needle_ca)
                or_q = piece if or_q is None else (or_q | piece)
            if or_q is None:
                break
            level_qs = list(Job.objects.filter(accessible_q).exclude(id__in=visited_down).filter(or_q))
            next_frontier = set()
            next_uid_map = {}
            for child in level_qs:
                if len(nodes_ids) >= max_nodes:
                    break
                nodes_ids.add(child.id)
                child_parents = parent_job_ids(child)
                for src_id in child_parents & frontier_down:
                    edges.add((src_id, child.id))
                if child.id not in visited_down:
                    next_frontier.add(child.id)
                    next_uid_map[child.id] = child.user_id
            visited_down |= next_frontier
            frontier_down = next_frontier
            frontier_uid_map = next_uid_map

    nodes = []
    if nodes_ids:
        for j in (
            Job.objects.filter(accessible_q, id__in=list(nodes_ids))
            .only("id", "job_name", "status", "protocol_id", "workspace_id")
            .order_by("-id")
        ):
            nodes.append({
                "id": j.id,
                "job_name": j.job_name,
                "status": j.status,
                "protocol_id": j.protocol_id,
                "workspace_id": getattr(j, "workspace_id", None),
            })

    return {
        "root": root_job.id,
        "nodes": nodes,
        "edges": [{"from": s, "to": t} for (s, t) in edges],
        "truncated": len(nodes_ids) >= max_nodes,
        "max_nodes": max_nodes,
    }


def job_seed_summaries(user, ids):
    """Accessible jobs as {id, job_name, status} in the given id order."""
    if not ids:
        return []
    rows = {
        j["id"]: j
        for j in Job.objects.filter(accessible_job_q(user), id__in=list(ids)).values("id", "job_name", "status")
    }
    return [rows[i] for i in ids if i in rows]


def rename_job(job, new_name, dry_run=False):
    """Rename job files/dirs then job_name. Returns result dict from rename helper."""
    from .files import rename_job_files
    result = rename_job_files(job, new_name, dry_run=dry_run)
    if result.get("conflicts"):
        return result
    if not dry_run:
        old = job.job_name or ""
        job.job_name = new_name
        try:
            job.save(update_fields=["job_name"])
        except Exception:
            job.save()
        audit_operation(job, "Renamed job", comment="{} -> {}".format(old, new_name))
    return result


def can_mutate(user, obj):
    """Write permission matching QueueDB._OwnerModel.check_owner(read_only=False)."""
    if obj is None:
        return False
    if getattr(user, "is_staff", False):
        return True
    if getattr(obj, "user_id", None) is None:
        return False
    delegate = delegate_for(user)
    return obj.user_id == getattr(delegate, "id", None)


def get_visible_protocol(user, pk):
    """Own or public protocol (list/detail/clone)."""
    return visible_protocols(user).filter(pk=pk).first()


def get_owned_protocol(user, pk):
    """Protocol the user may mutate (own or staff). Public protocols are read-only."""
    proto = ProtocolList.objects.filter(pk=pk).first()
    if proto is None or not can_mutate(user, proto):
        return None
    return proto


def get_visible_reference(user, pk):
    return visible_references(user).filter(pk=pk).first()


def get_owned_reference(user, pk):
    """Reference the user may mutate (own or staff). Public references are read-only."""
    ref = Reference.objects.filter(pk=pk).first()
    if ref is None or not can_mutate(user, ref):
        return None
    return ref


def get_owned_workspace(user, pk):
    ws = Workspace.objects.filter(pk=pk).first()
    if ws is None or not can_mutate(user, ws):
        return None
    return ws


def get_visible_environment(user, pk):
    return visible_environments(user).filter(pk=pk).first()


def get_owned_environment(user, pk):
    env = VirtualEnvironment.objects.filter(pk=pk).first()
    if env is None or not can_mutate(user, env):
        return None
    return env


def search_workspaces(user, q):
    qs = visible_workspaces(user)
    q = (q or "").strip()
    if q:
        try:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(id=int(q)))
        except ValueError:
            qs = qs.filter(Q(name__icontains=q) | Q(description__icontains=q))
    return qs.order_by("-id")


def search_environments(user, q):
    qs = visible_environments(user)
    q = (q or "").strip()
    if q:
        try:
            qs = qs.filter(
                Q(name__icontains=q) | Q(ve_type__icontains=q) | Q(value__icontains=q) | Q(id=int(q))
            )
        except ValueError:
            qs = qs.filter(Q(name__icontains=q) | Q(ve_type__icontains=q) | Q(value__icontains=q))
    return qs.order_by("-id")


def search_protocols(user, q, ordering="-id"):
    qs = visible_protocols(user)
    q = (q or "").strip()
    if q:
        tokens = split_tokens(q)
        text_q = None
        for token in tokens:
            cond = Q(name__icontains=token) | Q(description__icontains=token)
            text_q = cond if text_q is None else (text_q & cond)
        try:
            id_q = Q(id=int(q))
        except ValueError:
            id_q = None
        if text_q is not None and id_q is not None:
            qs = qs.filter(text_q | id_q)
        elif text_q is not None:
            qs = qs.filter(text_q)
        elif id_q is not None:
            qs = qs.filter(id_q)
    allowed = {"name", "-name", "id", "-id"}
    if ordering in allowed:
        qs = qs.order_by(ordering)
    else:
        qs = qs.order_by("-id")
    return qs


def search_references(user, q):
    qs = visible_references(user)
    q = (q or "").strip()
    if q:
        try:
            qs = qs.filter(Q(name__icontains=q) | Q(path__icontains=q) | Q(id=int(q)))
        except ValueError:
            qs = qs.filter(Q(name__icontains=q) | Q(path__icontains=q))
    return qs


def protocol_steps(protocol):
    if protocol is None:
        return Step.objects.none()
    return Step.objects.filter(parent=protocol).select_related("env").order_by("step_order", "id")


class JobActionError(ValueError):
    """User-facing job mutation failure."""


def mark_job_wrong(job):
    if job.locked:
        raise JobActionError("This job is locked, please unlock first.")
    if job.status != JobStatus.FINISHED:
        raise JobActionError("Only a finished job can be marked failed.")
    job.set_status(JobStatus.WRONG)
    audit_operation(job, "Marked wrong")
    return job


def resume_job_from(job, rollback_to=None):
    """Queue the job from a step index. None keeps the current (failed) step."""
    if job.locked:
        raise JobActionError("This job is locked, please unlock first.")
    n_steps = protocol_steps(job.protocol).count()
    max_step = max(0, n_steps - 1) if n_steps else 0
    current = job.resume or 0
    if rollback_to is None:
        target = min(max(current, 0), max_step) if n_steps else max(current, 0)
    else:
        target = min(max(int(rollback_to), 0), max_step) if n_steps else max(int(rollback_to), 0)
        if target > current:
            target = current
    job.resume_job(target)
    return job


def protocol_step_counts(protocol_ids):
    """Map protocol_id -> step count for the given ids."""
    ids = [i for i in (protocol_ids or []) if i]
    if not ids:
        return {}
    from django.db.models import Count

    return dict(
        Step.objects.filter(parent_id__in=ids)
        .values("parent_id")
        .annotate(n=Count("id"))
        .values_list("parent_id", "n")
    )


def visible_shortcuts(user, protocol=None, active_only=False):
    """Shortcuts the user can see: own or public, optionally scoped to a protocol."""
    delegate = delegate_for(user)
    qs = ProtocolShortcut.objects.filter(Q(user=delegate) | Q(user=None))
    if protocol is not None:
        qs = qs.filter(protocol=protocol)
    if active_only:
        qs = qs.filter(active=1)
    return qs.order_by("order", "id")


def get_owned_shortcut(user, pk):
    sc = ProtocolShortcut.objects.filter(pk=pk).first()
    if sc is None or not can_mutate(user, sc):
        return None
    return sc


def create_shortcut(user, *, protocol, label, href_template, params_template="", order=0, active=1):
    return ProtocolShortcut.objects.create(
        user=delegate_for(user),
        protocol=protocol,
        label=label,
        href_template=href_template,
        params_template=params_template or "",
        order=order,
        active=1 if active else 0,
    )


def clone_shortcuts(src_protocol, dest_protocol, user):
    dest_user = delegate_for(user)
    for sc in ProtocolShortcut.objects.filter(protocol=src_protocol).order_by("order", "id"):
        ProtocolShortcut.objects.create(
            user=dest_user,
            protocol=dest_protocol,
            label=sc.label,
            href_template=sc.href_template,
            params_template=sc.params_template or "",
            order=sc.order,
            active=sc.active,
        )


def resolve_shortcut_href(sc, job):
    href = (sc.href_template or "").replace("{id}", str(job.id))
    extra = (sc.params_template or "").replace("{id}", str(job.id)).strip()
    if extra:
        if extra.startswith("?") or extra.startswith("&") or extra.startswith("/"):
            href += extra
        else:
            href += ("&" if "?" in href else "?") + extra
    return href


def shortcuts_for_jobs(user, jobs):
    """
    Attach a list of {label, href} on each job from shared + protocol shortcuts.

    Protocol-specific entries win on the same label+href (ui2 mergeShortcutsForJob).
    """
    jobs = list(jobs or [])
    proto_ids = {j.protocol_id for j in jobs if getattr(j, "protocol_id", None)}
    delegate = delegate_for(user)
    qs = ProtocolShortcut.objects.filter(Q(user=delegate) | Q(user=None), active=1)
    if proto_ids:
        qs = qs.filter(Q(protocol_id__in=list(proto_ids)) | Q(protocol_id=None))
    else:
        qs = qs.filter(protocol_id=None)
    shared = []
    by_proto = {}
    for sc in qs.order_by("order", "id"):
        item = sc
        if sc.protocol_id is None:
            shared.append(item)
        else:
            by_proto.setdefault(sc.protocol_id, []).append(item)
    for job in jobs:
        merged = {}
        for sc in shared:
            merged[(sc.label, sc.href_template)] = sc
        for sc in by_proto.get(job.protocol_id, []):
            merged[(sc.label, sc.href_template)] = sc
        items = sorted(merged.values(), key=lambda s: (s.order or 0, s.label or ""))
        job.ui3_shortcuts = [{"label": sc.label, "href": resolve_shortcut_href(sc, job)} for sc in items]
    return jobs


def shortcut_presets():
    """Plugin-advertised shortcut templates for the protocol picker."""
    from django.utils.safestring import mark_safe

    from ui3 import plugins

    out = []
    for item in plugins.shortcut_presets():
        payload = {
            "label": item["label"],
            "href_template": item["href_template"],
            "params_template": item.get("params_template") or "",
            "active": "1",
        }
        row = dict(item)
        row["hx_vals"] = mark_safe(json.dumps(payload))
        out.append(row)
    return out


def compute_step_hash(software, parameter):
    payload = "{} {}".format(software or "", (parameter or "").strip())
    return hashlib.md5(payload.encode()).hexdigest()


def create_step(protocol, software, parameter, step_order, env=None, user=None, version_check=""):
    return Step.objects.create(
        parent=protocol,
        software=software,
        parameter=parameter or "",
        step_order=step_order,
        env=env,
        hash=compute_step_hash(software, parameter),
        user=user,
        version_check=version_check or "",
    )


def swap_step_order(step, direction):
    siblings = list(protocol_steps(step.parent))
    idx = next((i for i, item in enumerate(siblings) if item.id == step.id), None)
    if idx is None:
        return False
    target = idx - 1 if direction == "up" else idx + 1
    if target < 0 or target >= len(siblings):
        return False
    other = siblings[target]
    step.step_order, other.step_order = other.step_order, step.step_order
    step.save(update_fields=["step_order"])
    other.save(update_fields=["step_order"])
    return True


def clone_protocol(src, name, user, copy_description=True, copy_shortcuts=False):
    dest = ProtocolList.objects.create(
        name=name,
        description=(src.description if copy_description else None),
        user=user,
    )
    for step in protocol_steps(src):
        create_step(
            dest,
            step.software,
            step.parameter,
            step.step_order,
            env=step.env,
            user=user,
        )
    if copy_shortcuts:
        clone_shortcuts(src, dest, user)
    return dest


PROTOCOL_WILDCARD_RE = re.compile(r"\{\{(.*?)\}\}", re.IGNORECASE | re.DOTALL)
MAX_PROTOCOL_JSON_BYTES = 1_000_000


class ProtocolImportError(ValueError):
    """User-facing protocol JSON import failure."""


def protocol_json_filename(name):
    raw = (name or "protocol").strip() or "protocol"
    safe = re.sub(r'[\x00-\x1f\\/:*?"<>|]+', "_", raw).strip(" .") or "protocol"
    if len(safe) > 180:
        safe = safe[:180].rstrip(" .") or "protocol"
    return safe + ".json"


def protocol_json_payload(protocol, user=None):
    """Legacy-compatible protocol JSON (name, description, ver, step, reference)."""
    steps_out = []
    for step in protocol_steps(protocol):
        steps_out.append(
            {
                "software": step.software,
                "parameter": step.parameter,
                "hash": step.hash or compute_step_hash(step.software, step.parameter),
                "step_order": step.step_order,
                "version_check": step.version_check or "",
            }
        )
    refs = {}
    if user is not None:
        known = {r.name: (r.description or "") for r in visible_references(user)}
        for step in steps_out:
            for token in PROTOCOL_WILDCARD_RE.findall(step.get("parameter") or ""):
                ref_name = (token or "").split(":")[0].strip()
                if ref_name and ref_name in known and ref_name not in refs:
                    refs[ref_name] = known[ref_name]
    return {
        "name": protocol.name,
        "description": protocol.description,
        "ver": protocol.ver,
        "step": steps_out,
        "reference": refs,
    }


def protocol_json_text(protocol, user=None):
    return json.dumps(protocol_json_payload(protocol, user), indent=4, sort_keys=True)


def _reference_entries(raw_refs):
    entries = []
    if isinstance(raw_refs, dict):
        for name, description in raw_refs.items():
            name = str(name or "").strip()
            if name:
                entries.append((name, "" if description is None else str(description)))
    elif isinstance(raw_refs, list):
        for item in raw_refs:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                if name:
                    entries.append((name, str(item.get("description") or "")))
            elif isinstance(item, str) and item.strip():
                entries.append((item.strip(), ""))
    return entries


def import_protocol_from_json(user, payload):
    """
    Create an owned protocol from legacy export JSON.

    Returns (protocol, missing_reference_names).
    """
    if not isinstance(payload, dict):
        raise ProtocolImportError("Invalid protocol JSON.")
    name = (payload.get("name") or "").strip()
    if not name:
        raise ProtocolImportError("Protocol name is required.")
    if len(name) > 500:
        raise ProtocolImportError("Protocol name is too long.")
    owner = delegate_for(user)
    if ProtocolList.objects.filter(name=name, user=owner).exists():
        raise ProtocolImportError("A protocol named '{}' already exists.".format(name))
    steps = payload.get("step") or []
    if not isinstance(steps, list):
        raise ProtocolImportError("Protocol steps must be a list.")
    description = payload.get("description")
    if description is not None:
        description = str(description).strip() or None
    with transaction.atomic():
        proto = ProtocolList.objects.create(name=name, description=description, user=owner)
        for index, raw in enumerate(steps, start=1):
            if not isinstance(raw, dict):
                continue
            software = (raw.get("software") or "").strip()
            if not software:
                continue
            parameter = raw.get("parameter") or ""
            try:
                order = int(raw.get("step_order") or index)
            except (TypeError, ValueError):
                order = index
            create_step(
                proto,
                software,
                parameter,
                order,
                user=owner,
                version_check=raw.get("version_check") or "",
            )
    known = set(visible_references(user).values_list("name", flat=True))
    missing = [name for name, _desc in _reference_entries(payload.get("reference")) if name not in known]
    return proto, missing


def import_protocol_from_upload(user, upload):
    if upload is None:
        raise ProtocolImportError("Choose a protocol JSON file.")
    size = getattr(upload, "size", None) or 0
    if size > MAX_PROTOCOL_JSON_BYTES:
        raise ProtocolImportError("File is too large (max 1 MB).")
    raw = upload.read()
    if len(raw) > MAX_PROTOCOL_JSON_BYTES:
        raise ProtocolImportError("File is too large (max 1 MB).")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ProtocolImportError("File is not valid UTF-8.")
    except json.JSONDecodeError:
        raise ProtocolImportError("Invalid protocol JSON.")
    return import_protocol_from_json(user, payload)


def running_job_count(user):
    return owned_jobs(user).filter(status=JobStatus.RUNNING).count()


def job_has_archives(job):
    try:
        return FileArchive.objects.filter(job=job).count()
    except Exception:
        return 0


def maybe_delete_job_files(job):
    try:
        from .files import delete_job_file_tree
        delete_job_file_tree(job)
    except Exception:
        pass


class JobMigrateError(ValueError):
    """User-facing job account migration failure."""


def find_user(raw):
    from django.contrib.auth.models import User

    text = (raw or "").strip()
    if not text:
        return None
    if text.lower().startswith("id:"):
        pk = text[3:].strip()
        if not pk.isascii() or not pk.isdigit():
            return None
        return User.objects.filter(pk=int(pk)).first()
    exact = list(User.objects.filter(username=text)[:2])
    if len(exact) == 1:
        return exact[0]
    iexact = list(User.objects.filter(username__iexact=text)[:3])
    if len(iexact) == 1:
        return iexact[0]
    if len(iexact) > 1:
        raise JobMigrateError("Username matches more than one account.")
    if text.isascii() and text.isdigit():
        return User.objects.filter(pk=int(text)).first()
    return None


def parse_migrate_job_ids(raw):
    """
    Parse the migrate Job IDs field.

    Blank means all source jobs (None). Any non-integer token is an error.
    """
    text = (raw or "").strip()
    if not text:
        return None
    ids = []
    for token in text.replace(",", " ").split():
        try:
            ids.append(int(token))
        except (TypeError, ValueError):
            raise JobMigrateError("Job IDs must be integers.")
    if not ids:
        raise JobMigrateError("Job IDs must be integers.")
    return ids


def search_migrate_jobs(from_user, q, limit=10):
    """Staff job picker: name tokens and/or integer ids, optionally scoped to one owner."""
    text = (q or "").strip()
    if not text:
        return []
    try:
        limit = max(1, min(int(limit or 10), 25))
    except (TypeError, ValueError):
        limit = 10
    qs = Job.objects.select_related("user").order_by("-pk")
    if from_user is not None:
        qs = qs.filter(user=from_user)
    q_ids = []
    q_names = []
    for token in split_tokens(text):
        if token.isdigit():
            q_ids.append(int(token))
        else:
            q_names.append(token)
    clauses = []
    if q_ids:
        clauses.append(Q(pk__in=q_ids))
    if q_names:
        clauses.append(reduce(operator.and_, [Q(job_name__icontains=t) for t in q_names]))
    if not clauses:
        return []
    qs = qs.filter(reduce(operator.or_, clauses) if len(clauses) > 1 else clauses[0])
    rows = []
    for job in qs[:limit]:
        rows.append(
            {
                "id": job.id,
                "job_name": job.job_name or "",
                "status": job.status,
                "username": getattr(job.user, "username", "") or "",
            }
        )
    return rows


def _migrate_result_key(job):
    from .files import job_result_relpath

    rel = job_result_relpath(job)
    if not rel:
        return ""
    return rel.replace("\\", "/")


def _result_nested_under(job, other):
    child = _migrate_result_key(job)
    parent = _migrate_result_key(other)
    if not child or not parent:
        return False
    if (job.run_dir or "").strip() != (other.run_dir or "").strip():
        return False
    return child != parent and child.startswith(parent + "/")


def _jobs_for_migrate(from_user, job_ids):
    qs = Job.objects.filter(user=from_user)
    if not job_ids:
        return list(qs.select_related("workspace", "protocol", "parent_job").order_by("id")), []
    wanted = [int(i) for i in job_ids]
    found = set(qs.filter(pk__in=wanted).values_list("id", flat=True))
    visited = set(found)
    frontier = list(found)
    while frontier:
        kids = list(
            Job.objects.filter(parent_job_id__in=frontier)
            .exclude(pk__in=visited)
            .values_list("id", "user_id")
        )
        if not kids:
            break
        frontier = []
        for kid_id, uid in kids:
            visited.add(kid_id)
            frontier.append(kid_id)
            if uid == from_user.id:
                found.add(kid_id)
    missing = [i for i in wanted if i not in found]
    jobs = list(
        Job.objects.filter(pk__in=found)
        .select_related("workspace", "protocol", "parent_job")
        .order_by("id")
    )
    return jobs, missing


def _file_plan_for_job(job, to_user, move_files):
    if not move_files:
        return "left", "left in place"
    from .files import job_result_move_paths

    _src, _dest, reason = job_result_move_paths(job, to_user)
    if reason == "none":
        return "none", "no result folder"
    if reason == "missing":
        return "skip", "Source folder missing."
    if reason == "collision":
        return "skip", "Destination folder already exists."
    if reason == "invalid":
        return "skip", "Result path is not safe to move."
    if reason:
        return "skip", reason
    return "move", "would move"


def _migrate_gate_reason(job):
    if job.locked:
        return "Job is locked."
    if job.status == JobStatus.RUNNING:
        return "Job is running."
    if job.status == JobStatus.RESOURCELOCK:
        return "Job is waiting for resources."
    return None


def _migrate_history_peers(job, from_user, moving_ids):
    peers = []
    seen = set()
    for hid in parent_job_ids(job):
        if hid == job.id or hid in moving_ids or hid in seen:
            continue
        if Job.objects.filter(pk=hid, user=from_user).exists():
            seen.add(hid)
            peers.append(hid)
    needle_h = "{{{{History:{}-".format(job.id)
    needle_ca = "{{{{CrossAccess:{}-{}-".format(from_user.id, job.id)
    inbound = (
        Job.objects.filter(user=from_user)
        .exclude(pk__in=list(moving_ids) + [job.id])
        .filter(
            Q(parameter__icontains=needle_h)
            | Q(input_file__icontains=needle_h)
            | Q(parameter__icontains=needle_ca)
            | Q(input_file__icontains=needle_ca)
        )
        .values_list("id", flat=True)[:8]
    )
    for hid in inbound:
        if hid not in seen:
            seen.add(hid)
            peers.append(hid)
    return peers


def _mark_migrate_skip(rec, skipped_ids, moving_ids, detail):
    rec["skip"] = detail
    skipped_ids.add(rec["job"].id)
    moving_ids.discard(rec["job"].id)


def migrate_jobs(from_user, to_user, job_ids=None, *, move_files=True, dry_run=False):
    """
    Reassign jobs from one account to another.

    Moves result folders from {run_dir}/{from_id}/{result} to
    {run_dir}/{to_id}/{result}. Nested array folders are moved with the
    shallowest parent in the batch. Running, resource-locked, and locked
    jobs are skipped. Missing source folders skip the DB update when
    move_files is on. Same-owner History links outside the moving set
    skip. Workspaces the destination does not own are cleared. Protocols
    stay attached. Historical Audition rows keep their original user.
    """
    if from_user is None or to_user is None:
        raise JobMigrateError("Choose a source and destination account.")
    if from_user.id == to_user.id:
        raise JobMigrateError("Source and destination must be different accounts.")
    if not getattr(to_user, "is_active", True):
        raise JobMigrateError("Destination account is inactive.")
    jobs, missing = _jobs_for_migrate(from_user, job_ids)
    rows = []
    for pk in missing:
        rows.append({"job_id": pk, "job_name": "", "action": "skip", "detail": "Not owned by the source account."})
    from .files import move_job_result_folder

    batch_ids = {job.id for job in jobs}
    jobs.sort(key=lambda j: (_migrate_result_key(j).count("/"), j.id))
    covering = {}
    for job in jobs:
        covers = [other.id for other in jobs if other.id != job.id and _result_nested_under(job, other)]
        parent = job.parent_job
        if parent is not None and parent.id not in batch_ids and _result_nested_under(job, parent):
            covers.append(parent.id)
        covering[job.id] = covers

    skipped_ids = set()
    classified = []
    for job in jobs:
        rec = {"job": job, "skip": None, "files": "", "notes": [], "plan": None}
        gate = _migrate_gate_reason(job)
        if gate:
            rec["skip"] = gate
            skipped_ids.add(job.id)
            classified.append(rec)
            continue
        nested_covers = covering.get(job.id) or []
        external_cover = next((cid for cid in nested_covers if cid not in batch_ids), None)
        blocked_cover = next((cid for cid in nested_covers if cid in skipped_ids), None)
        if external_cover is not None:
            rec["skip"] = "Nested under job #{} which is not in this migrate.".format(external_cover)
            skipped_ids.add(job.id)
            classified.append(rec)
            continue
        if blocked_cover is not None:
            rec["skip"] = "Nested under job #{} which is not moving.".format(blocked_cover)
            skipped_ids.add(job.id)
            classified.append(rec)
            continue
        covered_by = next((cid for cid in nested_covers if cid in batch_ids), None)
        workspace = job.workspace
        if workspace is not None and workspace.user_id != to_user.id:
            rec["notes"].append("workspace cleared")
        if covered_by is not None and move_files:
            rec["files"] = "covered by job #{}".format(covered_by)
            rec["plan"] = "covered"
        else:
            plan, file_detail = _file_plan_for_job(job, to_user, move_files)
            if plan == "skip":
                rec["skip"] = file_detail
                skipped_ids.add(job.id)
                classified.append(rec)
                continue
            rec["files"] = file_detail
            rec["plan"] = plan
        classified.append(rec)

    moving_ids = {rec["job"].id for rec in classified if not rec["skip"]}
    for rec in classified:
        if rec["skip"]:
            continue
        peers = _migrate_history_peers(rec["job"], from_user, moving_ids)
        if peers:
            shown = ", #".join(str(p) for p in peers[:6])
            _mark_migrate_skip(rec, skipped_ids, moving_ids, "History links job #{} which are not moving.".format(shown))
    for rec in classified:
        if rec["skip"]:
            continue
        blocked = next((cid for cid in (covering.get(rec["job"].id) or []) if cid in skipped_ids), None)
        if blocked is not None:
            _mark_migrate_skip(
                rec,
                skipped_ids,
                moving_ids,
                "Nested under job #{} which is not moving.".format(blocked),
            )

    migrated_ids = []
    for rec in classified:
        job = rec["job"]
        row = {
            "job_id": job.id,
            "job_name": job.job_name or "",
            "action": "skip" if rec["skip"] else "move",
            "detail": rec["skip"] or "",
            "files": rec["files"],
        }
        if rec["skip"]:
            rows.append(row)
            continue
        notes = rec["notes"]
        if dry_run:
            row["action"] = "preview"
            row["detail"] = "; ".join(notes) if notes else "Would reassign owner."
            rows.append(row)
            continue
        try:
            with transaction.atomic():
                fresh = (
                    Job.objects.select_for_update()
                    .select_related("workspace", "protocol")
                    .get(pk=job.id)
                )
                gate = _migrate_gate_reason(fresh)
                if gate:
                    row["action"] = "skip"
                    row["detail"] = gate
                    rows.append(row)
                    skipped_ids.add(job.id)
                    continue
                if fresh.user_id != from_user.id:
                    row["action"] = "skip"
                    row["detail"] = "Owner changed before migrate finished."
                    rows.append(row)
                    skipped_ids.add(job.id)
                    continue
                if rec["plan"] == "move" and move_files:
                    try:
                        moved = move_job_result_folder(fresh, to_user)
                    except Exception:
                        row["action"] = "error"
                        row["detail"] = "Could not move result folder."
                        rows.append(row)
                        skipped_ids.add(job.id)
                        continue
                    if moved in ("collision", "invalid", "missing"):
                        row["action"] = "skip"
                        if moved == "collision":
                            row["detail"] = "Destination folder already exists."
                        elif moved == "missing":
                            row["detail"] = "Source folder missing."
                        else:
                            row["detail"] = "Result path is not safe to move."
                        rows.append(row)
                        skipped_ids.add(job.id)
                        continue
                    row["files"] = "moved" if moved == "moved" else ("no result folder" if moved == "none" else moved)
                workspace = fresh.workspace
                fresh.user = to_user
                if workspace is not None and workspace.user_id != to_user.id:
                    fresh.workspace = None
                fresh.save(update_fields=["user", "workspace"])
                FileArchive.objects.filter(job=fresh).update(user=to_user)
                Audition.objects.create(
                    operation="Migrated",
                    related_job=fresh,
                    job_name=fresh.job_name or "",
                    job_ver=fresh.version,
                    prev_par=fresh.parameter or "",
                    new_par=fresh.parameter or "",
                    prev_input=fresh.input_file or "",
                    current_input=fresh.input_file or "",
                    protocol=(fresh.protocol.name if fresh.protocol_id else ""),
                    protocol_ver=fresh.protocol_ver or "",
                    resume_point=fresh.resume,
                    user=to_user,
                    comments="from {} to {}".format(from_user.username, to_user.username),
                )
        except Job.DoesNotExist:
            row["action"] = "skip"
            row["detail"] = "Not owned by the source account."
            rows.append(row)
            continue
        migrated_ids.append(job.id)
        row["action"] = "moved"
        row["detail"] = "; ".join(notes) if notes else "Owner updated."
        rows.append(row)
    return {
        "from_user": from_user,
        "to_user": to_user,
        "dry_run": dry_run,
        "rows": rows,
        "moved": len(migrated_ids),
        "skipped": sum(1 for r in rows if r["action"] == "skip"),
        "errors": sum(1 for r in rows if r["action"] == "error"),
        "previews": sum(1 for r in rows if r["action"] == "preview"),
    }


AUTOCOMPLETE_TOKENS = (
    "InputFile",
    "InputFile:",
    "Job",
    "JobName",
    "LastOutput",
    "LastOutput:",
    "Output:",
    "AllOutputBefore",
    "Suffix",
    "Suffix:",
    "ThreadN",
    "Workspace",
    "UserBin",
    "History",
)


def autocomplete_tokens(user):
    names = []
    try:
        names = [n for n in visible_references(user).values_list("name", flat=True) if n]
    except Exception:
        names = []
    return sorted(set(list(AUTOCOMPLETE_TOKENS) + names), key=lambda s: s.lower())


BUILTIN_PARAM_TOKENS = frozenset(
    {
        "InputFile",
        "LastOutput",
        "Job",
        "ThreadN",
        "Output",
        "Uploaded",
        "Suffix",
        "Workspace",
        "UserBin",
        "JobName",
    }
)


def protocol_usable(user, protocol):
    """True if user may create jobs with this protocol (own, public, or staff)."""
    if protocol is None:
        return False
    if getattr(user, "is_staff", False):
        return True
    if protocol.user_id is None:
        return True
    delegate = delegate_for(user)
    return protocol.user_id == getattr(delegate, "id", None)


def get_usable_protocol(user, pk):
    if pk is None:
        return None
    protocol = ProtocolList.objects.filter(pk=pk).first()
    if protocol is None or not protocol_usable(user, protocol):
        return None
    return protocol


def parameter_scaffold(protocol, user=None):
    """
    Build semicolon-separated Key= scaffold from protocol step {{Key}} tokens.

    Mirrors CreateJobPage.tsx: exclude builtin tokens and reference names.
    """
    if protocol is None:
        return ""
    predef = set(BUILTIN_PARAM_TOKENS)
    try:
        for name in visible_references(user).values_list("name", flat=True) if user is not None else []:
            if name:
                predef.add(name)
    except Exception:
        pass
    if user is None:
        try:
            for name in Reference.objects.filter(user=None).values_list("name", flat=True):
                if name:
                    predef.add(name)
        except Exception:
            pass

    user_keys = []
    seen = set()
    token_re = re.compile(r"\{\{(.*?)\}\}", re.IGNORECASE | re.DOTALL)
    for step in protocol_steps(protocol):
        for match in token_re.finditer(step.parameter or ""):
            raw = match.group(1) or ""
            name = str(raw.split(":")[0])
            if "{{" in name and "}}" not in name:
                name += "}}"
            if not name or ";" in name:
                continue
            if name in predef or name in seen:
                continue
            seen.add(name)
            user_keys.append(name)
    if not user_keys:
        return ""
    return "".join("{}=;".format(k) for k in user_keys)


def create_job(
    user,
    *,
    job_name,
    protocol,
    parameter="",
    input_file="",
    workspace=None,
    comments="",
    is_gpu_job=0,
    array_setting=None,
    slave=None,
):
    run_dir = ""
    try:
        from worker.bases import get_config

        run_dir = get_config("env", "workspace") or ""
    except Exception:
        run_dir = ""
    kwargs = {
        "user": user,
        "job_name": job_name,
        "protocol": protocol,
        "protocol_ver": getattr(protocol, "ver", None) or "",
        "parameter": parameter or "",
        "input_file": input_file or "",
        "workspace": workspace,
        "comments": comments or "",
        "is_gpu_job": 1 if is_gpu_job else 0,
        "run_dir": run_dir,
        "visibility": 1,
    }
    if array_setting is not None and str(array_setting).strip() != "":
        kwargs["array_setting"] = str(array_setting).strip()
    if slave is not None:
        kwargs["slave"] = slave
    return Job.objects.create(**kwargs)


def shared_search_jobs(user, q, limit=50):
    """Jobs owned by CrossAccess grantors matching q (id or name)."""
    from QueueDB.models import CrossAccess

    delegate = delegate_for(user)
    owner_ids = list(
        CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True)
    )
    if not owner_ids:
        return Job.objects.none()
    qs = Job.objects.filter(user_id__in=owner_ids)
    q = (q or "").strip()
    if q:
        if q.isdigit():
            qs = qs.filter(id=int(q))
        else:
            qs = qs.filter(job_name__icontains=q)
    return qs.order_by("-id")[:limit]


def create_jobs_batch(user, tsv_content, workspace=None):
    """
    Create jobs from TSV lines: protocol_id\\tjob_name\\tinput_file\\tparameter[\\tarray_setting][\\tis_gpu].

    Returns {"created": int, "errors": [{"line": int, "error": str}], "jobs": [Job, ...]}.
    """
    delegate = user
    errors = []
    jobs_to_create = []
    protocol_cache = {}
    staff = bool(getattr(user, "is_staff", False))
    lines = (tsv_content or "").splitlines()
    run_dir = ""
    try:
        from worker.bases import get_config

        run_dir = get_config("env", "workspace") or ""
    except Exception:
        run_dir = ""

    for idx, raw in enumerate(lines, start=1):
        line = (raw or "").strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) < 4:
            errors.append({"line": idx, "error": "expected at least 4 columns"})
            continue
        try:
            protocol_id = int(parts[0])
            job_name = parts[1]
            input_file = parts[2]
            parameter = parts[3]
            array_setting = parts[4] if len(parts) >= 5 and parts[4] != "" else None
            is_gpu_job = 0
            if len(parts) >= 6 and parts[5] != "":
                try:
                    is_gpu_job = int(parts[5])
                except Exception:
                    is_gpu_job = 0

            if protocol_id not in protocol_cache:
                proto = ProtocolList.objects.filter(id=protocol_id).first()
                if proto is None:
                    errors.append({"line": idx, "error": "protocol {} not found".format(protocol_id)})
                    protocol_cache[protocol_id] = None
                    continue
                if not staff and not protocol_usable(user, proto):
                    errors.append({"line": idx, "error": "no permission for protocol {}".format(protocol_id)})
                    protocol_cache[protocol_id] = None
                    continue
                protocol_cache[protocol_id] = proto
            proto = protocol_cache.get(protocol_id)
            if proto is None:
                continue

            jobs_to_create.append(
                Job(
                    protocol_id=protocol_id,
                    protocol_ver=getattr(proto, "ver", None) or "",
                    job_name=job_name,
                    input_file=input_file,
                    parameter=parameter,
                    run_dir=run_dir,
                    user=delegate,
                    is_gpu_job=is_gpu_job,
                    workspace=workspace,
                    array_setting=array_setting,
                    visibility=1,
                )
            )
        except Exception as exc:
            errors.append({"line": idx, "error": str(exc)})

    created_jobs = []
    if jobs_to_create:
        created_jobs = Job.objects.bulk_create(jobs_to_create)
    return {"created": len(created_jobs), "errors": errors, "jobs": created_jobs}


def create_array_job(user, *, protocol, job_name, job_list, workspace=None, is_gpu_job=0, slave=None):
    """
    Create virtual parent + child jobs from job_list lines:
    input_file\\tparameter[\\tis_gpu][\\tsuffix].

    Returns {"parent": Job, "created": int, "errors": [...]}.
    """
    import os

    run_dir = ""
    try:
        from worker.bases import get_config

        run_dir = get_config("env", "workspace") or ""
    except Exception:
        run_dir = ""

    parent_job = Job(
        protocol=protocol,
        protocol_ver=getattr(protocol, "ver", None) or "",
        job_name=job_name,
        parameter=";",
        run_dir=run_dir,
        user=user,
        input_file=";",
        is_gpu_job=1 if is_gpu_job else 0,
        workspace=workspace,
        slave=slave,
        array_setting="",
        is_executable=0,
        visibility=1,
    )
    parent_job.save()
    try:
        parent_job.result = "{}v{}".format(parent_job.id, int(parent_job.version or -1) + 1)
        parent_job.save(update_fields=["result"])
    except Exception:
        pass
    try:
        base_dir = str(run_dir or os.getcwd())
        out_dir = os.path.join(base_dir, str(getattr(user, "id", "")), str(parent_job.result or ""))
        if out_dir.strip():
            os.makedirs(out_dir, exist_ok=True)
    except Exception:
        pass

    errors = []
    children = []
    for i, raw in enumerate((job_list or "").splitlines()):
        line = (raw or "").strip()
        if not line:
            continue
        cols = line.split("\t")
        if not (2 <= len(cols) <= 4):
            errors.append({"line": i + 1, "error": "expected 2-4 tab-separated columns"})
            continue
        try:
            in_file = cols[0]
            param = cols[1]
            try:
                is_gpu = int(cols[2]) if len(cols) >= 3 and cols[2] != "" else 0
            except Exception:
                is_gpu = 0
            try:
                suffix = cols[3] if len(cols) >= 4 and cols[3] != "" else i
            except Exception:
                suffix = i
            children.append(
                Job(
                    parent_job=parent_job,
                    protocol=protocol,
                    protocol_ver=getattr(protocol, "ver", None) or "",
                    job_name="{}_{}".format(job_name, suffix),
                    input_file=in_file,
                    parameter=param,
                    run_dir=run_dir,
                    user=user,
                    is_gpu_job=is_gpu,
                    array_setting=str(i),
                    visibility=0,
                    workspace=workspace,
                    slave=slave,
                )
            )
        except Exception as exc:
            errors.append({"line": i + 1, "error": str(exc)})

    if children:
        Job.objects.bulk_create(children)

    return {"parent": parent_job, "created": len(children), "errors": errors}


ARCHIVE_STATUS = {
    0: "Queued",
    -1: "Working",
    1: "Done",
}

HISTORY_TOKEN_RE = re.compile(r"\{\{History:(\d+)-(.*?)\}\}", re.IGNORECASE | re.DOTALL)


def _stringify(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    if value is None:
        return ""
    return str(value)


def parse_parameter_map(raw):
    """Turn job.parameter into a key→value map plus a pretty string for diffs."""
    text = (raw or "").strip()
    if not text:
        return {}, ""
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            mapping = {str(k): _stringify(v) for k, v in parsed.items()}
            pretty = json.dumps(parsed, indent=2, sort_keys=True, default=str)
            return mapping, pretty
    except Exception:
        pass
    mapping = {}
    for part in re.split(r"[\n;,]+", text):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            key, value = part.split("=", 1)
            mapping[key.strip()] = value.strip()
        else:
            mapping[part] = ""
    return mapping, text


def split_input_files(raw):
    return [p.strip() for p in re.split(r"[\n;]+", raw or "") if p.strip()]


def unified_diff_lines(left_text, right_text, left_name, right_name):
    rows = []
    for line in difflib.unified_diff(
        (left_text or "").splitlines(),
        (right_text or "").splitlines(),
        fromfile=left_name,
        tofile=right_name,
        lineterm="",
    ):
        if line.startswith("+") and not line.startswith("+++"):
            cls = "diff-add"
        elif line.startswith("-") and not line.startswith("---"):
            cls = "diff-del"
        else:
            cls = "diff-ctx"
        rows.append({"text": line, "cls": cls})
    return rows


def compare_jobs(left, right):
    left_map, left_pretty = parse_parameter_map(getattr(left, "parameter", None))
    right_map, right_pretty = parse_parameter_map(getattr(right, "parameter", None))
    keys = sorted(set(left_map) | set(right_map))
    param_rows = []
    for key in keys:
        in_left = key in left_map
        in_right = key in right_map
        lv = left_map.get(key, "")
        rv = right_map.get(key, "")
        if in_left and in_right:
            state = "same" if lv == rv else "changed"
        elif in_left:
            state = "only-left"
        else:
            state = "only-right"
        param_rows.append({"key": key, "left": lv, "right": rv, "state": state})

    left_inputs = split_input_files(getattr(left, "input_file", None))
    right_inputs = split_input_files(getattr(right, "input_file", None))
    left_set, right_set = set(left_inputs), set(right_inputs)
    input_rows = []
    for path in sorted(left_set | right_set):
        in_left = path in left_set
        in_right = path in right_set
        if in_left and in_right:
            state = "same"
        elif in_left:
            state = "only-left"
        else:
            state = "only-right"
        input_rows.append({"path": path, "state": state})

    return {
        "param_rows": param_rows,
        "input_rows": input_rows,
        "param_diff": unified_diff_lines(
            left_pretty,
            right_pretty,
            "job #{} parameters".format(left.id),
            "job #{} parameters".format(right.id),
        ),
        "input_diff": unified_diff_lines(
            "\n".join(left_inputs),
            "\n".join(right_inputs),
            "job #{} inputs".format(left.id),
            "job #{} inputs".format(right.id),
        ),
        "same_protocol": getattr(left, "protocol_id", None) == getattr(right, "protocol_id", None),
    }


def protocol_dump_path(protocol_id, ver):
    from django.conf import settings

    base = getattr(settings, "BASE_DIR", "") or os.getcwd()
    dump_dir = os.path.realpath(os.path.join(base, "protocol_dumps"))
    try:
        safe_id = str(int(protocol_id))
    except (TypeError, ValueError):
        return None
    raw_ver = str(ver or "").replace("\\", "/")
    safe_ver = os.path.basename(raw_ver)
    if not safe_ver or safe_ver in (".", "..") or safe_ver != raw_ver or ".." in safe_ver:
        return None
    path = os.path.realpath(os.path.join(dump_dir, "{}_{}.txt".format(safe_id, safe_ver)))
    if path != dump_dir and not path.startswith(dump_dir + os.sep):
        return None
    return path


def load_protocol_dump(protocol_id, ver):
    path = protocol_dump_path(protocol_id, ver)
    if not path:
        return ""
    try:
        if os.path.isfile(path):
            with open(path, encoding="utf-8", errors="replace") as fh:
                return fh.read()
    except Exception:
        return ""
    return ""


def protocol_live_text(protocol):
    if protocol is None:
        return ""
    steps = []
    for step in protocol_steps(protocol):
        steps.append(
            {
                "software": step.software,
                "parameter": step.parameter,
                "hash": step.hash,
                "step_order": step.step_order,
            }
        )
    payload = {
        "name": protocol.name,
        "description": protocol.description or "",
        "ver": protocol.ver,
        "step": steps,
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


def job_protocol_text(job):
    dump = load_protocol_dump(job.protocol_id, job.protocol_ver)
    if dump:
        return dump, True
    note = "(no protocol dump for protocol {} version {})\n".format(
        job.protocol_id, job.protocol_ver or ""
    )
    if job.protocol_id and job.protocol_ver and job.protocol and job.protocol_ver == job.protocol.ver:
        return note + protocol_live_text(job.protocol), False
    extra = job.parameter or ""
    return note + extra, False


def current_protocol_text(protocol):
    if protocol is None:
        return "", False
    dump = load_protocol_dump(protocol.id, protocol.ver)
    if dump:
        return dump, True
    return protocol_live_text(protocol), False


def compare_job_to_protocol(job):
    left, left_from_dump = job_protocol_text(job)
    proto = job.protocol
    right, right_from_dump = current_protocol_text(proto)
    current_ver = getattr(proto, "ver", None) or ""
    job_ver = job.protocol_ver or ""
    dump_missing = not (left_from_dump and right_from_dump)
    diff = []
    if not dump_missing:
        diff = unified_diff_lines(
            left,
            right,
            "job #{} protocol {}".format(job.id, job_ver or "(unknown)"),
            "protocol {} {}".format(getattr(proto, "id", "?"), current_ver or "(current)"),
        )
    return {
        "job_ver": job_ver,
        "current_ver": current_ver,
        "versions_match": bool(job_ver) and job_ver == current_ver,
        "left_from_dump": left_from_dump,
        "right_from_dump": right_from_dump,
        "dump_missing": dump_missing,
        "diff": diff,
    }


def visible_archives(user):
    qs = FileArchive.objects.select_related("protocol", "job", "user").order_by("-create_time", "-pk")
    if getattr(user, "is_staff", False):
        return qs
    return qs.filter(user=delegate_for(user))


def archive_status_label(status):
    try:
        status = int(status)
    except (TypeError, ValueError):
        return str(status)
    return ARCHIVE_STATUS.get(status, str(status))


_SHARE_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_share_list(raw):
    """Comma-separated emails for FileArchive.shared_with (Drive share list)."""
    text = (raw or "").strip()
    if not text:
        return True
    parts = [p.strip() for p in text.split(",") if p.strip()]
    if not parts:
        return True
    return all(len(p) <= 254 and _SHARE_EMAIL_RE.match(p) for p in parts)


def create_file_archive(user, job, file_paths, *, raw_files="", description="", shared_with=""):
    if job is None or job.protocol_id is None:
        return None, "Job has no protocol; cannot archive."
    paths = [p for p in (file_paths or []) if p]
    if not paths:
        return None, "No files to archive."
    protocol_ver = job.protocol_ver or (job.protocol.ver if job.protocol else "") or ""
    if len(protocol_ver) > 33:
        return None, "Protocol version is too long to archive (max 33 characters)."
    archive = FileArchive.objects.create(
        user=delegate_for(user),
        protocol=job.protocol,
        protocol_ver=protocol_ver,
        inputs=job.input_file or "",
        files=json.dumps(paths),
        file_md5s="ph",
        job=job,
        raw_files=raw_files or "ph",
        description=description or "",
        shared_with=shared_with or "",
        archive_file="ph",
        status=0,
    )
    return archive, None


def profile_for(user):
    """Profile that owns folder overrides (the delegate's profile)."""
    delegate = delegate_for(user)
    return getattr(delegate, "queuedb_profile_related", None) or getattr(user, "queuedb_profile_related", None)


def folder_defaults_for(user):
    from .files import workspace_root_for

    profile = profile_for(user)
    root = workspace_root_for(delegate_for(user))
    upload = (getattr(profile, "upload_folder", None) or "").strip()
    archive = (getattr(profile, "archive_folder", None) or "").strip()
    return {
        "workspace": root,
        "uploads": upload or os.path.join(root, "uploads"),
        "bin": os.path.join(root, "bin"),
        "archives": archive or os.path.join(root, "archives"),
        "upload_folder": upload,
        "archive_folder": archive,
        "using_custom_uploads": bool(upload),
        "using_custom_archives": bool(archive),
    }


class UserManageError(ValueError):
    """User-facing staff account management failure."""


USER_STATES = ("all", "pending", "active", "staff", "deactivated")


def _require_staff_actor(actor):
    if actor is None or not getattr(actor, "is_staff", False):
        raise UserManageError("Staff access required.")


def user_is_pending(user):
    return user is not None and (not user.is_active) and user.last_login is None


def user_is_deactivated(user):
    return user is not None and (not user.is_active) and user.last_login is not None


def pending_user_count(actor):
    from django.contrib.auth.models import User

    _require_staff_actor(actor)
    return User.objects.filter(is_active=False, last_login__isnull=True).count()


def search_users(actor, q="", state="all"):
    from django.contrib.auth.models import User

    _require_staff_actor(actor)
    qs = User.objects.all()
    state = (state or "all").strip().lower()
    if state not in USER_STATES:
        state = "all"
    if state == "pending":
        qs = qs.filter(is_active=False, last_login__isnull=True)
    elif state == "deactivated":
        qs = qs.filter(is_active=False, last_login__isnull=False)
    elif state == "active":
        qs = qs.filter(is_active=True)
    elif state == "staff":
        qs = qs.filter(is_staff=True, is_active=True)
    text = (q or "").strip()
    if text:
        clauses = [
            Q(username__icontains=text),
            Q(email__icontains=text),
            Q(first_name__icontains=text),
            Q(last_name__icontains=text),
        ]
        if text.isdigit():
            clauses.append(Q(pk=int(text)))
        qs = qs.filter(reduce(operator.or_, clauses))
    return qs.order_by("is_active", "last_login", "-date_joined", "username")


def get_managed_user(pk):
    from django.contrib.auth.models import User

    try:
        return User.objects.get(pk=int(pk))
    except (TypeError, ValueError, User.DoesNotExist):
        return None


def _guard_user_change(actor, target):
    _require_staff_actor(actor)
    if target is None:
        raise UserManageError("Account not found.")
    if target.is_superuser and not getattr(actor, "is_superuser", False):
        raise UserManageError("Only a superuser can change a superuser account.")


def _lock_user(target):
    from django.contrib.auth.models import User

    try:
        return User.objects.select_for_update().get(pk=target.pk)
    except User.DoesNotExist:
        raise UserManageError("Account not found.")


def _locked_active_staff_count(exclude):
    from django.contrib.auth.models import User

    return (
        User.objects.select_for_update()
        .filter(is_staff=True, is_active=True)
        .exclude(pk=exclude.pk)
        .count()
    )


def set_user_active(actor, target, active):
    from django.utils import timezone

    _guard_user_change(actor, target)
    active = bool(active)
    with transaction.atomic():
        locked = _lock_user(target)
        _guard_user_change(actor, locked)
        if locked.pk == actor.pk and not active:
            raise UserManageError("You cannot deactivate your own account.")
        if locked.is_staff and locked.is_active and not active and _locked_active_staff_count(locked) < 1:
            raise UserManageError("Cannot deactivate the last active staff account.")
        if locked.is_active == active:
            return locked
        locked.is_active = active
        fields = ["is_active"]
        if not active and locked.last_login is None:
            locked.last_login = timezone.now()
            fields.append("last_login")
        locked.save(update_fields=fields)
        return locked


def set_user_staff(actor, target, staff):
    _guard_user_change(actor, target)
    staff = bool(staff)
    if not getattr(actor, "is_superuser", False):
        raise UserManageError("Only a superuser can change staff status.")
    with transaction.atomic():
        locked = _lock_user(target)
        _guard_user_change(actor, locked)
        if not getattr(actor, "is_superuser", False):
            raise UserManageError("Only a superuser can change staff status.")
        if locked.pk == actor.pk and not staff:
            raise UserManageError("You cannot remove staff from your own account.")
        if locked.is_staff and not staff and locked.is_active and _locked_active_staff_count(locked) < 1:
            raise UserManageError("Cannot remove staff from the last active staff account.")
        if locked.is_staff == staff:
            return locked
        locked.is_staff = staff
        locked.save(update_fields=["is_staff"])
        return locked


def create_managed_user(actor, *, username, password, password_2, email="", first_name="", last_name="", activate=True, staff=False):
    from django.contrib.auth.models import Group, User
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    _require_staff_actor(actor)
    if staff and not getattr(actor, "is_superuser", False):
        raise UserManageError("Only a superuser can grant staff.")
    username = (username or "").strip()
    email = (email or "").strip()
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    if not username:
        raise UserManageError("Username is required.")
    if len(username) > 150:
        raise UserManageError("Username is too long (max 150 characters).")
    if User.objects.filter(username=username).exists():
        raise UserManageError("That username is already taken.")
    if not password:
        raise UserManageError("Password is required.")
    if password != (password_2 or ""):
        raise UserManageError("Passwords do not match.")
    if email and len(email) > 254:
        raise UserManageError("Email is too long (max 254 characters).")
    if len(first_name) > 150 or len(last_name) > 150:
        raise UserManageError("Name is too long (max 150 characters).")
    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        is_active=bool(activate),
        is_staff=bool(staff),
    )
    try:
        user.full_clean(exclude=["password"])
    except ValidationError as exc:
        raise UserManageError("; ".join(msg for msgs in exc.message_dict.values() for msg in msgs))
    try:
        validate_password(password, user)
    except ValidationError as exc:
        raise UserManageError("; ".join(exc.messages))
    user.set_password(password)
    try:
        with transaction.atomic():
            user.save()
            group, _created = Group.objects.get_or_create(name="normal")
            user.groups.add(group)
    except IntegrityError:
        raise UserManageError("That username is already taken.")
    return user
