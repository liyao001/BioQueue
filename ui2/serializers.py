#!/usr/bin/env python
# -*- coding: utf-8 -*-

from rest_framework import serializers
from rest_framework.exceptions import NotAuthenticated
from django.db.models import Q

from QueueDB.models import (
    Job,
    ProtocolList, Protocol,
    Step,
    Reference,
    Workspace,
    Sample,
    Training,
    Prediction,
    VirtualEnvironment, Environment,
    Slave,
    ProtocolShortcut,
)


# reuse existing serializers when available
from QueueDB.serializers import (
    JobSerializer as CoreJobSerializer,
    CreateJobSerializer as CoreCreateJobSerializer,
)


class _AutoUserCreateMixin:
    def _get_delegate(self):
        request = self.context.get("request")
        if request is None:
            return None
        prof = getattr(request.user, "queuedb_profile_related", None)
        return getattr(prof, "delegate", request.user)

    def create(self, validated_data):
        # prevent client-supplied user override first
        validated_data.pop("user", None)
        # require an authenticated request and assign the current user's delegate
        request = self.context.get("request")
        if request is None or not getattr(request, "user", None) or not request.user.is_authenticated:
            raise NotAuthenticated("authentication required")
        delegate = self._get_delegate()
        if delegate is not None:
            validated_data["user"] = delegate
        return super().create(validated_data)


class ProtocolListSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = ProtocolList
        fields = [
            "id",
            "name",
            "description",
            "ver",
            "user",
        ]
        extra_kwargs = {"user": {"read_only": True}}


class StepSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = Step
        fields = [
            "id",
            "software",
            "parameter",
            "specify_output",
            "parent",
            "hash",
            "step_order",
            "env",
            "force_local",
            "version_check",
            "cpu_prior",
            "mem_prior",
            "disk_prior",
            "gpu_step",
            "step_comment",
        ]
        extra_kwargs = {"hash": {"read_only": True}}

    def create(self, validated_data):
        # compute hash from software and parameter
        try:
            import hashlib
            sw = str(validated_data.get("software", "") or "")
            par = str(validated_data.get("parameter", "") or "").strip()
            m = hashlib.md5(str(sw + " " + par).encode())
            validated_data["hash"] = m.hexdigest()
        except Exception:
            pass
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # recompute hash when software or parameter changes
        sw = validated_data.get("software", instance.software)
        par = validated_data.get("parameter", instance.parameter)
        try:
            import hashlib
            m = hashlib.md5(str(str(sw) + " " + str(par).strip()).encode())
            validated_data["hash"] = m.hexdigest()
        except Exception:
            pass
        return super().update(instance, validated_data)


class ReferenceSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = Reference
        fields = [
            "id",
            "name",
            "path",
            "description",
            "user",
        ]
        extra_kwargs = {"user": {"read_only": True}}


class WorkspaceSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = Workspace
        fields = ["id", "name", "description", "user", "create_time"]
        extra_kwargs = {"user": {"read_only": True}}


class SampleSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = Sample
        fields = [
            "id",
            "name",
            "file_path",
            "inner_path",
            "experiment",
            "attribute",
            "create_time",
            "user",
        ]
        extra_kwargs = {"user": {"read_only": True}}


class TrainingSerializer(serializers.ModelSerializer):
    class Meta:
        model = Training
        fields = [
            "id",
            "step_hash",
            "input",
            "output",
            "mem",
            "vrt_mem",
            "cpu",
            "create_time",
        ]


class PredictionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Prediction
        fields = ["id", "step_hash", "a", "b", "r", "type", "create_time"]


 


class VirtualEnvironmentSerializer(_AutoUserCreateMixin, serializers.ModelSerializer):
    class Meta:
        model = VirtualEnvironment
        fields = [
            "id",
            "name",
            "ve_type",
            "value",
            "activation_command",
            "user",
        ]
        extra_kwargs = {"user": {"read_only": True}}


# simple re-exports for clarity in api.py
class _ProtocolScopedMixin:
    def _limit_protocol_queryset(self, fields):
        request = self.context.get("request")
        if request and "protocol" in fields:
            try:
                from QueueDB.models import ProtocolList
                delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
                fields["protocol"].queryset = ProtocolList.objects.filter(Q(user=delegate) | Q(user=None))
            except Exception:
                pass


