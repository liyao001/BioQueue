# ui3 – HTMX + Tailwind (DaisyUI) frontend

Server-rendered UI for core BioQueue flows: **Jobs**, **Protocols**, **References**, **Workspaces**, and **Virtual Environments**.
It is the default frontend (`/` redirects to `/ui/`). The Python package is still `ui3`. See [`CHANGELOG.md`](CHANGELOG.md).

**Agents and new contributors:** start with [`AGENTS.md`](AGENTS.md) (layout, HTMX contract, how to add a page). Product leftovers are in [`TODO.md`](TODO.md).

## Why Tailwind + DaisyUI (not Chakra)

Chakra UI is a React component library and cannot drive Django templates.
ui3 uses **HTMX** for interactions and **DaisyUI on Tailwind** for buttons, tables, modals, and badges.

## Run

1. Add `'ui3'` to `INSTALLED_APPS` (already done in `settings-example.py`).
2. Include URLs (already in `BioQueue/urls.py`):

   `path('ui/', include('ui3.urls'))`

3. Start Django and open `/` (redirects to `/ui/`) or `/ui/login/`.

Compiled CSS lives in `static/ui3/app.css` (checked in so tests and production do not need Node).
Rebuild after template or `static_src/input.css` changes:

```bash
cd ui3 && npm install && npm run build:css
```

HTMX and Font Awesome still load from CDNs in `templates/ui3/base.html`.

## Tests

Uses an isolated SQLite settings module so Postgres/Celery are not required:

```bash
# conda env created for this app (Django 4.2)
conda activate bioqueue-ui3

# or any env with Django 4.2+
python manage.py test ui3 --settings=ui3.test_settings
```

## Scope

Included now:

- Session login/logout
- Job list (card view), multi-status + scope filters, polling, lock-aware actions
- Rerun / terminate / lock / delete / GPU / visibility, parameter/input/comments edit, clone-to-new
- Job file browser (list, sort/filter, load-more append, preview, download, delete)
- Bulk select + terminate / rerun / delete
- History / rename / dependents / dependencies modal wiring
- Protocol list, create (with draft steps), rename, clone, delete, step CRUD/reorder
- Reference list/create/edit/delete
- Workspace and virtual environment CRUD
- Job-card inline workspace / runner / array-setting edits
- Compiled Tailwind + DaisyUI stylesheet
- DAG explorer (Cytoscape JS island; graph data from `/ui/dag/graph/`)
- Site plugin hooks (mounted on `/ui/…`; protocol shortcut presets). Lab Dec/WandB still live in `ui/views/plugins/` and are remounted by `ui3.plugins.legacy`. New plugins: gitignored `ui3/plugins/local/` or `UI3_PLUGINS`.

Deferred (see `TODO.md` and [`CHANGELOG.md`](CHANGELOG.md)):

- Optional table view and keyboard shortcuts
- Samples, learning/predictions UI, and share-with-peer (still on `/ui/` only)
