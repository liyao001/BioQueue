from django.urls import path

from .views import agent

app_name = "agent_api"

urlpatterns = [
    path("", agent.index, name="index"),
    path("jobs/", agent.jobs, name="jobs"),
    path("jobs/batch/", agent.jobs_batch, name="jobs_batch"),
    path("jobs/<int:pk>/", agent.job_detail, name="job_detail"),
    path("jobs/<int:pk>/logs/", agent.job_logs, name="job_logs"),
    path("jobs/<int:pk>/files/", agent.job_files, name="job_files"),
    path("jobs/<int:pk>/files/download/", agent.job_file_download, name="job_file_download"),
    path("jobs/<int:pk>/dag/", agent.job_dag, name="job_dag"),
    path("protocols/", agent.protocols, name="protocols"),
    path("protocols/import/", agent.protocol_import, name="protocol_import"),
    path("protocols/<int:pk>/", agent.protocol_detail, name="protocol_detail"),
    path("workspaces/", agent.workspaces, name="workspaces"),
    path("runners/", agent.runners, name="runners"),
]
