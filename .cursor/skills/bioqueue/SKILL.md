---
name: bioqueue
description: >-
  Run and inspect BioQueue analyses through the /api/v1/ HTTP API: create
  protocols, create jobs, poll status, read logs, and download results. Use
  when the user asks to write or import a BioQueue protocol, run a
  bioinformatics job or protocol in BioQueue, queue an analysis, check a
  BioQueue job, read its log, or chain a job to an earlier result.
---

# Use BioQueue

Drive a running BioQueue through `GET` and `POST /api/v1/`. A session cookie is rejected. Full field lists are in [reference.md](reference.md).

## Connect

1. Base URL: `BIOQUEUE_URL`, or `http://127.0.0.1:8000`.
2. Token: `BIOQUEUE_TOKEN`. Send `Authorization: Bearer $BIOQUEUE_TOKEN`.
3. If the variable is missing or the response is 401, ask the user for the key on **Account** (`/ui/account/`). Do not invent one, and do not rotate it unless they ask.
4. Confirm with `GET /api/v1/`.

Pass the token with an environment variable in the header. Do not write it into the repo, a job comment, or a command that gets committed.

## Submit one job

1. `GET /api/v1/protocols/`, `/workspaces/`, and `/runners/`. Use an id or a unique name. If `has_more` is true, do not guess at protocols past the page; ask for an id.
2. If the protocol does not exist, create it with the steps in **Create a protocol**. Importing the same name again is an error.
3. `POST /api/v1/jobs/` with `job_name`, `protocol`, and the inputs. Optional: `parameter`, `input_file`, `workspace`, `comments`, `is_gpu_job`, `array_setting`, `sample_sheet`, `runner`. Unknown fields are a 400.
4. Send `Idempotency-Key` on every create and import. Use a stable key for that logical run, such as `liver-rep1`. Retry a lost response with the **same key and the same body**. The first response is returned again, including its job id. A different body with that key is 409; choose a new key only when the request itself changed. A 409 that says the key is in progress means the first request is still running: wait, then retry the same request. An abandoned claim can be retried after two minutes.

`parameter` is `name=value;` repeated, for example `threads=8;`. `sample_sheet` is only valid on a protocol that has a template; its shape is in [reference.md](reference.md). `job_name` is at most 100 characters.

Job creation returns 201 and `{"job": {...}}`. The new job stays **Waiting** until the worker claims it.

## Create a protocol

Import creates a protocol. There is no edit endpoint, and a second import of the same name is an error. Read [reference.md](reference.md) before writing the JSON.

1. `GET /api/v1/protocols/`. When one is close, `GET /api/v1/protocols/<id>/` and start from that document.
2. Use a **step protocol** (`step`) for one ordered command list. Use a **template** (`samples`, `blocks`, `pipeline`) when the same commands run once per sample and a later command sees every sample.
3. `POST /api/v1/protocols/import/` with `Idempotency-Key`. Send the document, or `{"protocol": <document>}`.
4. On 201 the protocol exists. `missing_references` names tokens that will not become paths, because this account has no reference of that name. `unchanged_environments` names recipes that were left as already stored. To change a protocol, import a new name.

The worker runs `software`, a space, then `parameter`. Leave placeholders in `parameter`. A step with an empty `software` is dropped, so check the saved document with `GET /api/v1/protocols/<id>/`. A template rejects a missing software name. Import stores `software`, `parameter`, `step_order`, `env`, and `version_check`. On a `step` list it ignores `force_local` and `gpu_step`; a template step keeps them. `env` must name an environment that exists, or one created by the document's `environment` object. Import stores that recipe and does not run it. The `reference` object does not create reference files. `{{Script:…}}` and `{{Asset:…}}` need files already attached on the Protocols page; this API cannot upload them.

```json
{
  "name": "trim-reads",
  "description": "Trim the first input file.",
  "step": [
    {
      "software": "fastp",
      "parameter": "-i {{InputFile:1}} -o {{JobName}}.fq.gz -w {{ThreadN}}",
      "version_check": "fastp --version"
    }
  ]
}
```

A multi-line script sets `software` to `__SHELL__` and puts the script in `parameter`. The tag is not part of the script. Placeholder and template fields are in [reference.md](reference.md).

## Submit many jobs

`POST /api/v1/jobs/batch/` with `{"tsv": "...", "workspace": <id or name>}`. Columns, tab-separated:

```text
protocol_id	job_name	input_file	parameter	array_setting	is_gpu
```

`protocol_id` is numeric. The last two columns are optional.

- **201** — every row was created.
- **207** — some rows were created. Read `errors` and do not resubmit the rows already in `jobs`.
- **400** — nothing was created.

## Wait, then read the outcome

Poll `GET /api/v1/jobs/<id>/` every few seconds. Stop on a terminal `status`:

| status | label | What to do |
| --- | --- | --- |
| 0 | Waiting | Keep polling |
| -2 | Waiting for resources | Keep polling |
| 1 | Running | Keep polling |
| -1 | Finished | List and download results |
| -3 | Failed | Read both logs |
| 2 | Interrupted | Read both logs |

Logs: `GET /api/v1/jobs/<id>/logs/?kind=stdout` and `kind=stderr`. `text` is chronological. When `truncated` is true, `text` is the tail.

Files: `GET /api/v1/jobs/<id>/files/`, then `GET .../files/download/?name=` with the relative `name` from that list. Do not send absolute paths or `..`.

`scope=all` on the job list includes jobs shared with this account. The default list is the account's own jobs.

## Chain a follow-up job

Put the upstream file in `input_file`:

```text
{{History:JOBID-relative/name}}
```

BioQueue waits until that job succeeds. `GET /api/v1/jobs/<id>/dag/?up=1&down=1` returns the jobs this run depends on and the jobs built from it.

## When a call fails

The body is `{"error": "..."}` with an HTTP 4xx. Fix the request the message names. A 404 means the job or protocol is missing or belongs to another account. A 500 that mentions `api_idempotency` means this install has not applied the migration (`python manage.py migrate`).
