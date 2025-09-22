#!/usr/bin/env python
# -*- coding: utf-8 -*-

from rest_framework import viewsets, mixins, permissions, status
from rest_framework.views import APIView
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q, Count
import os
import re
import operator
from functools import reduce
from QueueDB.models import Job, ProtocolList, Protocol, Step, Reference, Workspace, Sample, Training, Prediction, VirtualEnvironment, Environment, FileArchive, JobStatus, Audition, Slave, CrossAccess, ProtocolShortcut
from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from .tools import delete_job_file_tree, list_job_files, open_job_file_response, delete_job_file_by_trace, build_preview_response
from worker.bases import get_config, get_job_log
from .serializers import (
    JobSerializer,
    CreateJobSerializer,
    ProtocolListSerializer,
    StepSerializer,
    ReferenceSerializer,
    WorkspaceSerializer,
    SampleSerializer,
    TrainingSerializer,
    PredictionSerializer,
    VirtualEnvironmentSerializer,
    ProtocolShortcutSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 200

    
def _audit_operation(job: Job, operation: str, comment: str = ""):
    """
    Create an Audition record for a job operation.

    Parameters
    ----------
    job : Job
        Target job.
    operation : str
        Description of the operation performed.
    comment : str, optional
        Additional information for the Audition.comments field.
    """
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
            protocol=job.protocol.name,
            protocol_ver=job.protocol_ver,
            resume_point=job.resume,
            user=job.user,
            comments=comment or None,
        ).save()
    except Exception:
        # audition should not block main operation
        pass


class IsOwnerOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_staff:
            return True
        if hasattr(obj, "check_owner"):
            return obj.check_owner(request.user, read_only=(request.method in permissions.SAFE_METHODS))
        return True


