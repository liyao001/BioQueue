# ui3 changelog

## 2026-10-02 — Notification hooks

Account menu → Notifications. Each user can add Discord, Telegram, Slack, Teams, Mattermost, ntfy, Gotify, Pushover, email, or a generic webhook. worker3 sends them when a job starts, finishes, fails, or is interrupted. See `docs/notifications.md`.

## 2026-09-30 — Collapse protocol shortcuts by default

The shortcuts section on the protocol editor starts closed. Opening it stays open for that protocol while you keep editing the page.

## 2026-09-30 — Drag protocol steps to reorder

On an editable protocol, the grip at the left of a step row can be dragged to a new position. The new order is saved in one request, and the step editor stays in place so another step can be added without reloading. The up and down buttons still work.

## 2026-09-29 — Stop filter query params from multiplying in the URL

Pager links used to put the current query string into `hx-get` *and* `hx-include` the filter form. Each page click duplicated empty `q=` / `protocol=` values until the address bar ballooned. Pager navigation now sends `page` via `hx-vals` only; empty and duplicate query keys are compacted server-side and stripped before HTMX pushes the URL.

## 2026-09-29 — Restore `/ui/mark-finished`

The old Bootstrap UI exposed `GET /ui/mark-finished?job_id=…` (JSON). After ui3 took `/ui/`, that path 404’d. It is back as a compatibility endpoint: marks the job finished via `set_done()`, writes `.snapshot.ini` when a results folder exists, and returns the same success JSON shape for API clients. Protocol shortcuts that point at mark-finished are rendered as HTMX posts (same as the job-card button) so the menu no longer opens a JSON tab. Browser navigations to the legacy URL redirect back to the job list; HTMX requests refresh the list in place.

## 2026-09-20 — Wide edit modals

Job field edits (parameter, input, comments), protocol step edits, shortcuts, environments, workspaces, and references use `ui-modal-lg ui-modal-editor`. Mono textareas fill the dialog (min 16rem tall) so long commands and paths are easier to edit. Rename/resume stay small.

## 2026-09-20 — Lock job UI while deleting files

Deleting (or purging / clean-rerunning) a job can take a while because result files are removed on the server. While that request is in flight the whole job card is locked — not just the delete button — and auto-refresh / filters / bulk actions cannot swap the list out from under it. Bulk delete locks the results panel.

## 2026-09-18 — Default UI at `/ui/`

The HTMX app is the site UI. Browser paths are `/ui/…` (jobs, login, plugins). `/` redirects to `/ui/`. Old `/ui3/…` bookmarks redirect to the same path under `/ui/`.

The Python package is still named `ui3` (`reverse("ui3:jobs")`, `templates/ui3/`, `static/ui3/`). That is not the public URL.

The old Bootstrap `ui` **views are unmounted**. The `ui` package stays in the tree for:

- Lab Dec / WandB views (`ui/views/plugins/`), remounted on `/ui/` via `ui3.plugins.legacy`
- `ui/cron_jobs.py` + `ui/cron_runner.py`
- Django admin registrations in `ui/admin.py`
- `ui.tools.success` / `error` (accounts login JSON)
- `maintenance_protocols/` (reference install helpers, unused by ui3)

Do not delete `ui/` until those move. `ui2` / `ui2-frontend` are still not mounted.

### `ui.tools` callers (outside `ui/` itself)

| Caller | Symbols | Now |
| --- | --- | --- |
| `worker/feedback.py` | `os_to_int` | `worker.bases.os_to_int` |
| `worker/cluster_models/HTCondor.py` | `os_to_int` | `worker.bases.os_to_int` |
| `ui3/services.py` (`rename_job`) | `rename_job_files` | `ui3.files.rename_job_files` |
| `accounts/views.py` | `success`, `error` | still `ui.tools` (JSON login for `/accounts/`) |

Inside `ui/`, Job/Protocol/Misc/Samples/Shield/References still import the rest of `ui.tools`.

### Plugins

`ui/views/plugins/urls.py` (Dec, WandB, ABC, …) is included at **`/ui/`**, so shortcuts like `/ui/dec-eval-runs/{id}` keep working. New plugins: `ui3/plugins/local/` with hrefs under `/ui/…` (not `/ui/ext/…`).

### Not ported (gone from the UI until someone rebuilds them)

| Area | Old URL | What it did |
| --- | --- | --- |
| **Samples** | `/ui/register-sample/`, `/ui/query-job-sample/` | Register experiment files as `Sample` rows |
| **Learning** | `/ui/show-learning/`, `/ui/fetch-learning/` | Browse/import `Prediction` resource models |
| **Share** | `/ui/share-with-peer/` | Clone a protocol + steps onto another account |

Job **scope=shared** (CrossAccess) is in ui3; that is not share-with-peer.
