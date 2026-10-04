# BioQueue: repository guide

## What this project does

BioQueue is a personal or small-lab workspace for running bioinformatics analyses
and keeping their records. A **workspace** groups jobs for a project; a
**protocol** defines reusable commands; a **job** runs a protocol with inputs and
parameters. The app tracks results, logs, run history, and job dependencies.
Jobs can execute locally or through Slurm, LSF, Torque/PBS, or HTCondor.

Read `README.md` for the product overview and setup. The current default stack is
**QueueDB + ui + worker3**. Before changing ui, read
[`ui/AGENTS.md`](ui/AGENTS.md) for its UI patterns and contribution rules.

## Architecture and execution flow

- **`QueueDB/`** owns the shared Django models. `models.py` defines `Job`,
  `ProtocolList`, `Step`, `Workspace`, `Slave` (runner), `VirtualEnvironment`,
  `Reference`, `CrossAccess`, `Audition` (history), `Training`, and `Prediction`.
  `Protocol` and `Environment` are backward-compatible proxy model names.
- **`ui/`** is the default web UI at `/ui/`. `BioQueue/urls.py` redirects `/`
  there and redirects old `/ui3/` paths. It uses Django templates, HTMX, and
  Tailwind/DaisyUI. The DAG canvas is a Cytoscape JavaScript island.
- **`worker3/`** is a separate process started with `python -m worker3`. It reads
  and updates QueueDB directly through the Django ORM. UI requests create or
  update database records; the worker polls those records.

A typical run:

1. `ui/services.py` creates a job with its protocol, inputs, parameters,
   workspace, and optional runner.
2. `worker3/queue/job_queue.py` claims waiting, unlocked, executable jobs using
   a conditional database update. Unpinned workers fetch only unassigned jobs;
   pinned workers fetch jobs assigned to their runner.
3. `queue/task.py` builds in-memory state, prepares the results directory, and
   restores output mappings when resuming. `queue/protocol.py` materializes steps.
4. `queue/scheduler.py` dispatches steps under resource limits using greedy or
   FIFO scheduling. Steps are sequential within a job; jobs may run concurrently.
5. `step.py` resolves placeholders and forecasts resources. Input preflight and
   dependency checks run before execution. Commands run through
   `queue/process_runner.py` locally or through the cluster adapters.
6. Completion updates the step cursor, outputs, training records, and job status.
   The UI polls for changes and exposes logs, files, and history. If the job
   owner has notification hooks, worker3 sends them on start, finish, failure,
   and interrupt (`QueueDB/notifications.py`).

Protocols can also contain a compact JSON template (`samples`, `blocks`,
`pipeline`). `QueueDB/protocol_template.py` expands it and the job's optional
JSON `sample_sheet` into a flat step list. Both UI validation and worker execution
use this module; keep their interpretation consistent.

## Where to start for a change

| Issue or feature | Start here | Relevant tests |
| --- | --- | --- |
| Database fields, statuses, audit history | `QueueDB/models.py`, `QueueDB/migrations/` | Tests for affected UI and worker behavior |
| Job creation, search, permissions, actions | `ui/services.py`, `ui/views/jobs.py` | `ui/tests/test_jobs.py` |
| Protocol editing, import/export, step ordering | `ui/views/protocols.py`, `ui/services.py` | `ui/tests/test_protocols.py` |
| Template expansion or sample sheets | `QueueDB/protocol_template.py`, `worker3/queue/task.py` | `ui/tests/test_protocol_template.py`, worker integration tests |
| Files, previews, downloads, renames, purge | `ui/files.py`, `ui/views/jobs.py` | `ui/tests/test_jobs.py` |
| Dependency graph | `ui/services.py` (`parent_job_ids`, `build_job_dag`), `ui/views/dag.py`, `ui/static/ui3/dag.js` | `ui/tests/test_dag.py` |
| Workspaces, references, environments, accounts, archives | Matching `ui/views/<area>.py` and service functions | Matching `ui/tests/test_<area>.py` |
| HTMX responses, filters, toasts, authentication redirects | `ui/http.py`, `ui/decorators.py`, `ui/urls.py` | UI endpoint tests |
| Layout and shared browser behavior | `ui/templates/ui3/base.html`, area templates, `ui/static_src/input.css` | UI response tests; inspect affected page |
| Jobs stuck waiting, runner selection, duplicate execution | `worker3/queue/job_queue.py`, `worker3/queue/scheduler.py` | `worker3/tests/test_scheduler.py`, `test_integration.py` |
| Input validation and dependency waits | `worker3/queue/input_check.py`, `job_queue.py`, `worker3/step.py` | `worker3/tests/test_input_check.py` |
| Command substitution, shell scripts, process termination | `worker3/step.py`, `worker3/queue/process_runner.py` | `worker3/tests/test_step_shell.py`, `test_process_runner.py` |
| Resource prediction and measurement | `worker3/step.py`, `worker3/ml_collector.py`, `QueueDB/models.py` | Worker scheduler/integration tests |
| Cluster submission, polling, cancellation, SSH | `worker3/queue/cluster_request.py`, `worker3/cluster_support.py`, `worker3/cluster_models/` | `worker3/tests/test_cluster.py` |
| Worker startup, CLI, import problems | `worker3/cli.py`, `bioqueue.py`, `_bootstrap.py`, `django_initial.py` | `worker3/tests/test_cli.py`, `test_bootstrap.py` |
| Site-specific pages and shortcuts | `ui/plugins/`, `ProtocolShortcut` | `ui/tests/test_plugins.py` |
| Job status notifications | `QueueDB/notifications.py`, `worker3/queue/job_queue.py`, `ui/views/notifications.py` | `ui/tests/test_notifications.py`, `worker3/tests/test_notifications.py` |

