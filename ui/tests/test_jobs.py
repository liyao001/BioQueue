from django.urls import reverse

from QueueDB.models import Job, JobStatus
from ui.services import search_jobs
from ui.tests import Ui3TestCase


class JobTests(Ui3TestCase):
    def test_list_shows_own_jobs_only(self):
        mine = self.make_job(job_name="alice-job")
        self.make_job(user=self.other, job_name="bob-job", protocol=self.other_protocol)
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alice-job")
        self.assertNotContains(response, "bob-job")
        self.assertContains(response, str(mine.id))

    def test_htmx_list_returns_partial(self):
        self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:jobs"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<html")
        self.assertContains(response, 'id="job-results"')

    def test_auto_refresh_pauses_during_ui_interaction(self):
        self.make_job()
        self.login()
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, "shouldPauseAutoRefresh")
        self.assertContains(page, "every 8s[window.ui3")
        self.assertContains(page, "shouldPauseAutoRefresh()]")
        self.assertContains(page, 'id="job-results"')
        off = self.client.get(reverse("ui3:jobs"), {"auto": "0"})
        self.assertNotContains(off, "every 8s")

    def test_search_by_name(self):
        self.make_job(job_name="alpha")
        self.make_job(job_name="beta")
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"q": "alpha"})
        self.assertContains(response, "alpha")
        self.assertNotContains(response, "beta")

    def test_search_q_numeric_id(self):
        keep = self.make_job(job_name="keep-me")
        self.make_job(job_name="other")
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"q": str(keep.id)})
        self.assertContains(response, "keep-me")
        self.assertNotContains(response, "other")

    def test_search_q_splits_names_and_ids(self):
        named = self.make_job(job_name="gamma-run")
        other = self.make_job(job_name="unrelated")
        self.login()
        # AND mode: name token plus a non-matching id should exclude both
        response = self.client.get(reverse("ui3:jobs"), {"q": "gamma {}".format(other.id + 999)})
        self.assertNotContains(response, "gamma-run")
        self.assertNotContains(response, "unrelated")
        # OR mode: name or id
        response = self.client.get(
            reverse("ui3:jobs"),
            {"q": "gamma {}".format(other.id), "mode": "any"},
        )
        self.assertContains(response, "gamma-run")
        self.assertContains(response, "unrelated")
        self.assertContains(response, str(named.id))

    def test_search_exclude_job_name(self):
        self.make_job(job_name="keep-alpha")
        self.make_job(job_name="drop-alpha")
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"job_name_not": "drop"})
        self.assertContains(response, "keep-alpha")
        self.assertNotContains(response, "drop-alpha")

    def test_list_uses_card_layout(self):
        job = self.make_job(job_name="carded")
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, 'class="job-card')
        self.assertContains(response, 'id="job-card-{}"'.format(job.id))
        self.assertContains(response, "icon-btn-label")
        self.assertContains(response, 'title="More"')
        self.assertContains(response, reverse("ui3:job_archive", args=[job.id]))
        self.assertContains(response, reverse("ui3:job_dependents", args=[job.id]))
        self.assertContains(response, reverse("ui3:job_purge", args=[job.id]))
        self.assertContains(response, reverse("ui3:job_rename", args=[job.id]))
        self.assertContains(response, "job-card-busy")
        self.assertContains(response, 'data-ui3-lock="card"')
        self.assertContains(response, 'hx-indicator="closest .job-card"')
        self.assertContains(response, 'hx-sync="#job-results:abort"')
        self.assertContains(response, 'id="bulk-form"')
        self.assertContains(response, 'data-ui3-lock="results"')
        self.assertContains(response, "job-results-busy hidden")
        self.assertContains(response, "isJobUiLocked")
        self.assertNotContains(response, "<thead>")

    def test_running_card_shows_step_progress_and_shortcuts(self):
        from QueueDB.models import ProtocolShortcut, Step

        Step.objects.create(
            parent=self.protocol,
            software="a",
            parameter="x",
            step_order=1,
            hash="h1",
            user=self.user,
        )
        Step.objects.create(
            parent=self.protocol,
            software="b",
            parameter="y",
            step_order=2,
            hash="h2",
            user=self.user,
        )
        ProtocolShortcut.objects.create(
            user=self.user,
            protocol=self.protocol,
            label="Open eval",
            href_template="/eval/{id}",
            params_template="tab=out",
            active=1,
        )
        job = self.make_job(job_name="running-card", status=JobStatus.RUNNING, resume=0)
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, "1/2")
        self.assertContains(response, 'title="a x"')
        self.assertContains(response, "Open eval")
        self.assertContains(response, "/eval/{}".format(job.id))
        self.assertContains(response, "tab=out")

    def test_mark_finished_shortcut_uses_htmx_not_new_tab(self):
        from QueueDB.models import ProtocolShortcut

        ProtocolShortcut.objects.create(
            user=self.user,
            protocol=self.protocol,
            label="Mark finished",
            href_template="/ui/mark-finished?job_id={id}",
            active=1,
        )
        job = self.make_job(job_name="mf-shortcut", status=JobStatus.RUNNING)
        self.login()
        page = self.client.get(reverse("ui3:jobs"), {"q": "mf-shortcut"})
        self.assertContains(page, "Mark finished")
        self.assertContains(page, reverse("ui3:job_mark_finished", args=[job.id]))
        self.assertContains(page, 'hx-post="{}"'.format(reverse("ui3:job_mark_finished", args=[job.id])))
        self.assertNotContains(page, 'href="/ui/mark-finished?job_id={}"'.format(job.id))
        response = self.client.post(
            reverse("ui3:job_mark_finished", args=[job.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="job-results"')
        self.assertNotContains(response, "<html")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FINISHED)

    def test_search_jobs_helper_filters_status(self):
        running = self.make_job(job_name="run", status=JobStatus.RUNNING)
        self.make_job(job_name="wait", status=JobStatus.WAITING)
        qs = search_jobs(self.user, {"status": str(JobStatus.RUNNING)})
        ids = list(qs.values_list("id", flat=True))
        self.assertEqual(ids, [running.id])

    def test_search_can_include_visibility_values(self):
        shown = self.make_job(job_name="vis-shown", visibility=1)
        workspace = self.make_job(job_name="vis-ws", visibility=2, workspace=self.workspace)
        hidden = self.make_job(job_name="vis-hidden", visibility=0)
        default_ids = list(search_jobs(self.user, {}).values_list("id", flat=True))
        self.assertIn(shown.id, default_ids)
        self.assertNotIn(workspace.id, default_ids)
        self.assertNotIn(hidden.id, default_ids)
        named = list(search_jobs(self.user, {"q": "vis-"}).values_list("id", flat=True))
        self.assertIn(shown.id, named)
        self.assertIn(workspace.id, named)
        self.assertNotIn(hidden.id, named)
        hidden_only = list(search_jobs(self.user, {"visibility": "0"}).values_list("id", flat=True))
        self.assertEqual(hidden_only, [hidden.id])
        all_vis = set(search_jobs(self.user, {"visibility": "0,1,2"}).values_list("id", flat=True))
        self.assertEqual(all_vis, {shown.id, workspace.id, hidden.id})

    def test_job_list_visibility_filter_ui(self):
        hidden = self.make_job(job_name="vis-hidden", visibility=0)
        self.login()
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, 'id="filter-visibility"')
        self.assertContains(page, "Visibility: default")
        self.assertContains(page, "In workspace")
        self.assertNotContains(page, "vis-hidden")
        filtered = self.client.get(reverse("ui3:jobs"), {"visibility": "0"})
        self.assertContains(filtered, "vis-hidden")
        self.assertContains(filtered, "Visibility: 1 selected")
        self.assertContains(filtered, str(hidden.id))

    def test_create_job(self):
        self.login()
        response = self.client.post(
            reverse("ui3:job_create"),
            {"job_name": "new-job", "protocol": self.protocol.id, "parameter": "k=v"},
        )
        self.assertEqual(response.status_code, 302)
        job = Job.objects.get(job_name="new-job")
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.protocol, self.protocol)
        self.assertEqual(job.parameter, "k=v")

    def test_create_job_requires_name(self):
        self.login()
        response = self.client.post(reverse("ui3:job_create"), {"protocol": self.protocol.id})
        self.assertEqual(response.status_code, 400)

    def test_rerun_and_terminate(self):
        job = self.make_job(status=JobStatus.FINISHED)
        self.login()
        response = self.client.post(reverse("ui3:job_rerun", args=[job.id]))
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WAITING)

        job.status = JobStatus.RUNNING
        job.save(update_fields=["status"])
        response = self.client.post(reverse("ui3:job_terminate", args=[job.id]))
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.ter, 1)

    def test_htmx_rerun_returns_results_fragment(self):
        job = self.make_job(status=JobStatus.FINISHED)
        self.login()
        response = self.client.post(
            reverse("ui3:job_rerun", args=[job.id]),
            HTTP_HX_REQUEST="true",
            HTTP_HX_TARGET="job-results",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "queued to rerun")

    def test_locked_job_cannot_be_deleted(self):
        job = self.make_job(locked=1)
        self.login()
        response = self.client.post(reverse("ui3:job_delete", args=[job.id]))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Job.objects.filter(pk=job.id).exists())

    def test_delete_job(self):
        job = self.make_job()
        self.login()
        response = self.client.post(reverse("ui3:job_delete", args=[job.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Job.objects.filter(pk=job.id).exists())

    def test_cannot_rerun_other_users_job(self):
        job = self.make_job(user=self.other, protocol=self.other_protocol)
        self.login()
        response = self.client.post(reverse("ui3:job_rerun", args=[job.id]))
        self.assertEqual(response.status_code, 403)

    def test_edit_parameter(self):
        job = self.make_job(parameter="old")
        self.login()
        response = self.client.post(
            reverse("ui3:job_edit_field", args=[job.id, "parameter"]),
            {"value": "new=1"},
        )
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.parameter, "new=1")

    def test_running_count_badge(self):
        self.make_job(status=JobStatus.RUNNING)
        self.make_job(status=JobStatus.WAITING)
        self.login()
        response = self.client.get(reverse("ui3:running_count"))
        self.assertContains(response, "1")
        self.assertContains(response, "bq-running-badge")
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, 'id="running-badge"')
        self.assertContains(page, "bq-running-badge")
        self.assertContains(page, "bq-nav-item")

    def test_header_keeps_logo_and_nav_together(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, 'class="bq-bar"')
        self.assertContains(response, "ui3/logo.png")
        self.assertContains(response, 'class="bq-nav"')
        self.assertContains(response, 'id="bq-nav"')
        self.assertContains(response, "bq-nav-toggle")
        self.assertContains(response, 'aria-controls="bq-nav"')
        self.assertContains(response, "page-head")
        self.assertContains(response, "shouldPortCombo")
        self.assertContains(response, 'combo.closest(".ui-modal")')
        self.assertContains(response, "preventScroll")
        self.assertContains(response, "scrollIntoView")
        self.assertContains(response, "toggleFilters")
        self.assertContains(response, "scheduleToastDismiss")
        self.assertContains(response, "htmx:oobAfterSwap")
        self.assertNotContains(response, "navbar")

    def test_filters_use_searchable_combos(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, "ui-combo")
        self.assertContains(response, "filter-toggle")
        self.assertContains(response, 'id="filter-more"')
        self.assertContains(response, "filter protocols")
        self.assertContains(response, "filter workspaces")
        self.assertContains(response, 'name="combo_q"')
        self.assertContains(response, 'hx-include="this"')
        opts = self.client.get(reverse("ui3:protocol_options"), {"combo_q": "RNA"})
        self.assertContains(opts, "RNA-seq")
        miss = self.client.get(reverse("ui3:protocol_options"), {"combo_q": "zzzz-missing"})
        self.assertContains(miss, "No matches")
        legacy = self.client.get(reverse("ui3:protocol_options"), {"q": "RNA"})
        self.assertContains(legacy, "RNA-seq")

    def test_edit_modal_can_be_closed(self):
        job = self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:job_edit_field", args=[job.id, "comments"]))
        self.assertContains(response, "ui-overlay")
        self.assertContains(response, "ui-modal-lg")
        self.assertContains(response, "ui-modal-editor")
        self.assertContains(response, 'rows="16"')
        self.assertContains(response, "data-ui3-close")
        self.assertContains(response, "Comments")
        self.assertNotContains(response, "modal-open")
        self.assertNotContains(response, "Insert from job results")

    def test_parameter_edit_modal_is_wide(self):
        job = self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:job_edit_field", args=[job.id, "parameter"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ui-modal-lg")
        self.assertContains(response, "ui-modal-editor")
        self.assertContains(response, 'class="ui-input w-full font-mono"')
        self.assertContains(response, 'rows="16"')

    def test_input_file_edit_offers_job_results_picker(self):
        job = self.make_job()
        self.login()
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, 'id="picker-root"')
        response = self.client.get(reverse("ui3:job_edit_field", args=[job.id, "input_file"]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Insert from job results")
        self.assertContains(response, 'id="id_edit_input_file"')
        self.assertContains(response, 'hx-target="#picker-root"')
        self.assertContains(response, reverse("ui3:job_results_picker"))
        comments = self.client.get(reverse("ui3:job_edit_field", args=[job.id, "comments"]))
        self.assertNotContains(comments, "Insert from job results")

    def test_locked_job_cannot_open_edit_or_visibility(self):
        job = self.make_job(locked=1, comments="keep")
        self.login()
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, "Locked — unlock to hide")
        self.assertContains(page, "Locked — unlock to edit comments")
        edit = self.client.get(reverse("ui3:job_edit_field", args=[job.id, "comments"]))
        self.assertEqual(edit.status_code, 400)
        post = self.client.post(
            reverse("ui3:job_edit_field", args=[job.id, "comments"]),
            {"value": "changed"},
        )
        self.assertEqual(post.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.comments, "keep")

    def test_job_results_disinherits_swap_for_modals(self):
        self.make_job()
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, 'hx-disinherit="hx-swap hx-target hx-push-url"')
        self.assertContains(response, 'hx-target="#modal-root" hx-swap="innerHTML"')

    def test_job_files_browser(self):
        import os
        import tempfile

        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="with-files", result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        with open(os.path.join(folder, "region_mapping.bed"), "w") as fh:
            fh.write("chr1\t1\t10\n")
        self.login()
        response = self.client.get(reverse("ui3:job_files", args=[job.id]))
        self.assertContains(response, "hello.txt")
        self.assertContains(response, "filter files")
        self.assertContains(response, reverse("ui3:job_file_rename", args=[job.id]))
        self.assertContains(response, "fa-i-cursor")
        self.assertContains(response, "job-files-table")
        self.assertContains(response, 'class="job-files"')
        self.assertContains(response, "job-files-filter")
        self.assertContains(response, "job-files-controls")
        self.assertContains(response, "job-files-name")
        self.assertContains(response, "data-ui3-select-name")
        self.assertContains(response, 'id="job-files-results-{}'.format(job.id))
        self.assertContains(response, 'id="job-files-filter-{}'.format(job.id))
        self.assertContains(response, "job-file-select-all")
        self.assertContains(response, "job-files-delete-selected")
        self.assertContains(response, 'name="traces"')
        filtered = self.client.get(reverse("ui3:job_files", args=[job.id]), {"q": "nope", "partial": "1"})
        self.assertContains(filtered, "No files found")
        self.assertContains(filtered, 'id="job-files-results-{}'.format(job.id))
        from ui.files import encode_trace, list_job_files
        files = list_job_files(job)
        self.assertEqual(len(files), 2)
        by_name = {f["name"]: f for f in files}
        self.assertIn("hello.txt", by_name)
        self.assertIn("region_mapping.bed", by_name)
        download = self.client.get(
            reverse("ui3:job_file_download", args=[job.id]),
            {"trace": by_name["hello.txt"]["trace"]},
        )
        self.assertEqual(download.status_code, 200)
        preview = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["hello.txt"]["trace"], "name": "hello.txt"},
        )
        self.assertEqual(preview.status_code, 200)
        self.assertContains(preview, "abc")
        bed_preview = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["region_mapping.bed"]["trace"], "name": "attr/region_mapping.bed"},
        )
        self.assertEqual(bed_preview.status_code, 200)
        self.assertContains(bed_preview, "chr1")

    def test_preview_html_renders_and_logs_are_text(self):
        import os
        import tempfile

        from ui.files import list_job_files, preview_mode_for

        self.assertEqual(preview_mode_for("report.html"), "iframe")
        self.assertEqual(preview_mode_for("report.HTML"), "iframe")
        self.assertEqual(preview_mode_for("page.htm", "text/html"), "iframe")
        self.assertEqual(preview_mode_for("run.log"), "text")
        self.assertEqual(preview_mode_for("nextflow.log.1"), "text")
        self.assertEqual(preview_mode_for("cluster.out"), "text")

        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="preview-types", result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        with open(os.path.join(folder, "report.html"), "w") as fh:
            fh.write("<html><body><h1>HelloReport</h1></body></html>")
        with open(os.path.join(folder, "run.log"), "w") as fh:
            fh.write("step started\n")
        with open(os.path.join(folder, "nextflow.log.1"), "w") as fh:
            fh.write("rotated log line\n")
        self.login()
        by_name = {f["name"]: f for f in list_job_files(job)}
        html_preview = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["report.html"]["trace"], "name": "report.html"},
        )
        self.assertEqual(html_preview.status_code, 200)
        self.assertContains(html_preview, "<iframe")
        self.assertNotContains(html_preview, "&lt;html&gt;")
        raw_html = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["report.html"]["trace"], "raw": "1"},
        )
        self.assertEqual(raw_html.status_code, 200)
        self.assertIn("text/html", raw_html["Content-Type"])
        self.assertContains(raw_html, "HelloReport")
        log_preview = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["run.log"]["trace"], "name": "run.log"},
        )
        self.assertEqual(log_preview.status_code, 200)
        self.assertContains(log_preview, "step started")
        self.assertContains(log_preview, "<pre")
        rotated = self.client.get(
            reverse("ui3:job_file_preview", args=[job.id]),
            {"trace": by_name["nextflow.log.1"]["trace"], "name": "nextflow.log.1"},
        )
        self.assertEqual(rotated.status_code, 200)
        self.assertContains(rotated, "rotated log line")


    def test_job_files_sort(self):
        import os
        import tempfile
        import time

        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="sort-files", result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        small = os.path.join(folder, "a-small.txt")
        large = os.path.join(folder, "z-large.txt")
        with open(small, "w") as fh:
            fh.write("x")
        time.sleep(0.05)
        with open(large, "w") as fh:
            fh.write("y" * 200)
        self.login()
        by_name = self.client.get(
            reverse("ui3:job_files", args=[job.id]),
            {"partial": "1", "sort": "name", "order": "asc"},
        )
        body = by_name.content.decode()
        self.assertLess(body.find("a-small.txt"), body.find("z-large.txt"))
        by_size_desc = self.client.get(
            reverse("ui3:job_files", args=[job.id]),
            {"partial": "1", "sort_key": "size:desc"},
        )
        body = by_size_desc.content.decode()
        self.assertLess(body.find("z-large.txt"), body.find("a-small.txt"))
        self.assertContains(by_size_desc, 'value="size:desc" selected')
        self.assertContains(by_size_desc, "ui-sort-btn")

    def test_job_file_rename(self):
        import os
        import tempfile

        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="rename-files", result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        nested = os.path.join(folder, "nested")
        os.makedirs(nested)
        with open(os.path.join(folder, "hello.txt"), "w") as fh:
            fh.write("abc")
        with open(os.path.join(folder, "taken.txt"), "w") as fh:
            fh.write("nope")
        with open(os.path.join(nested, "inner.txt"), "w") as fh:
            fh.write("in")
        self.login()
        from ui.files import encode_trace, list_job_files

        by_name = {f["name"]: f for f in list_job_files(job)}
        hello = by_name["hello.txt"]
        get_resp = self.client.get(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"trace": hello["trace"]},
        )
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "new_name")
        self.assertContains(get_resp, "hello.txt")
        self.assertNotContains(get_resp, "<html")

        renamed = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]) + "?trace={}".format(hello["trace"]),
            {"new_name": "world.txt", "trace": hello["trace"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(renamed.status_code, 200)
        self.assertContains(renamed, "world.txt")
        self.assertContains(renamed, "Renamed to world.txt.")
        self.assertNotContains(renamed, "<html")
        self.assertFalse(os.path.exists(os.path.join(folder, "hello.txt")))
        self.assertTrue(os.path.exists(os.path.join(folder, "world.txt")))

        conflict = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"new_name": "taken.txt", "trace": encode_trace("out/world.txt")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(conflict.status_code, 409)

        traversal = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"new_name": "../escape.txt", "trace": encode_trace("out/world.txt")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(traversal.status_code, 400)
        self.assertFalse(os.path.exists(os.path.join(tmp, str(self.user.id), "escape.txt")))

        inner = by_name["nested/inner.txt"]
        nested_rename = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"new_name": "moved.txt", "trace": inner["trace"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(nested_rename.status_code, 200)
        self.assertTrue(os.path.exists(os.path.join(nested, "moved.txt")))
        self.assertFalse(os.path.exists(os.path.join(nested, "inner.txt")))
        self.assertFalse(os.path.exists(os.path.join(folder, "moved.txt")))

        too_long = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"new_name": "x" * 256, "trace": encode_trace("out/world.txt")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(too_long.status_code, 400)

        empty = self.client.post(
            reverse("ui3:job_file_rename", args=[job.id]),
            {"new_name": "   ", "trace": encode_trace("out/world.txt")},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(empty.status_code, 400)

        locked = self.make_job(job_name="locked-files", result="out", run_dir=tmp, locked=1)
        locked_folder = os.path.join(tmp, str(self.user.id), "out")
        with open(os.path.join(locked_folder, "locked.txt"), "w") as fh:
            fh.write("z")
        locked_files = {f["name"]: f for f in list_job_files(locked)}
        locked_post = self.client.post(
            reverse("ui3:job_file_rename", args=[locked.id]),
            {"new_name": "nope.txt", "trace": locked_files["locked.txt"]["trace"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(locked_post.status_code, 400)
        self.assertTrue(os.path.exists(os.path.join(locked_folder, "locked.txt")))

        other = self.make_job(
            user=self.other,
            protocol=self.other_protocol,
            job_name="other-files",
            result="out",
            run_dir=tmp,
        )
        other_folder = os.path.join(tmp, str(self.other.id), "out")
        os.makedirs(other_folder)
        with open(os.path.join(other_folder, "secret.txt"), "w") as fh:
            fh.write("no")
        other_files = {f["name"]: f for f in list_job_files(other)}
        forbidden = self.client.post(
            reverse("ui3:job_file_rename", args=[other.id]),
            {"new_name": "stolen.txt", "trace": other_files["secret.txt"]["trace"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(forbidden.status_code, 403)

    def test_job_file_delete_multi(self):
        import os
        import tempfile

        tmp = tempfile.mkdtemp()
        job = self.make_job(job_name="delete-files", result="out", run_dir=tmp)
        folder = os.path.join(tmp, str(self.user.id), "out")
        os.makedirs(folder)
        keep = os.path.join(folder, "keep.txt")
        a = os.path.join(folder, "a.txt")
        b = os.path.join(folder, "b.txt")
        for path, body in ((keep, "k"), (a, "a"), (b, "b")):
            with open(path, "w") as fh:
                fh.write(body)
        self.login()
        from ui.files import list_job_files

        by_name = {f["name"]: f for f in list_job_files(job)}
        page = self.client.get(reverse("ui3:job_files", args=[job.id]))
        self.assertContains(page, "job-files-delete-selected")
        self.assertContains(page, "job-file-select-all")
        self.assertContains(page, 'name="traces"')

        single = self.client.post(
            reverse("ui3:job_file_delete", args=[job.id]) + "?trace={}".format(by_name["a.txt"]["trace"]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(single.status_code, 200)
        self.assertContains(single, "File deleted.")
        self.assertNotContains(single, "<html")
        self.assertFalse(os.path.exists(a))
        self.assertTrue(os.path.exists(b))

        multi = self.client.post(
            reverse("ui3:job_file_delete", args=[job.id]),
            {"traces": [by_name["b.txt"]["trace"], by_name["keep.txt"]["trace"]]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(multi.status_code, 200)
        self.assertContains(multi, "Deleted 2 files.")
        self.assertFalse(os.path.exists(b))
        self.assertFalse(os.path.exists(keep))

        empty = self.client.post(
            reverse("ui3:job_file_delete", args=[job.id]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(empty.status_code, 400)

        with open(os.path.join(folder, "again.txt"), "w") as fh:
            fh.write("x")
        locked = self.make_job(job_name="locked-delete", result="out", run_dir=tmp, locked=1)
        locked_files = {f["name"]: f for f in list_job_files(locked)}
        locked_post = self.client.post(
            reverse("ui3:job_file_delete", args=[locked.id]),
            {"traces": [locked_files["again.txt"]["trace"]]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(locked_post.status_code, 400)
        self.assertTrue(os.path.exists(os.path.join(folder, "again.txt")))

        other = self.make_job(
            user=self.other,
            protocol=self.other_protocol,
            job_name="other-delete",
            result="out",
            run_dir=tmp,
        )
        other_folder = os.path.join(tmp, str(self.other.id), "out")
        os.makedirs(other_folder)
        with open(os.path.join(other_folder, "secret.txt"), "w") as fh:
            fh.write("no")
        other_files = {f["name"]: f for f in list_job_files(other)}
        forbidden = self.client.post(
            reverse("ui3:job_file_delete", args=[other.id]),
            {"traces": [other_files["secret.txt"]["trace"]]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(forbidden.status_code, 403)
        self.assertTrue(os.path.exists(os.path.join(other_folder, "secret.txt")))

    def test_pager_has_jump_controls(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, "job-pager")
        self.assertContains(response, "pager-meta")
        self.assertContains(response, "pager-size")
        self.assertContains(response, "aria-label=\"Page number\"")
        self.assertContains(response, 'id="page-size-select"')
        self.assertContains(response, "page size")
        body = response.content.decode()
        filters_idx = body.find('id="job-filters"')
        pager_idx = body.find('id="page-size-select"')
        self.assertGreater(pager_idx, filters_idx)
        # page size control should not appear in the top filter toolbar
        filters_chunk = body[filters_idx:body.find('id="job-results"')]
        self.assertNotIn("page size", filters_chunk)
        # Multi-page pager must not bake filters into hx-get (that duplicated q=/protocol=).
        for i in range(20):
            self.make_job(job_name="page-job-{}".format(i))
        multi = self.client.get(reverse("ui3:jobs"), {"page_size": "12"})
        self.assertContains(multi, 'hx-vals=\'{"page": "2"}\'')
        self.assertContains(multi, 'hx-include="#job-filters"')
        # Pager page links must use bare list URL + hx-vals (not a baked-in query string).
        self.assertRegex(
            multi.content.decode(),
            r'hx-get="%s"\s+hx-vals=\'\{"page": "2"\}\'' % reverse("ui3:jobs"),
        )
        self.assertContains(multi, "htmx:configRequest")

    def test_list_params_compacts_duplicate_empty_query(self):
        from ui.http import compact_querydict, list_params
        from django.http import QueryDict
        from django.test import RequestFactory

        bloated = QueryDict("q=&q=&q=&protocol=&protocol=&page=2")
        cleaned = compact_querydict(bloated)
        self.assertEqual(list(cleaned.keys()), ["page"])
        self.assertEqual(cleaned.get("page"), "2")
        rf = RequestFactory()
        request = rf.get("/ui/jobs/?q=&q=&protocol=&protocol=&q=alpha&page=3")
        params = list_params(request)
        self.assertEqual(params.get("q"), "alpha")
        self.assertEqual(params.get("page"), "3")
        self.assertNotIn("protocol", params)

    def test_logs_no_typeerror(self):
        job = self.make_job()
        self.login()
        from unittest.mock import MagicMock, patch
        import sys
        import types

        fake_bases = types.ModuleType("worker.bases")
        fake_bases.get_config = MagicMock(return_value="/tmp/ui3-logs")
        fake_bases.get_job_log = MagicMock(return_value="line1<br />line2")
        with patch.dict(sys.modules, {"worker.bases": fake_bases}), patch(
            "os.path.exists", return_value=True
        ):
            response = self.client.get(reverse("ui3:job_logs", args=[job.id]), {"kind": "stdout"})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "TypeError")
        self.assertContains(response, "line1")

    def test_shared_job_card_is_read_only(self):
        from QueueDB.models import CrossAccess

        job = self.make_job(user=self.other, protocol=self.other_protocol, job_name="shared-ro")
        CrossAccess.objects.create(user=self.other, grantee=self.user, allow_read=1, allow_write=0)
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"scope": "shared"})
        self.assertContains(response, "shared-ro")
        self.assertContains(response, "read-only")
        self.assertContains(response, 'title="More"')
        self.assertContains(response, reverse("ui3:job_dependents", args=[job.id]))
        self.assertNotContains(response, reverse("ui3:job_archive", args=[job.id]))
        self.assertNotContains(response, reverse("ui3:job_purge", args=[job.id]))
        self.assertNotContains(response, reverse("ui3:job_rename", args=[job.id]))
        self.assertNotContains(response, 'hx-post="{}"'.format(reverse("ui3:job_rerun", args=[job.id])))

    def test_resume_modal_max_is_last_index(self):
        from QueueDB.models import Step

        Step.objects.create(parent=self.protocol, software="a", parameter="x", step_order=1, hash="h1", user=self.user)
        Step.objects.create(parent=self.protocol, software="b", parameter="y", step_order=2, hash="h2", user=self.user)
        Step.objects.create(parent=self.protocol, software="c", parameter="z", step_order=3, hash="h3", user=self.user)
        job = self.make_job(status=JobStatus.FINISHED, resume=2)
        self.login()
        response = self.client.get(reverse("ui3:job_resume", args=[job.id]))
        self.assertContains(response, "0–2")
        self.assertContains(response, "Step index")
        self.assertContains(response, 'max="2"')
        self.assertNotContains(response, 'max="3"')

    def test_failed_card_shows_step_progress_and_command(self):
        from QueueDB.models import Step

        Step.objects.create(
            parent=self.protocol,
            software="bwa",
            parameter="mem -t 8",
            step_order=1,
            hash="h1",
            user=self.user,
        )
        Step.objects.create(
            parent=self.protocol,
            software="samtools",
            parameter="sort",
            step_order=2,
            hash="h2",
            user=self.user,
        )
        self.make_job(job_name="failed-steps", status=JobStatus.WRONG, resume=1)
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"q": "failed-steps"})
        self.assertContains(response, "2/2")
        self.assertContains(response, "failed step 2 of 2")
        self.assertContains(response, 'title="samtools sort"')

    def test_step_command_tooltip_is_truncated(self):
        from QueueDB.models import Step

        long_param = "x" * 400
        Step.objects.create(
            parent=self.protocol,
            software="echo",
            parameter=long_param,
            step_order=1,
            hash="h1",
            user=self.user,
        )
        self.make_job(job_name="long-cmd", status=JobStatus.RUNNING, resume=0)
        self.login()
        response = self.client.get(reverse("ui3:jobs"), {"q": "long-cmd"})
        html = response.content.decode()
        self.assertIn("echo " + "x" * 20, html)
        self.assertIn("…", html)
        self.assertNotIn(long_param, html)

    def test_toast_uses_brand_success_and_error_colors(self):
        from ui.http import toast_html

        ok = toast_html("Saved.", "success")
        self.assertIn("#6a994e", ok)
        self.assertIn("Saved.", ok)
        err = toast_html("Nope.", "error")
        self.assertIn("#bc4749", err)
        self.assertIn("Nope.", err)

    def test_failed_job_card_hides_mark_failed_and_offers_resume(self):
        failed = self.make_job(job_name="failed-card", status=JobStatus.WRONG, resume=1)
        done = self.make_job(job_name="done-card", status=JobStatus.FINISHED, resume=1)
        self.login()
        failed_page = self.client.get(reverse("ui3:jobs"), {"q": "failed-card"})
        self.assertContains(failed_page, "Resume from failed step")
        self.assertContains(failed_page, 'from_failed')
        self.assertNotContains(failed_page, reverse("ui3:job_mark_wrong", args=[failed.id]))
        done_page = self.client.get(reverse("ui3:jobs"), {"q": "done-card"})
        self.assertContains(done_page, reverse("ui3:job_mark_wrong", args=[done.id]))
        self.assertNotContains(done_page, "Resume from failed step")

    def test_resume_from_failed_step_keeps_resume_point(self):
        from QueueDB.models import Step

        Step.objects.create(parent=self.protocol, software="a", parameter="x", step_order=1, hash="h1", user=self.user)
        Step.objects.create(parent=self.protocol, software="b", parameter="y", step_order=2, hash="h2", user=self.user)
        Step.objects.create(parent=self.protocol, software="c", parameter="z", step_order=3, hash="h3", user=self.user)
        job = self.make_job(status=JobStatus.WRONG, resume=2)
        self.login()
        response = self.client.post(reverse("ui3:job_resume", args=[job.id]), {"from_failed": "1"})
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WAITING)
        self.assertEqual(job.resume, 2)

    def test_cannot_mark_failed_job_failed_again(self):
        job = self.make_job(status=JobStatus.WRONG)
        self.login()
        response = self.client.post(reverse("ui3:job_mark_wrong", args=[job.id]))
        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.WRONG)

    def test_legacy_mark_finished_url(self):
        import os
        import tempfile
        from QueueDB.models import Audition

        tmp = tempfile.mkdtemp()
        job = self.make_job(status=JobStatus.RUNNING, result="out", run_dir=tmp)
        os.makedirs(os.path.join(tmp, str(job.user_id), "out"), exist_ok=True)
        with open(os.path.join(tmp, str(job.user_id), "out", "a.txt"), "w") as fh:
            fh.write("x")
        self.login()
        missing = self.client.get(reverse("ui3:mark_finished_compat"))
        self.assertEqual(missing.status_code, 400)
        response = self.client.get(reverse("ui3:mark_finished_compat"), {"job_id": job.id})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload.get("status"), 1)
        self.assertEqual(payload.get("info"), "Marked")
        job.refresh_from_db()
        self.assertEqual(job.status, JobStatus.FINISHED)
        self.assertTrue(
            Audition.objects.filter(related_job=job, operation="Done").exists()
            or Audition.objects.filter(job_name=job.job_name, operation="Done").exists()
        )
        self.assertTrue(os.path.exists(os.path.join(tmp, str(job.user_id), "out", ".snapshot.ini")))
        htmx_job = self.make_job(status=JobStatus.RUNNING, result="out2", run_dir=tmp)
        os.makedirs(os.path.join(tmp, str(htmx_job.user_id), "out2"), exist_ok=True)
        htmx = self.client.get(
            reverse("ui3:mark_finished_compat"),
            {"job_id": htmx_job.id},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(htmx.status_code, 200)
        self.assertContains(htmx, 'id="job-results"')
        htmx_job.refresh_from_db()
        self.assertEqual(htmx_job.status, JobStatus.FINISHED)
        browser = self.client.get(
            reverse("ui3:mark_finished_compat"),
            {"job_id": job.id},
            HTTP_ACCEPT="text/html",
        )
        self.assertEqual(browser.status_code, 302)
        self.assertIn("/ui/", browser["Location"])
        card = self.client.post(reverse("ui3:job_mark_finished", args=[job.id]))
        # already finished + unlocked is fine; locked path tested separately
        self.assertIn(card.status_code, (200, 302))
        locked = self.make_job(status=JobStatus.RUNNING, locked=1)
        blocked = self.client.get(reverse("ui3:mark_finished_compat"), {"job_id": locked.id})
        self.assertEqual(blocked.status_code, 400)
        foreign = self.make_job(user=self.other, protocol=self.other_protocol, status=JobStatus.RUNNING)
        forbidden = self.client.get(reverse("ui3:mark_finished_compat"), {"job_id": foreign.id})
        self.assertEqual(forbidden.status_code, 403)

    def test_crossaccess_read_cannot_rerun(self):
        from QueueDB.models import CrossAccess

        job = self.make_job(user=self.other, protocol=self.other_protocol, job_name="shared-job")
        CrossAccess.objects.create(user=self.other, grantee=self.user, allow_read=1, allow_write=0)
        self.login()
        # readable via scope=all
        from ui.services import get_readable_job, get_writable_job

        self.assertIsNotNone(get_readable_job(self.user, job.id))
        self.assertIsNone(get_writable_job(self.user, job.id))
        response = self.client.post(reverse("ui3:job_rerun", args=[job.id]))
        self.assertEqual(response.status_code, 403)

    def test_post_refresh_preserves_filters_via_hx_current_url(self):
        keep = self.make_job(job_name="keep-alpha")
        self.make_job(job_name="drop-beta")
        self.login()
        response = self.client.post(
            reverse("ui3:job_rerun", args=[keep.id]),
            HTTP_HX_REQUEST="true",
            HTTP_HX_CURRENT_URL="http://testserver/ui/jobs/?q=alpha",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "keep-alpha")
        self.assertNotContains(response, "drop-beta")

    def test_visibility_locked_rejects(self):
        job = self.make_job(locked=1, workspace=self.workspace)
        self.login()
        response = self.client.post(
            reverse("ui3:job_visibility", args=[job.id]),
            {"visibility": "2"},
        )
        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.visibility, 1)

    def test_visibility_requires_workspace(self):
        job = self.make_job(workspace=None)
        self.login()
        response = self.client.post(
            reverse("ui3:job_visibility", args=[job.id]),
            {"visibility": "2"},
        )
        self.assertEqual(response.status_code, 400)

    def test_history_modal(self):
        from QueueDB.models import Audition

        job = self.make_job()
        Audition.objects.create(
            operation="Locked",
            related_job=job,
            job_name=job.job_name,
            prev_par=job.parameter,
            new_par=job.parameter,
            prev_input=job.input_file,
            current_input=job.input_file,
            protocol=job.protocol.name,
            protocol_ver=job.protocol_ver or "",
            user=self.user,
        )
        self.login()
        response = self.client.get(reverse("ui3:job_history", args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Locked")
        self.assertNotContains(response, "<th>User</th>")
        self.assertContains(response, "ui-overlay")
        self.assertContains(response, "data-ui3-close")

    def test_rename_modal_and_post(self):
        job = self.make_job(job_name="old-name")
        self.login()
        get_resp = self.client.get(reverse("ui3:job_rename", args=[job.id]))
        self.assertEqual(get_resp.status_code, 200)
        self.assertContains(get_resp, "new_name")
        from unittest.mock import patch

        with patch("ui.services.rename_job", return_value={"renames": [], "conflicts": []}) as mocked:
            response = self.client.post(
                reverse("ui3:job_rename", args=[job.id]),
                {"new_name": "new-name"},
            )
            mocked.assert_called()
        self.assertIn(response.status_code, (200, 302))

    def test_relations_modals(self):
        src = self.make_job(job_name="src")
        dep = self.make_job(
            job_name="dep",
            parameter="{{{{History:{}-out.txt}}}}".format(src.id),
        )
        self.login()
        deps = self.client.get(reverse("ui3:job_dependencies", args=[dep.id]))
        self.assertEqual(deps.status_code, 200)
        self.assertContains(deps, str(src.id))
        dependents = self.client.get(reverse("ui3:job_dependents", args=[src.id]))
        self.assertEqual(dependents.status_code, 200)
        self.assertContains(dependents, str(dep.id))
        self.assertContains(dependents, "ui-overlay")

    def test_bulk_terminate(self):
        a = self.make_job(status=JobStatus.RUNNING, job_name="bulk-a")
        b = self.make_job(status=JobStatus.RUNNING, job_name="bulk-b")
        locked = self.make_job(status=JobStatus.FINISHED, locked=1, job_name="bulk-locked")
        self.login()
        response = self.client.post(
            reverse("ui3:job_bulk"),
            {"action": "terminate", "ids": "{},{}".format(a.id, b.id)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        a.refresh_from_db()
        b.refresh_from_db()
        self.assertEqual(a.ter, 1)
        self.assertEqual(b.ter, 1)
        # locked skip for rerun
        response = self.client.post(
            reverse("ui3:job_bulk"),
            {"action": "rerun_clean", "ids": str(locked.id)},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Skipped")

    def test_delete_calls_file_tree(self):
        job = self.make_job(result="out-folder")
        self.login()
        from unittest.mock import patch

        with patch("ui.files.delete_job_file_tree") as mocked:
            response = self.client.post(reverse("ui3:job_delete", args=[job.id]))
            self.assertEqual(response.status_code, 302)
            mocked.assert_called_once()
        self.assertFalse(Job.objects.filter(pk=job.id).exists())

    def test_new_job_page_uses_combos(self):
        self.login()
        response = self.client.get(reverse("ui3:job_create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ui-combo")
        self.assertContains(response, "filter protocols")
        self.assertContains(response, "filter workspaces")
        self.assertContains(response, reverse("ui3:protocol_options"))
        self.assertContains(response, reverse("ui3:workspace_options"))
        self.assertContains(response, 'id="ui3-tokens"')
        self.assertContains(response, "data-ui3-complete")
        self.assertContains(response, 'id="id_parameter_legacy"')
        self.assertContains(response, "Legacy keys")
        self.assertContains(response, "InputFile")
        # Django would eat "{{" + token + "}}" as a string literal, inserting
        # " + token + " instead of {{Token}}. Split the braces in JS instead.
        self.assertContains(response, '"{" + "{" + token + "}" + "}"')
        self.assertNotContains(response, '"{{" + token + "}}"')

    def test_clone_bad_id_shows_error(self):
        self.login()
        response = self.client.get(reverse("ui3:job_create"), {"clone": "999999"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not found or is not accessible")
        self.assertNotContains(response, "-copy")

    def test_clone_invalid_id_shows_error(self):
        self.login()
        response = self.client.get(reverse("ui3:job_create"), {"clone": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid clone job id")

    def test_clone_foreign_protocol_shows_error(self):
        from QueueDB.models import CrossAccess

        job = self.make_job(
            user=self.other,
            protocol=self.other_protocol,
            job_name="shared-clone",
            parameter="a=1",
        )
        CrossAccess.objects.create(user=self.other, grantee=self.user, allow_read=1, allow_write=0)
        self.login()
        response = self.client.get(reverse("ui3:job_create"), {"clone": str(job.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "not available for creating new jobs")

    def test_clone_public_protocol_ok(self):
        from QueueDB.models import ProtocolList

        public = ProtocolList.objects.create(name="public-proto", user=None, ver="p1")
        job = self.make_job(protocol=public, job_name="to-clone", parameter="x=1")
        self.login()
        response = self.client.get(reverse("ui3:job_create"), {"clone": str(job.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "to-clone-copy")
        self.assertContains(response, "x=1")
        self.assertNotContains(response, "not available for creating")

    def test_create_with_array_setting(self):
        self.login()
        response = self.client.post(
            reverse("ui3:job_create"),
            {
                "job_name": "arrayed",
                "protocol": self.protocol.id,
                "parameter": "k=v",
                "array_setting": "1-5",
            },
        )
        self.assertEqual(response.status_code, 302)
        job = Job.objects.get(job_name="arrayed")
        self.assertEqual(job.array_setting, "1-5")

    def test_create_rejects_invalid_workspace(self):
        self.login()
        response = self.client.post(
            reverse("ui3:job_create"),
            {
                "job_name": "bad-ws",
                "protocol": self.protocol.id,
                "workspace": "999999",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, "Workspace", status_code=400)
        self.assertFalse(Job.objects.filter(job_name="bad-ws").exists())

    def test_parameter_scaffold_returns_keys(self):
        from QueueDB.models import Step

        Step.objects.create(
            parent=self.protocol,
            software="tool",
            parameter="{{Genome}} {{ThreadN}} {{MyKey:opt}} {{InputFile}} {{UMI_LEN||6}} {{MODE||per_read}} {{ZERO||0}} {{EXPR||a=b}}",
            step_order=1,
            hash="abc",
            user=self.user,
        )
        self.login()
        response = self.client.get(
            reverse("ui3:parameter_scaffold"),
            {"protocol": self.protocol.id, "format": "text"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.content.decode()
        self.assertIn("Genome=", body)
        self.assertIn("MyKey=", body)
        self.assertNotIn("ThreadN=", body)
        self.assertNotIn("InputFile=", body)
        self.assertIn("UMI_LEN=6;MODE=per_read;ZERO=0;EXPR=a=b;", body)
        legacy = self.client.get(
            reverse("ui3:parameter_scaffold"),
            {"protocol": self.protocol.id, "format": "text", "legacy": "1"},
        )
        self.assertEqual(
            legacy.content.decode(),
            "Genome=;MyKey=;UMI_LEN||6=;MODE||per_read=;ZERO||0=;EXPR||a=b=;",
        )
        html = self.client.get(reverse("ui3:parameter_scaffold"), {"protocol": self.protocol.id})
        self.assertTemplateUsed(html, "ui3/jobs/_parameter_scaffold.html")
        self.assertNotContains(html, "<html")

    def test_scaffold_preserves_conflicting_or_unrepresentable_defaults(self):
        from QueueDB.models import Step
        from ui.services import parameter_scaffold

        Step.objects.create(
            parent=self.protocol, software="tool", user=self.user, step_order=1, hash="defaults",
            parameter="{{SAME}} {{SAME||6}} {{SAME||6}} {{DIFFERENT||6}} {{DIFFERENT||8}} {{LIST||a;b}}",
        )
        self.assertEqual(parameter_scaffold(self.protocol, self.user), "SAME=6;DIFFERENT=;LIST=;")
        self.assertEqual(
            parameter_scaffold(self.protocol, self.user, legacy=True),
            "SAME=;SAME||6=;DIFFERENT||6=;DIFFERENT||8=;",
        )

    def test_workspace_uploads_list(self):
        import os
        import tempfile
        from unittest.mock import patch

        tmp = tempfile.mkdtemp()
        uploads = os.path.join(tmp, str(self.user.id), "uploads")
        os.makedirs(uploads)
        with open(os.path.join(uploads, "sample.fq"), "w") as fh:
            fh.write("x")
        self.login()
        with patch("ui.files.workspace_root_for", return_value=os.path.join(tmp, str(self.user.id))):
            response = self.client.get(reverse("ui3:workspace_uploads"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sample.fq")
        self.assertContains(response, "upload-opt")
        self.assertContains(response, "data-ui3-close")

    def test_job_results_picker_lists_recent_jobs(self):
        job = self.make_job(job_name="picker-source")
        self.login()
        response = self.client.get(reverse("ui3:job_results_picker"), {"target": "id_input_file"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "picker-source")
        self.assertContains(response, "#{}".format(job.id))
        self.assertContains(response, 'id="picker-body"')
        self.assertContains(response, 'id="picker-job-filter"')
        self.assertContains(response, 'id="picker-insert"')
        self.assertNotContains(response, 'id="picker-insert" disabled')
        self.assertNotContains(response, "Type a job name or id to search")

    def test_job_results_picker_filters_by_name(self):
        self.make_job(job_name="alpha-run")
        self.make_job(job_name="beta-run")
        self.login()
        response = self.client.get(
            reverse("ui3:job_results_picker"),
            {"q": "alpha", "target": "id_input_file"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "alpha-run")
        self.assertNotContains(response, "beta-run")

    def test_batch_create_from_tsv(self):
        self.login()
        tsv = "{}\tbatch-one\tin.fq\tp=1\n".format(self.protocol.id)
        response = self.client.post(
            reverse("ui3:job_create_batch"),
            {"tsv": tsv, "tab": "bulk"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Job.objects.filter(job_name="batch-one").exists())
        self.assertContains(response, "Created 1 job")

    def test_array_create_parent_and_children(self):
        self.login()
        job_list = "a.fq\tx=1\nb.fq\ty=2\n"
        response = self.client.post(
            reverse("ui3:job_create_array"),
            {
                "job_name": "arr-parent",
                "protocol": self.protocol.id,
                "job_list": job_list,
            },
        )
        self.assertEqual(response.status_code, 200)
        parent = Job.objects.get(job_name="arr-parent")
        self.assertEqual(parent.is_executable, 0)
        children = Job.objects.filter(parent_job=parent)
        self.assertEqual(children.count(), 2)
        self.assertContains(response, "Array parent #{}".format(parent.id))

    def test_card_inline_workspace_runner_array(self):
        from QueueDB.models import Slave

        runner = Slave.objects.create(name="node-1", comment="")
        job = self.make_job()
        self.login()
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, reverse("ui3:job_workspace", args=[job.id]))
        self.assertContains(page, reverse("ui3:job_runner", args=[job.id]))
        self.assertContains(page, reverse("ui3:job_edit_field", args=[job.id, "array_setting"]))
        self.assertContains(page, reverse("ui3:workspaces"))
        self.assertContains(page, reverse("ui3:environments"))

        ws = self.client.post(reverse("ui3:job_workspace", args=[job.id]), {"value": str(self.workspace.id)})
        self.assertEqual(ws.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.workspace_id, self.workspace.id)

        clear = self.client.post(reverse("ui3:job_workspace", args=[job.id]), {"value": ""})
        self.assertEqual(clear.status_code, 302)
        job.refresh_from_db()
        self.assertIsNone(job.workspace_id)

        run = self.client.post(reverse("ui3:job_runner", args=[job.id]), {"value": str(runner.id)})
        self.assertEqual(run.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.slave_id, runner.id)

        arr = self.client.post(
            reverse("ui3:job_edit_field", args=[job.id, "array_setting"]),
            {"value": "1-8"},
        )
        self.assertEqual(arr.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.array_setting, "1-8")

        opts = self.client.get(reverse("ui3:runner_options"), {"combo_q": "node"})
        self.assertContains(opts, "node-1")
        miss = self.client.get(reverse("ui3:runner_options"), {"combo_q": "zzzz-missing"})
        self.assertContains(miss, "No matches")
        ws_opts = self.client.get(reverse("ui3:workspace_options"), {"combo_q": "ws1", "empty": "(none)"})
        self.assertContains(ws_opts, "ws1")
        ws_legacy = self.client.get(reverse("ui3:workspace_options"), {"q": "ws1", "empty": "(none)"})
        self.assertContains(ws_legacy, "ws1")
        ws_miss = self.client.get(reverse("ui3:workspace_options"), {"combo_q": "zzzz-missing", "empty": "(none)"})
        self.assertContains(ws_miss, "No matches")
        self.assertContains(page, 'placeholder="filter runners"')
        self.assertContains(page, 'name="combo_q"')
        self.assertContains(page, 'hx-include="this"')

    def test_array_setting_rejects_too_long(self):
        job = self.make_job(array_setting="1-2")
        self.login()
        response = self.client.post(
            reverse("ui3:job_edit_field", args=[job.id, "array_setting"]),
            {"value": "x" * 101},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.array_setting, "1-2")

    def test_staff_can_assign_foreign_workspace(self):
        from QueueDB.models import Workspace

        self.user.is_staff = True
        self.user.save()
        foreign = Workspace.objects.create(name="bob-ws", user=self.other)
        job = self.make_job()
        self.login()
        opts = self.client.get(reverse("ui3:workspace_options"), {"combo_q": "bob"})
        self.assertContains(opts, "bob-ws")
        response = self.client.post(reverse("ui3:job_workspace", args=[job.id]), {"value": str(foreign.id)})
        self.assertEqual(response.status_code, 302)
        job.refresh_from_db()
        self.assertEqual(job.workspace_id, foreign.id)

    def test_non_staff_cannot_assign_foreign_workspace(self):
        from QueueDB.models import Workspace

        foreign = Workspace.objects.create(name="bob-ws", user=self.other)
        job = self.make_job()
        self.login()
        opts = self.client.get(reverse("ui3:workspace_options"), {"combo_q": "bob"})
        self.assertNotContains(opts, "bob-ws")
        response = self.client.post(reverse("ui3:job_workspace", args=[job.id]), {"value": str(foreign.id)})
        self.assertEqual(response.status_code, 400)
        job.refresh_from_db()
        self.assertNotEqual(job.workspace_id, foreign.id)

    def test_locked_job_cannot_change_workspace_runner_array(self):
        from QueueDB.models import Slave

        runner = Slave.objects.create(name="node-lock", comment="")
        job = self.make_job(locked=1, workspace=self.workspace, array_setting="1-2")
        self.login()
        ws = self.client.post(reverse("ui3:job_workspace", args=[job.id]), {"value": ""})
        self.assertEqual(ws.status_code, 400)
        run = self.client.post(reverse("ui3:job_runner", args=[job.id]), {"value": str(runner.id)})
        self.assertEqual(run.status_code, 400)
        arr = self.client.post(
            reverse("ui3:job_edit_field", args=[job.id, "array_setting"]),
            {"value": "9-10"},
        )
        self.assertEqual(arr.status_code, 400)
        job.refresh_from_db()
        self.assertEqual(job.workspace_id, self.workspace.id)
        self.assertIsNone(job.slave_id)
        self.assertEqual(job.array_setting, "1-2")

    def test_compiled_stylesheet_not_cdn(self):
        self.login()
        response = self.client.get(reverse("ui3:jobs"))
        self.assertContains(response, "ui3/app.css")
        self.assertNotContains(response, "@tailwindcss/browser")
        self.assertNotContains(response, "cdn.jsdelivr.net/npm/daisyui")

    def test_compare_two_jobs(self):
        left = self.make_job(job_name="left", parameter="threads=4", input_file="a.fq")
        right = self.make_job(job_name="right", parameter="threads=8", input_file="a.fq\nb.fq")
        other = self.make_job(user=self.other, protocol=self.other_protocol, job_name="secret")
        self.login()
        modal = self.client.get(reverse("ui3:job_compare", args=[left.id]))
        self.assertEqual(modal.status_code, 200)
        self.assertContains(modal, "Other job id")
        bounced = self.client.get(reverse("ui3:job_compare", args=[left.id]), {"other": str(right.id)})
        self.assertEqual(bounced.status_code, 302)
        page = self.client.get(reverse("ui3:job_compare_pair", args=[left.id, right.id]))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "threads")
        self.assertContains(page, "b.fq")
        forbidden = self.client.get(reverse("ui3:job_compare_pair", args=[left.id, other.id]))
        self.assertEqual(forbidden.status_code, 403)
        bulk = self.client.post(
            reverse("ui3:job_bulk"),
            {"action": "compare", "ids": "{},{}".format(left.id, right.id)},
        )
        self.assertEqual(bulk.status_code, 302)
        self.assertIn("/compare/", bulk["Location"])
        too_few = self.client.post(reverse("ui3:job_bulk"), {"action": "compare", "ids": str(left.id)})
        self.assertEqual(too_few.status_code, 400)

    def test_protocol_diff_page(self):
        job = self.make_job(protocol_ver="oldver")
        self.login()
        response = self.client.get(reverse("ui3:job_protocol_diff", args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Protocol version diff")
        self.assertContains(response, "oldver")
        self.assertContains(response, self.protocol.ver)
        self.assertContains(response, "No protocol dump on disk")
        self.assertNotContains(response, "diff-add")
        hidden = self.make_job(user=self.other, protocol=self.other_protocol)
        forbidden = self.client.get(reverse("ui3:job_protocol_diff", args=[hidden.id]))
        self.assertEqual(forbidden.status_code, 403)

    def test_purge_keeps_job_and_removes_tree(self):
        import os
        import shutil
        import tempfile

        tmp = tempfile.mkdtemp()
        try:
            job = self.make_job(result="out", run_dir=tmp)
            folder = os.path.join(tmp, str(self.user.id), "out")
            os.makedirs(folder)
            with open(os.path.join(folder, "a.txt"), "w") as fh:
                fh.write("x")
            self.login()
            locked = self.make_job(result="locked-out", locked=1)
            locked_resp = self.client.post(reverse("ui3:job_purge", args=[locked.id]))
            self.assertEqual(locked_resp.status_code, 400)
            response = self.client.post(reverse("ui3:job_purge", args=[job.id]))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(Job.objects.filter(pk=job.id).exists())
            self.assertFalse(os.path.isdir(folder))
            hidden = self.make_job(user=self.other, protocol=self.other_protocol)
            forbidden = self.client.post(reverse("ui3:job_purge", args=[hidden.id]))
            self.assertEqual(forbidden.status_code, 403)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_purge_blocked_when_archives_exist(self):
        from QueueDB.models import FileArchive

        job = self.make_job(result="out")
        FileArchive.objects.create(
            user=self.user,
            protocol=self.protocol,
            protocol_ver="test",
            inputs="",
            files="[]",
            file_md5s="ph",
            job=job,
            status=0,
        )
        self.login()
        response = self.client.post(reverse("ui3:job_purge", args=[job.id]))
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Job.objects.filter(pk=job.id).exists())

    def test_array_children_page(self):
        parent = self.make_job(job_name="arr-parent", is_executable=0)
        child = self.make_job(job_name="arr-child", parent_job=parent)
        other = self.make_job(job_name="unrelated")
        self.login()
        response = self.client.get(reverse("ui3:job_array", args=[parent.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Array #{}".format(parent.id))
        self.assertContains(response, "arr-child")
        self.assertNotContains(response, "unrelated")
        self.assertContains(response, reverse("ui3:job_array", args=[parent.id]))
        htmx = self.client.get(reverse("ui3:job_array", args=[parent.id]), HTTP_HX_REQUEST="true")
        self.assertNotContains(htmx, "<html")
        self.assertContains(htmx, "arr-child")
        page = self.client.get(reverse("ui3:jobs"))
        self.assertContains(page, reverse("ui3:job_array", args=[parent.id]))
        hidden = self.make_job(user=self.other, protocol=self.other_protocol, is_executable=0)
        forbidden = self.client.get(reverse("ui3:job_array", args=[hidden.id]))
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(child.job_name, "arr-child")
        self.assertEqual(other.job_name, "unrelated")

    def test_protocol_dump_path_rejects_traversal(self):
        from ui.services import protocol_dump_path

        self.assertIsNone(protocol_dump_path(1, "../etc/passwd"))
        self.assertIsNone(protocol_dump_path(1, ".."))
        path = protocol_dump_path(1, "abc123")
        self.assertTrue(path.endswith("protocol_dumps/1_abc123.txt"))
        self.assertNotIn("..", path)