class JobSerializer(_ProtocolScopedMixin, serializers.ModelSerializer):
    protocol_name = serializers.CharField(source="protocol.name", read_only=True)
    workspace_name = serializers.CharField(source="workspace.name", read_only=True)
    # allow updating workspace (nullable fk)
    workspace = serializers.PrimaryKeyRelatedField(queryset=Workspace.objects.all(), allow_null=True, required=False)
    # runner (slave) is handled by drf as a normal fk; allow null updates
    slave = serializers.PrimaryKeyRelatedField(queryset=Slave.objects.all(), allow_null=True, required=False)
    slave_name = serializers.CharField(source="slave.name", read_only=True)
    class Meta:
        model = Job
        fields = [
            "id",
            "user_id",  # visible for readers
            "job_name",
            "protocol",
            "protocol_name",
            "protocol_ver",
            "parameter",
            "input_file",
            "result",
            "run_dir",
            "status",
            "resume",
            "locked",
            "workspace",
            "workspace_id",
            "workspace_name",
            "slave",
            "slave_name",
            "array_setting",
            "version",
            "create_time",
            "update_time",
            "visibility",
            "comments"
        ]

    def get_fields(self):
        fields = super().get_fields()
        self._limit_protocol_queryset(fields)
        # limit workspace options to current user's delegate
        try:
            request = self.context.get("request")
            if request is not None and "workspace" in fields:
                delegate = getattr(getattr(request.user, "queuedb_profile_related", None), "delegate", request.user)
                fields["workspace"].queryset = Workspace.objects.filter(user=delegate)
        except Exception:
            pass
        return fields

    def update(self, instance, validated_data):
        """
        Ensure changes to parameter and input_file go through
        model methods that create Audition records.
        """
        if instance.locked and "locked" in validated_data:
            if validated_data["locked"] == 1:
                raise serializers.ValidationError({"detail": "This job is locked, please unlock first"})

        # handle parameter update with audit
        if "parameter" in validated_data:
            new_par = validated_data.pop("parameter")
            if new_par != instance.parameter:
                instance.update_parameter(new_par)

        # handle input_file update with audit
        if "input_file" in validated_data:
            new_in = validated_data.pop("input_file")
            if new_in != instance.input_file:
                instance.update_inputs(new_in)

        # handle comments update with model helper (audition inside)
        if "comments" in validated_data:
            new_comments = validated_data.pop("comments")
            if new_comments != instance.comments:
                instance.update_comments(new_comments)

        # if protocol changed (or protocol_ver missing), refresh protocol_ver from current protocol
        if "protocol" in validated_data:
            try:
                proto = validated_data.get("protocol") or instance.protocol
                validated_data["protocol_ver"] = getattr(proto, "ver", "")
            except Exception:
                pass
        elif not getattr(instance, "protocol_ver", ""):
            try:
                validated_data["protocol_ver"] = getattr(instance.protocol, "ver", "")
            except Exception:
                pass

        # proceed with remaining fields (status/visibility/etc.)
        return super().update(instance, validated_data)


class CreateJobSerializer(_AutoUserCreateMixin, _ProtocolScopedMixin, serializers.ModelSerializer):
    # allow optional runner selection on create
    slave = serializers.PrimaryKeyRelatedField(queryset=Slave.objects.all(), allow_null=True, required=False)
    class Meta:
        model = Job
        fields = [
            "job_name",
            "protocol",
            "parameter",
            "input_file",
            # "user"  # auto-determined from request in view/serializer
            "workspace",
            "comments",
            "slave",
            "array_setting",
            "is_gpu_job",
        ]

    def get_fields(self):
        fields = super().get_fields()
        self._limit_protocol_queryset(fields)
        return fields

    def create(self, validated_data):
        # determine run_dir automatically from config
        try:
            from worker.bases import get_config
            validated_data["run_dir"] = get_config('env', 'workspace')
        except Exception:
            validated_data.setdefault("run_dir", "")
        # set protocol_ver from the selected protocol's current version
        proto = validated_data.get("protocol")
        if proto is not None:
            try:
                validated_data["protocol_ver"] = proto.ver
            except Exception:
                validated_data.setdefault("protocol_ver", "")
        # delegate user assignment to mixin and proceed with standard creation
        return super().create(validated_data)


class ProtocolShortcutSerializer(_AutoUserCreateMixin, _ProtocolScopedMixin, serializers.ModelSerializer):
    class Meta:
        model = ProtocolShortcut
        fields = [
            "id",
            "protocol",
            "label",
            "href_template",
            "params_template",
            "order",
            "active",
            "user",
        ]
        extra_kwargs = {"user": {"read_only": True}}

    def get_fields(self):
        fields = super().get_fields()
        self._limit_protocol_queryset(fields)
        return fields

        
 