## Rules and compatibility to preserve

- Keep UI queries, ownership rules, and business operations in `ui/services.py`;
  views parse requests and render pages or partials. Copy existing patterns.
- UI ownership uses the user's profile delegate. Shared reads use `CrossAccess`;
  job writes require ownership or staff access. Use the existing readable/writable
  service helpers and enforce permissions on the server.
- Preserve job locks, termination flags, resume cursors, and audit records when
  changing lifecycle actions. Use `JobStatus` rather than guessing numeric values.
- `{{History:…}}` and `{{CrossAccess:…}}` tokens connect jobs. Changes to token
  handling may affect execution, file selection, and the UI dependency graph.
- Protocol version hashes and job run versions are separate concepts. Check
  `_recompute_protocol_ver`, worker snapshots, and output mappings when changing
  protocols or resume behavior. A stored protocol hash alone does not guarantee
  execution of an immutable historical definition: the worker loads the current
  protocol and warns on version mismatch.
- Preserve on-disk output mapping keys and results path conventions when changing
  the worker; resumed jobs depend on them.
- Older `worker/` and `worker2/` coexist with the default stack. The `ui`
  package still imports `worker.bases`. Legacy lab plugins can live in
  `ui/views/plugins/` and are remounted by `ui.plugins.legacy`. Trace imports
  before changing shared behavior or assuming an older module is unused.
- Keep site-specific additions in the ui plugin hooks (`UI3_PLUGINS` or
  `ui/plugins/local/`); see `ui/AGENTS.md`.

## Configuration and verification

`bioqueue init` (or `python install.py`) sets up a personal install: data folder,
SQLite, and the first account. `bioqueue` starts the web app and worker3 together.
`BioQueue/settings-example.py` is copied to `settings.py` only when that file is
missing. Worker configuration comes from `config/custom.conf`, with
`BIOQUEUE_CUSTOM_CONF` supported by worker3 for an alternate path. Treat local
settings, configuration, databases, and result directories as user data.

Run tests from the repository root with a Python environment containing the
dependencies:

```bash
python manage.py test ui --settings=ui.test_settings
python manage.py test worker3.tests --settings=worker3.test_settings
# Example of a focused suite:
python manage.py test ui.tests.test_jobs --settings=ui.test_settings
```

`ui/run_tests.sh` selects its conda environment. `worker3/run_tests.sh` prefers
the environment in `worker3/pixi.toml`, then `BIOQUEUE_PYTHON` or an active conda
environment. Both suites have isolated SQLite settings. ui's settings stub
optional dependencies and skip historical migrations, so passing its tests does
not validate a schema migration. Check migrations separately for schema changes.

For UI changes, test the full-page and HTMX responses plus ownership failures.
For worker changes, use the scheduler, subprocess, and integration tests relevant
to the behavior. Avoid running a production worker merely to verify a change: it
can claim real queued jobs.

After CSS source changes or templates that need newly generated classes, rebuild
the checked-in stylesheet as described in `ui/AGENTS.md`:

```bash
cd ui
node node_modules/@tailwindcss/cli/dist/index.mjs -i ./static_src/input.css -o ./static/ui3/app.css --minify
```

## Efficient repository exploration

Check `git status --short` before editing and preserve unrelated local changes.
Use focused `rg` searches; exclude `.pixi`, `node_modules`, `__pycache__`, and
`.ipynb_checkpoints` from broad searches. Files named `*conflicted copy*` may be
sync artifacts; start with the canonical module and do not delete these copies
as incidental cleanup.
