# ui3 — design principles for agents

Server-rendered BioQueue UI. HTMX for interactions, Tailwind + DaisyUI for look, Django templates for structure. Parallel to `ui/` and `ui2-frontend`. Same QueueDB models and the same ownership / search rules as ui2.

**Read this file before changing `ui3/`. Copy an existing page; do not invent a new stack.**

## 30-second map

| Need | Where |
| --- | --- |
| URL → view | `urls.py` (imports each `views.*` module; `views/__init__.py` is empty on purpose) |
| Queries, visibility, mutations | `services.py` |
| HTMX / filter / toast helpers | `http.py` |
| Auth wrapper | `decorators.py` (`ui3_login_required`) |
| Job result files | `files.py` |
| Pages and partials | `templates/ui3/<area>/` (`list.html` + `_*.html`) |
| Shared chrome + `window.ui3` | `templates/ui3/base.html` (`{% block extra_js %}` for page islands) |
| DAG canvas | `static/ui3/dag.js` + `templates/ui3/dag/explorer.html` |
| Look (source) | `static_src/input.css` → rebuild `static/ui3/app.css` |
| Isolated tests | `tests/` + `test_settings.py` (SQLite, no Postgres/Celery) |

Areas today: **jobs**, **protocols**, **workspaces**, **environments**, **references**, **auth**, **DAG** (Cytoscape island on `/ui3/dag/`; data from `services.build_job_dag`).

## Design principles

1. **HTML over SPA.** New screens are Django templates + HTMX swaps. Do not add React, Vue, or a JS bundler to this app. A small JS island is allowed only when HTMX is the wrong tool (DAG explorer).
2. **Views stay thin.** Views parse the request, call `services` / `files`, and return HTML. Querysets, ownership, and search live in `services.py` so they stay aligned with ui2.
3. **One chrome, many partials.** First load is a full page. Later updates swap a named fragment (`#job-results`, `*_table.html`, `#modal-root`). Errors must not wipe the fragment they did not mean to replace.
4. **Filter state is the URL + `#job-filters`.** Job mutations POST with `hx-include="#job-filters"`. Server recovers query via `list_params()` (`HX-Current-URL`, then POST, then GET). Add new list keys to `LIST_FILTER_KEYS` in `http.py`.
5. **Parity of rules, not of widgets.** Visibility, CrossAccess, locks, staff vs delegate, and search semantics match ui2. The markup does not have to.
6. **Own vs shared vs staff.** `delegate_for(user)` is the QueueDB profile delegate. Reads may include shared jobs (`get_readable_job`, `scope=all`). Writes need ownership or staff (`get_writable_job`). Staff may assign any workspace; runners (`Slave`) are global.
7. **Fail in a toast.** HTMX validation / permission errors use `htmx_error()` (toast into `#toast-root`, HTTP 4xx). Successful mutations return the refreshed partial + `with_toast()`. Full-page POSTs use Django `messages` + redirect.
8. **Desktop first, phone must still work.** Breakpoint is `767px`. Do not break the single-toolbar desktop layout to make mobile collapse work.
9. **Test the contract.** Every new endpoint needs a test: happy path, HTMX partial vs full page, and “other user’s object is forbidden.”

## Request / HTMX contract

```
GET  list          → render_htmx(full, partial, ctx)
GET  modal         → render(_edit_modal.html) into #modal-root
POST action        → mutate; if HTMX: render(partial) + toast [+ OOB empty #modal-root]
POST invalid       → htmx_error("…")   # HX-Retarget #toast-root, do not swap the list
```

Patterns to copy:

- **List refresh after an action:** `_refresh_or_row` in `views/jobs.py`, or workspace edit/delete (render `_table.html`, append OOB closer, `with_toast`).
- **Close a modal after save:** append `'<div id="modal-root" hx-swap-oob="innerHTML"></div>'`.
- **Job list polling:** `#job-results` has `hx-disinherit="hx-swap hx-target hx-push-url"` so child buttons do not inherit `outerHTML` onto the wrong target. Poll every 8s only when `shouldPauseAutoRefresh()` is false (open combo, modal, nav, mobile filters, or a focused field). Mark quiet pollers with `data-ui3-quiet`.
- **Form reset:** `hx-on::after-request="if(event.detail.successful) this.reset()"` — never reset on 400.

Stable swap targets (do not rename without updating every `hx-target`):

- `#job-results` — job cards + pager
- `#modal-root` — one modal at a time
- `#toast-root` — OOB toasts (`partials/toast.html`)
- `#running-badge` — nav running count

## Templates

Naming:

- `list.html` / `new.html` / `login.html` — full pages, extend `base.html`
- `_card.html`, `_table.html`, `_results.html` — swap targets
- `_edit_modal.html`, `_files_modal.html`, … — fragments for `#modal-root`
- `partials/` — pager, toast, running badge

CSS classes (prefer these over raw DaisyUI `btn` / `navbar`):

- `ui-btn`, `ui-btn-primary`, `ui-input`, `ui-select`, `ui-toolbar`
- `ui-combo` / `ui-combo-toggle` / `ui-combo-panel` / `combo-filter` / `combo-list`
- `page-head`, `page-head-sub`, `filter-bar` (simple search pages)
- `job-card`, `icon-btn`, `icon-btn-group`, `job-pager`