class JobViewSet(viewsets.ModelViewSet):
    queryset = Job.objects.all().order_by("-id")
    serializer_class = JobSerializer
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["status", "user", "workspace", "protocol", "visibility"]
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        """
        Scope jobs to the current user's delegate by default.

        Optional query param `scope` controls inclusion of shared jobs via CrossAccess:
          - scope=own (default): only current user's delegate jobs
          - scope=shared: jobs owned by users who granted read access to the delegate
          - scope=all: union of own and shared
        """
        delegate = getattr(getattr(self.request.user, "queuedb_profile_related", None), "delegate", self.request.user)
        scope = (self.request.query_params.get("scope", "own") or "own").lower()
        if scope in ("shared", "all"):
            owner_ids = list(CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True))
        else:
            owner_ids = []
        if scope == "shared":
            base_qs = Job.objects.filter(user_id__in=owner_ids)
        elif scope == "all":
            base_qs = Job.objects.filter(Q(user=delegate) | Q(user_id__in=owner_ids))
        else:
            base_qs = Job.objects.filter(user=delegate)
        return base_qs.order_by("-id")

    def get_serializer_class(self):
        if self.action in ["create"]:
            return CreateJobSerializer
        return super().get_serializer_class()

    @action(detail=False, methods=["get"], url_path="status-choices", permission_classes=[permissions.IsAuthenticated])
    def status_choices(self, request):
        """
        GET /jobs/status-choices/

        Returns canonical job status choices as defined in QueueDB.models.JobStatus.

        Returns
        -------
        list[dict]
            Each item has fields: {"value": int, "label": str}.
        """
        return Response([
            {"value": int(v), "label": str(l)} for (v, l) in JobStatus.choices
        ])

    @action(detail=False, methods=["post"], url_path="batch", permission_classes=[permissions.IsAuthenticated])
    def create_batch(self, request):
        """
        POST /jobs/batch/

        create multiple jobs from a tsv payload or uploaded file.

        request
        -------
        - multipart/form-data: file: <tsv file>, workspace: optional workspace id
        - application/json: { "tsv": "<lines>", "workspace": <optional workspace id> }

        each line: protocol_id\tjob_name\tinput_file\tparameter[\tarray_setting][\tis_gpu]

        returns
        -------
        { "created": int, "errors": [ {"line": int, "error": str} ] }
        """
        delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
        tsv_content = ""
        if hasattr(request, "FILES") and "file" in request.FILES:
            try:
                uploaded = request.FILES["file"]
                data = uploaded.read()
                if isinstance(data, bytes):
                    tsv_content = data.decode("utf-8", errors="ignore")
                else:
                    tsv_content = str(data)
            except Exception:
                return Response({"detail": "failed to read uploaded file"}, status=status.HTTP_400_BAD_REQUEST)
        else:
            tsv_content = str(request.data.get("tsv", "") or "")
        if not tsv_content.strip():
            return Response({"detail": "no tsv provided"}, status=status.HTTP_400_BAD_REQUEST)

        # optional workspace override
        ws_obj = None
        ws_id = request.data.get("workspace")
        if ws_id not in (None, ""):
            try:
                ws_id_int = int(ws_id)
                ws_candidate = Workspace.objects.filter(user=delegate, id=ws_id_int).first()
                if ws_candidate:
                    ws_obj = ws_candidate
            except Exception:
                pass

        owner_ids = set([delegate.id])
        if request.user and request.user.is_staff:
            # staff can use any protocol
            owner_ids = None

        errors = []
        jobs_to_create = []
        lines = tsv_content.splitlines()
        protocol_cache = {}
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

                # fetch protocol once, verify visibility/ownership
                if protocol_id not in protocol_cache:
                    p = ProtocolList.objects.filter(id=protocol_id).first()
                    if p is None:
                        errors.append({"line": idx, "error": f"protocol {protocol_id} not found"})
                        protocol_cache[protocol_id] = None
                        continue
                    if owner_ids is not None and not (p.user is None or int(getattr(p.user, "id", -1)) in owner_ids):
                        errors.append({"line": idx, "error": f"no permission for protocol {protocol_id}"})
                        protocol_cache[protocol_id] = None
                        continue
                    protocol_cache[protocol_id] = p
                proto = protocol_cache.get(protocol_id)
                if proto is None:
                    continue

                jobs_to_create.append(
                    Job(
                        protocol_id=protocol_id,
                        protocol_ver=proto.ver,
                        job_name=job_name,
                        input_file=input_file,
                        parameter=parameter,
                        run_dir=get_config('env', 'workspace'),
                        user=delegate,
                        is_gpu_job=is_gpu_job,
                        workspace=ws_obj,
                        array_setting=array_setting,
                    )
                )
            except Exception as e:
                errors.append({"line": idx, "error": str(e)})

        if jobs_to_create:
            Job.objects.bulk_create(jobs_to_create)
        return Response({"created": len(jobs_to_create), "errors": errors})

    @action(detail=False, methods=["get"], url_path="status-counts", permission_classes=[permissions.IsAuthenticated])
    def status_counts(self, request):
        """
        GET /jobs/status-counts/

        Return the number of jobs in each status for the current user's delegate.

        Response
        --------
        {
          "total": int,
          "counts": [ { "value": int, "label": str, "count": int }, ... ]
        }
        """
        delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
        qs = Job.objects.filter(user=delegate)
        # aggregate counts by status present
        agg = list(qs.values("status").annotate(count=Count("id")))
        present = {int(row["status"]): int(row["count"]) for row in agg}
        out = []
        total = 0
        for (value, label) in JobStatus.choices:
            v = int(value)
            c = int(present.get(v, 0))
            total += c
            out.append({"value": v, "label": str(label), "count": c})
        return Response({"total": total, "counts": out})

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /jobs/{id}/

        Mirrors legacy delete behavior:
        - Forbid deletion if job is locked
        - Forbid deletion when dependent archives exist
        - On success, delete DB record and remove job output folder
        """
        job = self.get_object()
        if job.locked:
            return Response({"detail": "This job is locked, please unlock first"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            n_archive = FileArchive.objects.filter(job=job).count()
        except Exception:
            n_archive = 0
        if n_archive > 0:
            return Response({"detail": f"Job is under protection.({n_archive} dependent archives)"}, status=status.HTTP_400_BAD_REQUEST)

        # audit before deletion
        _audit_operation(job, "Deleted a job")
        # perform deletion then remove files
        self.perform_destroy(job)
        try:
            delete_job_file_tree(job)
        except Exception:
            pass
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["get"], url_path="files")
    def files(self, request, pk=None):
        """
        GET /jobs/{id}/files/

        Returns a flat list of files under the job's output directory.

        Query params:
          - limit: int, optional (default 200)
          - offset: int, optional (default 0)
          - sort: str, optional (name|size|created). default 'name'
          - order: str, optional (asc|desc). default 'asc'
          - q: str, optional. case-insensitive substring to filter file name
        """
        job = self.get_object()
        # paging params
        try:
            limit = int(request.query_params.get("limit", request.query_params.get("max", 200)))
        except Exception:
            limit = 200
        try:
            offset = int(request.query_params.get("offset", 0))
        except Exception:
            offset = 0
        limit = max(1, min(1000, limit))  # safety bounds
        offset = max(0, offset)

        # collect then sort to ensure stable pagination
        # note: for large directories this may be expensive; adjust cap if needed
        items = list_job_files(job, max_files=50000)
        # optional name filter
        q = (request.query_params.get("q", "") or "").strip().lower()
        if q:
            try:
                items = [it for it in items if q in str(it.get("name", "")).lower()]
            except Exception:
                pass
        sort_field = (request.query_params.get("sort", "name") or "name").lower()
        order = (request.query_params.get("order", "asc") or "asc").lower()
        reverse = order == "desc"
        # safe sort keys
        import time as _t
        def _created_ts(s: str) -> float:
            try:
                return _t.mktime(_t.strptime(s, "%a %b %d %H:%M:%S %Y"))
            except Exception:
                return 0.0
        try:
            if sort_field == "size":
                items.sort(key=lambda x: int(x.get("file_size") or 0), reverse=reverse)
            elif sort_field == "created":
                items.sort(key=lambda x: _created_ts(x.get("file_create") or ""), reverse=reverse)
            else:
                items.sort(key=lambda x: (x.get("name") or "").lower(), reverse=reverse)
        except Exception:
            pass
        total = len(items)
        start = min(offset, total)
        end = min(start + limit, total)
        page_items = items[start:end]
        has_more = end < total
        return Response({
            "items": page_items,
            "total": total,
            "offset": start,
            "limit": limit,
            "has_more": has_more,
        })

    @action(detail=False, methods=["get"], url_path="workspace-files", permission_classes=[permissions.IsAuthenticated])
    def workspace_files(self, request):
        """
        GET /jobs/workspace-files/?type=uploads|refs

        List files under the user's workspace subfolder (uploads or refs).

        Response: [{ name, file_size, file_create, full_path }]
        """
        import base64
        import time
        user = request.user.queuedb_profile_related.delegate
        kind = (request.query_params.get("type", "uploads") or "uploads").lower()
        if kind not in ("uploads", "refs"):
            kind = "uploads"
        base_dir = get_config('env', 'workspace')
        try:
            base_dir = str(base_dir) if base_dir is not None else os.getcwd()
        except Exception:
            base_dir = os.getcwd()
        user_root = os.path.join(base_dir, str(user.id), kind)
        try:
            os.makedirs(user_root, exist_ok=True)
        except Exception:
            pass
        out = []
        for root, dirs, files in os.walk(user_root):
            for file_name in files:
                try:
                    full_path = os.path.join(root, file_name)
                    rel = full_path.replace(user_root + os.sep, "").replace(user_root, "")
                    out.append({
                        "name": rel,
                        "file_size": os.path.getsize(full_path),
                        "file_create": time.ctime(os.path.getctime(full_path)),
                        "full_path": full_path,
                    })
                except Exception:
                    continue
        out.sort(key=lambda x: x.get("name") or "")
        return Response(out)

    @action(detail=False, methods=["get"], url_path="shared-search", permission_classes=[permissions.IsAuthenticated])
    def shared_search(self, request):
        """
        GET /jobs/shared-search/?q=keyword|id

        Search jobs owned by users who granted read access to the current user via CrossAccess.
        Returns a small list suitable for selection when referencing other users' job results.
        """
        delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
        # users who granted read access to delegate
        owner_ids = list(CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True))
        if not owner_ids:
            return Response([])
        q = (request.query_params.get("q", "") or "").strip()
        qs = Job.objects.filter(user_id__in=owner_ids)
        if q:
            if q.isdigit():
                qs = qs.filter(id=int(q))
            else:
                qs = qs.filter(job_name__icontains=q)
        qs = qs.order_by("-id")[:50]
        return Response([{ "id": j.id, "job_name": j.job_name } for j in qs])

    @action(detail=False, methods=["get"], url_path="shared-files", permission_classes=[permissions.IsAuthenticated])
    def shared_files(self, request):
        """
        GET /jobs/shared-files/?job_id=ID&limit=&offset=&sort=&order=

        List files for a job owned by another user if the current user has read access via CrossAccess.
        Mirrors the shape of /jobs/{id}/files.
        """
        try:
            job_id = int(request.query_params.get("job_id", 0))
        except Exception:
            job_id = 0
        if not job_id:
            return Response({"detail": "job_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
        # verify cross access
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            return Response({"detail": "job not found"}, status=status.HTTP_404_NOT_FOUND)
        has_access = CrossAccess.objects.filter(user=job.user, grantee=delegate, allow_read=1).exists()
        if not has_access and not request.user.is_staff:
            return Response({"detail": "forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # reuse files listing logic
        try:
            limit = int(request.query_params.get("limit", request.query_params.get("max", 200)))
        except Exception:
            limit = 200
        try:
            offset = int(request.query_params.get("offset", 0))
        except Exception:
            offset = 0
        limit = max(1, min(1000, limit))
        offset = max(0, offset)
        print(job, flush=True)
        items = list_job_files(job, max_files=50000)
        # optional name filter
        q = (request.query_params.get("q", "") or "").strip().lower()
        if q:
            try:
                items = [it for it in items if q in str(it.get("name", "")).lower()]
            except Exception:
                pass
        print(items, flush=True)
        sort_field = (request.query_params.get("sort", "name") or "name").lower()
        order = (request.query_params.get("order", "asc") or "asc").lower()
        reverse = order == "desc"
        import time as _t
        def _created_ts(s: str) -> float:
            try:
                return _t.mktime(_t.strptime(s, "%a %b %d %H:%M:%S %Y"))
            except Exception:
                return 0.0
        try:
            if sort_field == "size":
                items.sort(key=lambda x: int(x.get("file_size") or 0), reverse=reverse)
            elif sort_field == "created":
                items.sort(key=lambda x: _created_ts(x.get("file_create") or ""), reverse=reverse)
            else:
                items.sort(key=lambda x: (x.get("name") or "").lower(), reverse=reverse)
        except Exception:
            pass
        total = len(items)
        start = min(offset, total)
        end = min(start + limit, total)
        page_items = items[start:end]
        has_more = end < total
        return Response({
            "items": page_items,
            "total": total,
            "offset": start,
            "limit": limit,
            "has_more": has_more,
        })

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """
        GET /jobs/{id}/download/?trace=BASE64

        Download a specific file under the job's output directory.
        """
        job = self.get_object()
        trace = request.query_params.get("trace")
        if not trace:
            return Response({"detail": "trace is required"}, status=status.HTTP_400_BAD_REQUEST)
        return open_job_file_response(job, trace)

    @action(detail=True, methods=["get"], url_path="preview")
    @xframe_options_exempt
    def preview(self, request, pk=None):
        """
        GET /jobs/{id}/preview/?trace=BASE64

        Return a response suitable for inline preview. Textual files are returned as text,
        images and pdf are returned with inline content-disposition.
        """
        job = self.get_object()
        trace = request.query_params.get("trace")
        if not trace:
            return Response({"detail": "trace is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return build_preview_response(job, trace)
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=["delete"], url_path="delete-file")
    def delete_file(self, request, pk=None):
        """
        DELETE /jobs/{id}/delete-file/?trace=BASE64

        Delete a specific file under the job's output directory.
        """
        job = self.get_object()
        trace = request.query_params.get("trace")
        if not trace:
            return Response({"detail": "trace is required"}, status=status.HTTP_400_BAD_REQUEST)
        ok = delete_job_file_by_trace(job, trace)
        if ok:
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({"detail": "Unable to delete file"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path="search")
    def search(self, request):
        """
        Flexible keyword search across multiple fields.

        Query params:
          - mode: 'all' (default AND across fields) | 'any' (OR across fields)
          - job_name, parameter, input_file: free-text; tokens split by space/comma; AND within field
          - job_name_not, parameter_not, input_file_not: tokens to exclude
          - protocol: numeric protocol id filter
          - protocol_name: free-text for protocol name (optional)
          - protocol_name_not: tokens to exclude from protocol name
          - workspace_name: free-text for workspace name (optional)
          - workspace_name_not: tokens to exclude from workspace name
          - status: space/comma separated ints (OR among values)
          - status_not: ints to exclude
          - id: space/comma separated ints (OR among values)
          - id_not: ids to exclude
          - workspace: workspace id
        """
        # scope by current user's delegate and optional shared scope
        delegate = getattr(request.user, "queuedb_profile_related", None)
        delegate = getattr(delegate, "delegate", request.user)
        scope = (request.query_params.get("scope", "own") or "own").lower()
        if scope in ("shared", "all"):
            owner_ids = list(CrossAccess.objects.filter(grantee=delegate, allow_read=1).values_list("user_id", flat=True))
        else:
            owner_ids = []
        if scope == "shared":
            qs = Job.objects.filter(user_id__in=owner_ids)
        elif scope == "all":
            qs = Job.objects.filter(Q(user=delegate) | Q(user_id__in=owner_ids))
        else:
            qs = Job.objects.filter(user=delegate)

        # basic filters
        apply_vis_filter = False
        ws_id = request.query_params.get("workspace")
        if ws_id and str(ws_id).isdigit():
            qs = qs.filter(workspace_id=int(ws_id))
        else:
            apply_vis_filter = True

        def split_tokens(val: str):
            return [t for t in re.split(r"[\s,]+", (val or "").strip()) if t]

        combine_mode = (request.query_params.get("mode", "all") or "all").lower()
        use_or = combine_mode == "any"
        group_qs = []

        # text fields
        field_map = {
            "job_name": "job_name__icontains",
            "parameter": "parameter__icontains",
            "input_file": "input_file__icontains",
        }
        for qp, lookup in field_map.items():
            raw_value = request.query_params.get(qp, "") or ""
            tokens = split_tokens(raw_value)
            pos_tokens = tokens
            neg_tokens = split_tokens(request.query_params.get(f"{qp}_not", "") or "")
            field_q = None
            if pos_tokens:
                tq = [Q(**{lookup: t}) for t in pos_tokens]
                field_q = reduce(operator.and_, tq)
                apply_vis_filter = False
            if neg_tokens:
                nq = [~Q(**{lookup: t}) for t in neg_tokens]
                neg_q = reduce(operator.and_, nq)
                field_q = neg_q if field_q is None else (field_q & neg_q)
                apply_vis_filter = False
            if field_q is not None:
                group_qs.append(field_q)

        # protocol id
        proto = request.query_params.get("protocol")
        if proto and str(proto).isdigit():
            group_qs.append(Q(protocol_id=int(proto)))

        # optional: protocol name keywords
        pname = request.query_params.get("protocol_name")
        ptokens = split_tokens(pname) if pname else []
        if ptokens:
            group_qs.append(reduce(operator.and_, [Q(protocol__name__icontains=t) for t in ptokens]))
        pn_tokens = split_tokens(request.query_params.get("protocol_name_not", "") or "")
        if pn_tokens:
            group_qs.append(reduce(operator.and_, [~Q(protocol__name__icontains=t) for t in pn_tokens]))

        # optional: workspace name keywords
        wname = request.query_params.get("workspace_name")
        wtokens = split_tokens(wname) if wname else []
        if wtokens:
            group_qs.append(reduce(operator.and_, [Q(workspace__name__icontains=t) for t in wtokens]))
        wn_tokens = split_tokens(request.query_params.get("workspace_name_not", "") or "")
        if wn_tokens:
            group_qs.append(reduce(operator.and_, [~Q(workspace__name__icontains=t) for t in wn_tokens]))

        # status values (OR among)
        stokens = []
        for t in split_tokens(request.query_params.get("status", "")):
            try:
                stokens.append(int(t))
                apply_vis_filter = False
            except Exception:
                pass
        if stokens:
            group_qs.append(reduce(operator.or_, [Q(status=s) for s in stokens]))
        sneg = []
        for t in split_tokens(request.query_params.get("status_not", "")):
            try:
                sneg.append(int(t))
            except Exception:
                pass
        if sneg:
            group_qs.append(~Q(status__in=sneg))

        # ids (OR among)
        idtokens = []
        for t in split_tokens(request.query_params.get("id", "")):
            try:
                idtokens.append(int(t))
                apply_vis_filter = False
            except Exception:
                pass
        if idtokens:
            group_qs.append(reduce(operator.or_, [Q(id=i) for i in idtokens]))
        idneg = []
        for t in split_tokens(request.query_params.get("id_not", "")):
            try:
                idneg.append(int(t))
            except Exception:
                pass
        if idneg:
            group_qs.append(~Q(id__in=idneg))

        if group_qs:
            qs = qs.filter(reduce(operator.or_ if use_or else operator.and_, group_qs))

        if apply_vis_filter:
            qs = qs.filter(visibility=1)
        else:
            qs = qs.filter(visibility__gte=1)
        qs = qs.order_by("-create_time", "-pk")
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="runners")
    def runners(self, request):
        """
        GET /jobs/runners/

        experimental: list available runners (slaves). to be removed in production.

        returns
        -------
        list[dict]
            each item has fields: {"id": int, "name": str}
        """
        try:
            rows = list(Slave.objects.all().order_by("name").values("id", "name"))
        except Exception:
            rows = []
        return Response(rows)

    @action(detail=False, methods=["get"], url_path="dag")
    def dag(self, request):
        """
        build a job dependency dag around a root job.

        parameters
        ----------
        root : int
            root job id (required). graph will be built around this job.
        up : int, optional
            ancestor depth (how many levels of jobs this job depends on). default 1, max 3.
        down : int, optional
            descendant depth (how many levels of jobs that depend on this job). default 1, max 3.
        max_nodes : int, optional
            safety cap on total nodes included. default 300.

        returns
        -------
        dict
            nodes and edges describing a dag, where an edge a->b means b references a via history tag.
        """
        delegate = request.user.queuedb_profile_related.delegate

        def _parse_parent_ids(job_obj):
            text = f"{job_obj.parameter or ''} {job_obj.input_file or ''}"
            out = set()
            try:
                for m in re.finditer(r"\{\{History:(\d+)-.*?\}\}", text, flags=re.IGNORECASE | re.DOTALL):
                    try:
                        out.add(int(m.group(1)))
                    except Exception:
                        continue
            except Exception:
                pass
            return out

        root_raw = request.query_params.get("root")
        if not root_raw or not str(root_raw).isdigit():
            return Response({"detail": "root is required and must be an integer"}, status=status.HTTP_400_BAD_REQUEST)
        root_id = int(root_raw)

        try:
            root_job = Job.objects.get(user=delegate, id=root_id)
        except Job.DoesNotExist:
            return Response({"detail": "root job not found"}, status=status.HTTP_404_NOT_FOUND)

        def _clamp(v, lo, hi, default):
            try:
                iv = int(v)
            except Exception:
                iv = default
            return max(lo, min(hi, iv))

        up_depth = _clamp(request.query_params.get("up", 1), 0, 3, 1)
        down_depth = _clamp(request.query_params.get("down", 1), 0, 3, 1)
        try:
            max_nodes = int(request.query_params.get("max_nodes", 300))
        except Exception:
            max_nodes = 300

        nodes_ids = {root_job.id}
        edges = set()  # (src, dst) where dst depends on src

        # expand ancestors (up)
        if up_depth > 0:
            visited_up = set([root_job.id])
            frontier_up = {root_job.id}
            for _ in range(up_depth):
                if not frontier_up or len(nodes_ids) >= max_nodes:
                    break
                # fetch job objects for current frontier
                frontier_jobs = {j.id: j for j in Job.objects.filter(user=delegate, id__in=list(frontier_up))}
                next_frontier = set()
                for jid, job_obj in frontier_jobs.items():
                    parent_ids = _parse_parent_ids(job_obj)
                    if not parent_ids:
                        continue
                    # keep only visible/owned parents
                    parent_qs = Job.objects.filter(user=delegate, id__in=list(parent_ids)).only("id")
                    for pid in parent_qs.values_list("id", flat=True):
                        if len(nodes_ids) >= max_nodes:
                            break
                        nodes_ids.add(pid)
                        edges.add((pid, jid))
                        if pid not in visited_up:
                            next_frontier.add(pid)
                visited_up |= next_frontier
                frontier_up = next_frontier

        # expand descendants (down)
        if down_depth > 0:
            visited_down = set([root_job.id])
            frontier_down = {root_job.id}
            for _ in range(down_depth):
                if not frontier_down or len(nodes_ids) >= max_nodes:
                    break
                # build or query to find children referencing any id in frontier
                or_q = None
                for jid in frontier_down:
                    needle = f"{{{{History:{jid}-"
                    piece = Q(parameter__icontains=needle) | Q(input_file__icontains=needle)
                    or_q = piece if or_q is None else (or_q | piece)
                if or_q is None:
                    break
                level_qs = list(Job.objects.filter(user=delegate).exclude(id__in=visited_down).filter(or_q))
                next_frontier = set()
                # determine accurate edges by parsing each child's parents
                for child in level_qs:
                    if len(nodes_ids) >= max_nodes:
                        break
                    nodes_ids.add(child.id)
                    # parse parents of child and connect edges for any parent in current frontier
                    child_parents = _parse_parent_ids(child)
                    for src_id in (child_parents & frontier_down):
                        edges.add((src_id, child.id))
                    if child.id not in visited_down:
                        next_frontier.add(child.id)
                visited_down |= next_frontier
                frontier_down = next_frontier

        # materialize node data
        nodes = []
        if nodes_ids:
            for j in Job.objects.filter(user=delegate, id__in=list(nodes_ids)).select_related("protocol").only(
                "id", "job_name", "status", "protocol_id", "workspace_id"
            ).order_by("-id"):
                nodes.append({
                    "id": j.id,
                    "job_name": j.job_name,
                    "status": j.status,
                    "protocol_id": j.protocol_id,
                    "workspace_id": getattr(j, "workspace_id", None),
                })

        out_edges = [{"from": s, "to": t} for (s, t) in edges]
        return Response({
            "root": root_job.id,
            "nodes": nodes,
            "edges": out_edges,
        })

    @action(detail=True, methods=["post", "get"], url_path="rerun")
    def rerun(self, request, pk=None):
        job = self.get_object()
        # accept insitu from body or query for convenience
        try:
            raw_insitu = request.data.get("insitu", request.query_params.get("insitu", 0))
            insitu = bool(int(raw_insitu))
        except Exception:
            insitu = False

        # mirror legacy ui behavior: forbid rerun when locked
        if job.locked:
            return Response({"detail": "This job is locked, please unlock first"}, status=status.HTTP_400_BAD_REQUEST)

        # if not rerunning in-situ, remove previous result folder
        if not insitu:
            delete_job_file_tree(job)

        job.rerun_job(insitu=insitu)
        _audit_operation(job, "Reran a job", comment=f"insitu={insitu}")
        return Response({"status": "rerun"})

    @action(detail=True, methods=["post"], url_path="resume")
    def resume(self, request, pk=None):
        job = self.get_object()
        # prevent resume when locked; follow legacy behavior
        if job.locked:
            return Response({"detail": "This job is locked, please unlock first"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            rollback = int(request.data.get("rollback_to", request.query_params.get("rollback_to", 0)))
        except Exception:
            rollback = 0
        rollback_to = max(rollback, 0)
        if rollback_to <= job.resume:
            job.resume_job(rollback_to)
        else:
            job.resume_job(job.resume)
        _audit_operation(job, "Resumed a job", comment=f"rollback_to={rollback_to}")
        return Response({"status": "resumed", "resume": job.resume})

    @action(detail=True, methods=["post"], url_path="terminate")
    def terminate(self, request, pk=None):
        job = self.get_object()
        job.terminate_job()
        _audit_operation(job, "Terminated a job")
        return Response({"status": "terminated"})

    @action(detail=True, methods=["post"], url_path="lock")
    def lock(self, request, pk=None):
        """
        POST /jobs/{id}/lock/

        Toggle lock or set explicitly with body param "locked" (0/1).
        """
        job = self.get_object()
        try:
            locked_param = request.data.get("locked", request.query_params.get("locked"))
            if locked_param is None:
                job.locked = 0 if job.locked else 1
            else:
                job.locked = 1 if int(locked_param) else 0
            job.save(update_fields=["locked"])
            _audit_operation(job, "Locked" if job.locked else "Unlocked")
            return Response({"status": "locked" if job.locked else "unlocked", "locked": job.locked})
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=["post"], url_path="mark-wrong")
    def mark_wrong(self, request, pk=None):
        """
        POST /jobs/{id}/mark-wrong/

        Mark a job as failed (status = JobStatus.WRONG). Forbid when locked.
        """
        job = self.get_object()
        if job.locked:
            return Response({"detail": "This job is locked, please unlock first"}, status=status.HTTP_400_BAD_REQUEST)
        job.status = JobStatus.WRONG
        job.save(update_fields=["status"])
        _audit_operation(job, "Marked wrong")
        return Response({"status": "marked_wrong"})

    @action(detail=True, methods=["post"], url_path="visibility")
    def visibility(self, request, pk=None):
        """
        POST /jobs/{id}/visibility/

        Body params:
          - visibility: {0,1,2}
        Enforces: not locked; if visibility>1 requires workspace.
        """
        job = self.get_object()
        if job.locked:
            return Response({"detail": "This job is locked, please unlock first"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            vis = int(request.data.get("visibility", request.query_params.get("visibility", 0)))
        except Exception:
            return Response({"detail": "Invalid visibility"}, status=status.HTTP_400_BAD_REQUEST)
        if vis > 1 and job.workspace is None:
            return Response({"detail": "Please assign a workspace to the job before setting visibility higher than 'workspace-only'"}, status=status.HTTP_400_BAD_REQUEST)
        old_vis = job.visibility
        job.visibility = vis
        job.save(update_fields=["visibility"])
        _audit_operation(job, "Changed visibility", comment=f"{old_vis} -> {vis}")
        return Response({"status": "visibility_updated", "visibility": job.visibility})

    @action(detail=True, methods=["get"], url_path="logs")
    def logs(self, request, pk=None):
        """
        GET /jobs/{id}/logs/?type=out|err or ?std_out=1

        Returns the requested stdout/stderr as text.
        """
        job = self.get_object()
        std_param = (request.query_params.get("type") or "").lower()
        try:
            std_out_flag = int(request.query_params.get("std_out", 0))
        except Exception:
            std_out_flag = 0
        is_out = std_param == "out" or std_out_flag == 1
        suffix = ".log" if is_out else ".err"
        log_path = os.path.join(get_config('env', 'log'), f"{job.id}{suffix}")
        try:
            content = get_job_log(log_path)
        except Exception:
            try:
                with open(log_path, 'r') as fh:
                    content = fh.read()
            except Exception as e:
                return Response({"detail": str(e)}, status=status.HTTP_404_NOT_FOUND)
        return Response(content, content_type="text/plain")

    @action(detail=True, methods=["get"], url_path="history")
    def history(self, request, pk=None):
        """
        GET /jobs/{id}/history/

        Returns job change history.

        By default returns structured JSON suitable for client-side rendering.
        If `format=html` (or `Accept: text/html`) is provided, returns pre-rendered HTML.
        """
        job = self.get_object()
        history_items = Audition.objects.filter(Q(related_job=job) | Q(job_name=job.job_name)).order_by("-create_time")

        want_html = (request.query_params.get("format") == "html") or ("text/html" in (request.headers.get("Accept", "")))

        try:
            from prettydiff import diff_json, get_annotated_lines_from_diff, Flag
            import html
            def build_lines(h):
                current = {"parameter": (h.new_par or "").split(";"), "inputs": h.current_input or ""}
                executed = {"parameter": (h.prev_par or "").split(";"), "inputs": h.prev_input or ""}
                try:
                    return get_annotated_lines_from_diff(diff_json(executed, current))
                except Exception:
                    return []
        except Exception:
            # fallback when prettydiff not available
            Flag = type("Flag", (), {"ADDED": object(), "REMOVED": object()})
            html = None
            def build_lines(h):
                # naive fallback: show previous vs current parameters only
                prev = (h.prev_par or "").split(";")
                curr = (h.new_par or "").split(";")
                lines = []
                for s in curr:
                    if s and s not in prev:
                        lines.append(type("L", (), {"s": s, "flags": {Flag.ADDED}, "indent": 0}))
                for s in prev:
                    if s and s not in curr:
                        lines.append(type("L", (), {"s": s, "flags": {Flag.REMOVED}, "indent": 0}))
                return lines

        if want_html and html is not None:
            rendered = ""
            for h in history_items:
                lines = build_lines(h)
                rendered += '<div class="font-mono text-sm"><ul class="list-none m-0 p-0"><li>operation: '
                rendered += (h.operation or "") + " (" + str(h.create_time) + ")"
                rendered += '</li><li>protocol version: '
                rendered += str(job.protocol_ver)
                rendered += '</li></ul>'
                for line in lines:
                    pure_content = (line.s or "").strip()
                    if pure_content in ("{", "}", ""):
                        continue
                    if getattr(line, 'flags', None) and getattr(Flag, 'ADDED') in line.flags:
                        rendered += '<span class="text-green-600">+&nbsp;'
                    elif getattr(line, 'flags', None) and getattr(Flag, 'REMOVED') in line.flags:
                        rendered += '<span class="text-red-600">-&nbsp;'
                    else:
                        continue
                    rendered += "&nbsp;" * (2 * getattr(line, 'indent', 0))
                    rendered += html.escape(line.s)
                    rendered += "</span><br/>"
                rendered += "</div><hr class=\"my-2 border-gray-200 dark:border-gray-800\">"
            return Response(rendered, content_type="text/html")

        # default: json structure
        out = []
        for h in history_items:
            item = {
                "operation": h.operation or "",
                "timestamp": str(h.create_time),
                "protocol_ver": job.protocol_ver,
                "entries": [],
            }
            lines = build_lines(h)
            for line in lines:
                s = (line.s or "").strip()
                if s in ("{", "}", ""):
                    continue
                if getattr(line, 'flags', None) and Flag.ADDED in line.flags:
                    kind = "added"
                elif getattr(line, 'flags', None) and Flag.REMOVED in line.flags:
                    kind = "removed"
                else:
                    kind = "context"
                item["entries"].append({
                    "text": s,
                    "kind": kind,
                    "indent": int(getattr(line, 'indent', 0)),
                })
            out.append(item)
        return Response(out)

    @action(detail=True, methods=["get"], url_path="dependents")
    def dependents(self, request, pk=None):
        """
        GET /jobs/{id}/dependents/

        Find jobs that reference this job's results using History tags.

        Notes
        -----
        History tag format: ``{{History:job_id-job_file}}``.
        This endpoint returns other jobs owned by the current user whose
        ``parameter`` or ``input_file`` contains ``{{History:{id}-``.

        Query params
        ------------
        depth : int, optional
            Degree of traversal for reverse dependencies. Defaults to 1.
            Maximum is 3. For example, depth=2 includes jobs that depend
            on direct dependents as well.
        """
        job = self.get_object()
        delegate = request.user.queuedb_profile_related.delegate
        try:
            depth = int(request.query_params.get("depth", 1))
        except Exception:
            depth = 1
        depth = max(1, min(depth, 3))

        visited_ids = {job.id}
        all_found_ids = set()
        frontier_ids = {job.id}

        for _ in range(depth):
            if not frontier_ids:
                break
            # build or predicate for any needle across parameter/input_file
            or_q = None
            for jid in frontier_ids:
                needle = f"{{{{History:{jid}-"
                piece = Q(parameter__icontains=needle) | Q(input_file__icontains=needle)
                or_q = piece if or_q is None else (or_q | piece)
            if or_q is None:
                break
            level_qs = Job.objects.filter(user=delegate).exclude(id__in=visited_ids).filter(or_q)
            level_ids = set(level_qs.values_list("id", flat=True))
            if not level_ids:
                break
            all_found_ids |= level_ids
            visited_ids |= level_ids
            frontier_ids = level_ids

        qs_all = Job.objects.filter(id__in=list(all_found_ids)).order_by("-id")
        page = self.paginate_queryset(qs_all)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs_all, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="dependencies")
    def dependencies(self, request, pk=None):
        """
        GET /jobs/{id}/dependencies/

        Find jobs that this job references via History tags in
        ``parameter`` or ``input_file``.

        Returns only jobs visible to the current user (owned by the
        user's delegate).

        Notes
        -----
        History tag format: ``{{History:job_id-job_file}}``.
        """
        job = self.get_object()
        delegate = request.user.queuedb_profile_related.delegate
        text = f"{job.parameter or ''} {job.input_file or ''}"
        try:
            ids = set()
            for m in re.finditer(r"\{\{History:(\d+)-.*?\}\}", text, flags=re.IGNORECASE | re.DOTALL):
                try:
                    ids.add(int(m.group(1)))
                except Exception:
                    continue
        except Exception:
            ids = set()
        if not ids:
            return Response([])
        qs = Job.objects.filter(user=delegate, id__in=list(ids)).order_by("-id")
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

class ProtocolListViewSet(viewsets.ModelViewSet):
    # backward compatible viewset name and route; now serves both ProtocolList and Protocol (proxy) uniformly
    # queryset = ProtocolList.objects.all()
    serializer_class = ProtocolListSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    ordering_fields = ['name', 'id']
    ordering = ['-id']  # Default: highest ID first

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        qs = ProtocolList.objects.filter(Q(user=user) | Q(user=None))

        # Handle search query
        q = (self.request.query_params.get("q", "") or "").strip()
        if q:
            tokens = re.split(r"[\s,]+", q)
            name_q = None
            for t in tokens:
                if not t:
                    continue
                cond = Q(name__icontains=t)
                name_q = cond if name_q is None else (name_q & cond)
            id_q = None
            try:
                id_q = Q(id=int(q))
            except Exception:
                pass
            if name_q is not None and id_q is not None:
                qs = qs.filter(name_q | id_q)
            elif name_q is not None:
                qs = qs.filter(name_q)
            elif id_q is not None:
                qs = qs.filter(id_q)

        # Handle ordering - respect the ordering parameter
        ordering = self.request.query_params.get('ordering', '')
        if ordering:
            # Validate that the ordering field is allowed
            if ordering.lstrip('-') in self.ordering_fields:
                qs = qs.order_by(ordering)
        else:
            # Apply default ordering if no ordering parameter is provided
            qs = qs.order_by(*self.ordering)

        return qs


class StepViewSet(viewsets.ModelViewSet):
    queryset = Step.objects.all()
    serializer_class = StepSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        allowed_protocols = ProtocolList.objects.filter(Q(user=user) | Q(user=None))
        qs = Step.objects.filter(parent__in=allowed_protocols)
        parent = (self.request.query_params.get("parent", "") or "").strip()
        if parent:
            try:
                pid = int(parent)
                qs = qs.filter(parent_id=pid)
            except Exception:
                pass
        return qs


class ReferenceViewSet(viewsets.ModelViewSet):
    queryset = Reference.objects.all()
    serializer_class = ReferenceSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        return Reference.objects.filter(Q(user=user) | Q(user=None))


class WorkspaceViewSet(viewsets.ModelViewSet):
    queryset = Workspace.objects.all()
    serializer_class = WorkspaceSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        qs = Workspace.objects.filter(user=user)
        q = (self.request.query_params.get("q", "") or "").strip()
        if q:
            tokens = re.split(r"[\s,]+", q)
            name_q = None
            for t in tokens:
                if not t:
                    continue
                cond = Q(name__icontains=t)
                name_q = cond if name_q is None else (name_q & cond)
            if name_q is not None:
                qs = qs.filter(name_q)
        return qs


class SampleViewSet(viewsets.ModelViewSet):
    queryset = Sample.objects.all()
    serializer_class = SampleSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        return Sample.objects.filter(user=user)


class TrainingViewSet(viewsets.ModelViewSet):
    queryset = Training.objects.all()
    serializer_class = TrainingSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]


class PredictionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Prediction.objects.all()
    serializer_class = PredictionSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated]


class VirtualEnvironmentViewSet(viewsets.ModelViewSet):
    # backward compatible viewset name and route; now serves both VirtualEnvironment and Environment (proxy)
    queryset = VirtualEnvironment.objects.all()
    serializer_class = VirtualEnvironmentSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]

    def get_queryset(self):
        user = self.request.user.queuedb_profile_related.delegate
        return VirtualEnvironment.objects.filter(Q(user=user) | Q(user=None))


class ProtocolShortcutViewSet(viewsets.ModelViewSet):
    queryset = ProtocolShortcut.objects.all().order_by("protocol_id", "order", "id")
    serializer_class = ProtocolShortcutSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrAdmin]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ["protocol", "active"]

    def get_queryset(self):
        delegate = getattr(getattr(self.request.user, "queuedb_profile_related", None), "delegate", self.request.user)
        # protocols visible to delegate (own or public)
        visible_protocol_ids = ProtocolList.objects.filter(Q(user=delegate) | Q(user=None)).values_list("id", flat=True)
        qs = ProtocolShortcut.objects.filter(Q(protocol_id__in=list(visible_protocol_ids)) | Q(protocol_id=None))
        # limit by ownership for non-staff: own or public
        if not getattr(self.request.user, "is_staff", False):
            qs = qs.filter(Q(user=delegate) | Q(user=None))
        proto = self.request.query_params.get("protocol")
        if proto and str(proto).isdigit():
            qs = qs.filter(protocol_id=int(proto))
        active = self.request.query_params.get("active")
        if active is not None and str(active) != "":
            try:
                av = int(active)
                qs = qs.filter(active=av)
            except Exception:
                pass
        return qs.order_by("protocol_id", "order", "id")


@method_decorator(csrf_exempt, name="dispatch")
class LoginView(APIView):
    """
    session login endpoint for drf.

    parameters
    ----------
    username : str
    password : str

    returns
    -------
    dict
        {"status": "ok"} on success; 400 with details on failure.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        data = request.data or {}
        username = data.get("username", "")
        password = data.get("password", "")
        user = authenticate(request=request, username=username, password=password)
        if user is None or not user.is_active:
            return Response({"detail": "invalid credentials"}, status=status.HTTP_400_BAD_REQUEST)
        login(request, user)
        return Response({"status": "ok"})


@method_decorator(csrf_exempt, name="dispatch")
class LogoutView(APIView):
    """
    session logout endpoint for drf.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, *args, **kwargs):
        logout(request)
        return Response({"status": "ok"})


class MeView(APIView):
    """
    returns the current authenticated user info.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, *args, **kwargs):
        u = request.user
        return Response({
            "id": getattr(u, "id", None),
            "username": getattr(u, "username", ""),
            "is_staff": getattr(u, "is_staff", False),
        })