Job monitor filters:

- Always-visible: `q`, search, auto-refresh, refresh
- Collapsible on mobile only: add `filter-extra` (and `filter-toggle` / `filter-keep` for order)
- Hidden Filters button on desktop: `.ui-btn.filter-toggle { display: none }`
- **Do not wrap toolbar controls in `display: contents`** — it double-applies flex `gap`

After changing `static_src/input.css` or adding classes that must exist in the compiled sheet:

```bash
cd ui3 && node node_modules/@tailwindcss/cli/dist/index.mjs -i ./static_src/input.css -o ./static/ui3/app.css --minify
```

`app.css` is checked in so tests and production do not need Node.

## Combos (searchable dropdowns)

Copy a job-toolbar or job-card combo. Required pieces:

- Hidden `.combo-value` (or a CSV hidden input for multi-select)
- Toggle calls `ui3.comboToggle(this)`
- Filter input name is **`combo_q`**, with `hx-include="this"` and `hx-params="combo_q"` so the job-list `q` is not sent
- Server: `combo_query(request)` in `http.py`
- Options partial: `jobs/_combo_options.html` → `ui3.comboSelect(this)`
- `hx-disinherit="*"` on the panel so HTMX does not inherit list swap rules
- Enter in the filter input must `preventDefault`

On viewports `< 768px`, and on job-card combos at any width, `ui3` ports the panel to `document.body` and positions it between the header and the sticky pager. Do not implement a second dropdown system.

## JavaScript

All shared page JS is `window.ui3` in `base.html`. Add a function there if several templates need it. Do not add a bundler (no Vite/webpack in this app).

The DAG explorer is the one JS island: Cytoscape from CDN + `static/ui3/dag.js`. Graph JSON is `GET /ui3/dag/graph/?root=&up=&down=&max_nodes=` (`services.build_job_dag`, same History/CrossAccess walk as ui2). Seed search is `GET /ui3/dag/search/?q=`; hydrate IDs with `GET /ui3/dag/jobs/?ids=`. Job cards link to `/ui3/dag/?seeds=<id>`.

Existing helpers you should reuse: `comboToggle` / `comboSelect` / `closeCombos`, `toggleNav` / `closeNav`, `toggleFilters` / `closeFilters`, `shouldPauseAutoRefresh`, `syncStatusCsv`, selection / bulk helpers.

## Mobile (`max-width: 767px`)

Already handled globally — do not re-solve these per page:

- Hamburger nav (`.bq-nav-toggle`, `.bq-header.is-nav-open`)
- Job filters collapse (`.filter-extra` hidden until `.filter-panel.is-open`)
- Inputs at `16px` (no iOS focus zoom)
- Modals as bottom sheets; toasts inset at the bottom
- Combos ported into the safe box between header and pager
- Horizontal page overflow clipped

## Adding a feature (copy this)

1. **Service first.** `visible_*` / `get_owned_*` / `search_*` in `services.py`. Do not filter querysets in the view.
2. **View** in the matching `views/<area>.py`. Decorate with `ui3_login_required` and `require_GET` / `require_POST`. Import the module from `urls.py` — do not re-export in `views/__init__.py`.
3. **URL** under `/ui3/…` with `app_name = "ui3"`.
4. **Templates.** Full page + `_` partial. Reuse `page-head`, `ui-toolbar`, pager, modal shell.
5. **HTMX.** Full GET uses `render_htmx`. Mutations refresh the list/table partial. Errors use `htmx_error`. Job actions include `#job-filters`.
6. **Limits.** Match model `max_length` on the input (`maxlength=`) and reject oversize POSTs with 400.
7. **Test** in `tests/test_<area>.py` using `Ui3TestCase` (`self.login()`, `self.make_job()`). HTMX: `HTTP_HX_REQUEST="true"` and assert no `<html`.
8. **CSS rebuild** if you added classes that must be in `app.css`.
9. **Run** `python manage.py test ui3 --settings=ui3.test_settings` (or `ui3/run_tests.sh`).

## Tests

- Settings: `ui3.test_settings` (in-memory SQLite, stubbed Postgres `ArrayField` / wandb).
- Base class: `ui3.tests.Ui3TestCase`.
- Prefer behavior (status, ownership, partial id, toast/error) over screenshot tests.
- Do not require the live server or Node for the Django suite.

## Do not

- Add React/Chakra or move this app into `ui2-frontend`.
- Put ownership checks only in the template; the view must 403.
- Use the job-search param `q` as the combo filter (use `combo_q`).
- Swap `#job-results` with `innerHTML` on the list poller, or let children inherit that swap (keep `hx-disinherit`).
- Return 200 + a toast for a failed create/update (use 4xx + `htmx_error`).
- Reset forms on failed HTMX requests.
- Wrap flex toolbars in `display: contents` wrappers.
- Commit secrets, or change `test_settings.SECRET_KEY` to a real key.
- Rebuild the DAG explorer as an HTMX list. Graph data is `GET /ui3/dag/graph/`; the canvas is `static/ui3/dag.js` + Cytoscape from CDN.

## Deferred (see `TODO.md`)

- Optional job table view (cards stay default)
- Keyboard shortcuts on the job monitor
