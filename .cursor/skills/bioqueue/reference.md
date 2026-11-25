# BioQueue agent API

Base path `/api/v1/`. Header `Authorization: Bearer <api_key>`. Failures are `{"error": "..."}`.

## Endpoints

| Method | Path | Result |
| --- | --- | --- |
| GET | `/api/v1/` | Discovery document |
| GET | `/api/v1/jobs/` | `jobs`, `page`, `page_size`, `total`, `has_next` |
| POST | `/api/v1/jobs/` | 201 `{"job": {...}}` |
| POST | `/api/v1/jobs/batch/` | 201, 207, or 400. Body has `created`, `errors`, `jobs` |
| GET | `/api/v1/jobs/<id>/` | `{"job": {...}}` |
| GET | `/api/v1/jobs/<id>/logs/?kind=stdout\|stderr` | `kind`, `text`, `truncated`. `unavailable` when the file cannot be read |
| GET | `/api/v1/jobs/<id>/files/` | `items` of `name`, `size`, `size_label`, `created`, `is_link` |
| GET | `/api/v1/jobs/<id>/files/download/?name=` | File bytes |
| GET | `/api/v1/jobs/<id>/dag/?up=&down=&max_nodes=` | `root`, `nodes`, `edges` (`from`, `to`), `truncated` |
| GET | `/api/v1/protocols/` | `protocols`, `total`, `has_more` (capped at 500) |
| GET | `/api/v1/protocols/<id>/` | Protocol JSON |
| POST | `/api/v1/protocols/import/` | 201 `protocol`, `missing_references`, `unchanged_environments` |
| GET | `/api/v1/workspaces/` | `workspaces` of `id`, `name` |
| GET | `/api/v1/runners/` | `runners` of `id`, `name`. No SSH fields |

List filters match the job monitor: `q`, `status`, `protocol`, `workspace`, `job_name`, `scope` (`own`, `shared`, `all`), `page`, `page_size` (max 100).

## Job record

`id`, `job_name`, `protocol`, `protocol_name`, `protocol_ver`, `parameter`, `input_file`, `sample_sheet`, `comments`, `status`, `status_label`, `workspace`, `workspace_name`, `runner`, `runner_name`, `is_gpu_job`, `locked`, `visibility`, `resume`, `result`, `parent_job`, `create_time`, `update_time`.

`protocol`, `workspace`, and `runner` on create accept an id or a unique name. Several rows with the same name is an error; pass the id.

## Status

| Value | Label |
| --- | --- |
| -3 | Failed |
| -2 | Waiting for resources |
| -1 | Finished |
| 0 | Waiting |
| 1 | Running |
| 2 | Interrupted |

## Create body

```json
{
  "job_name": "liver_rep1",
  "protocol": "RNA-seq",
  "parameter": "threads=8;",
  "input_file": "sample.fq",
  "workspace": "figure-3",
  "comments": "",
  "is_gpu_job": false,
  "array_setting": null,
  "sample_sheet": "",
  "runner": "lab-node"
}
```

`job_name` max 100 characters. `array_setting` max 100 characters. `is_gpu_job` accepts a boolean or `1` / `0` / `yes` / `no`.

## Batch

JSON `{"tsv": "<text>", "workspace": <id or name>}` or a raw UTF-8 TSV body. Each line:

```text
protocol_id	job_name	input_file	parameter	array_setting	is_gpu
```

At least four columns. `errors` entries are `{"line": <n>, "error": "..."}`. On 207 the successful rows are already queued.

## Protocol JSON

`POST /api/v1/protocols/import/` creates an owned protocol. The body is the document, or `{"protocol": <document>}`. `name` is required, unique for this account, and at most 500 characters. `description` is optional. Exported `ver` and step `hash` are ignored and recomputed.

`missing_references` lists names from `reference` that this account does not have. `unchanged_environments` lists environments whose stored recipe was left in place. The protocol is still created.

### Step protocol

One ordered command list. The worker runs `software`, a space, then `parameter`, then replaces placeholders.

```json
{
  "name": "trim-reads",
  "description": "Trim the first input file.",
  "step": [
    {
      "software": "fastp",
      "parameter": "-i {{InputFile:1}} -o {{JobName}}.fq.gz -w {{ThreadN}}",
      "step_order": 1,
      "version_check": "fastp --version",
      "env": "analysis"
    }
  ],
  "reference": { "hg38": "human genome" },
  "environment": {
    "analysis": { "ve_type": "conda", "value": "analysis", "recipe": "fastp" }
  }
}
```

Stored step fields are `software`, `parameter`, `step_order` (default 1, 2, …), `env`, and `version_check`. An empty `software` is skipped, and the protocol can be saved with no steps. `force_local`, `gpu_step`, and `specify_output` on a step-list entry are not stored.

`env` is an environment name. The `environment` object creates a missing row and stores `ve_type` (default `conda`), `value` (default the name), and `recipe`. It does not run the recipe. An owned row with an empty recipe is filled in. A different recipe already stored is left unchanged.

`"software": "__SHELL__"` runs `parameter` as a bash script. The tag is removed before the script runs.

### Placeholders

Job inputs are semicolon-separated. Job parameters are `name=value;` repeated.

| Token | Becomes |
| --- | --- |
| `{{InputFile}}` | Every input path, space-separated |
| `{{InputFile:1}}` | One input path. The number starts at 1 |
| `{{JobName}}` | Job name |
| `{{Job}}` | Job id |
| `{{ThreadN}}` | CPU count for this run |
| `{{Workspace}}` | Job result directory |
| `{{UserBin}}` | This account's `bin` directory |
| `{{KEY}}` | Reference path named `KEY` when one exists; otherwise job parameter `KEY` |
| `{{KEY\|\|default}}` | Job parameter `KEY` when it is non-empty, otherwise `default`. The default may be another token, such as `{{hg38}}` |
| `{{LastOutput}}` | Files created by the previous step, space-separated |
| `{{LastOutput:1}}` | One of those files. The number starts at 1 |
| `{{Output:2-1}}` | File 1 recorded for step 2. Both numbers start at 1 |
| `{{AllOutputBefore}}` | Files recorded by earlier steps, space-separated |
| `{{Suffix:bam}}` | Previous-step files with that suffix |
| `{{History:18-counts.txt}}` | `counts.txt` from job 18. The job waits until 18 succeeds |
| `{{Uploaded:name}}` | A file uploaded for this account |
| `{{Script:trim.sh}}` | A script file already attached to this protocol |
| `{{Asset:regions.csv}}` | An asset file already attached to this protocol |

A reference token is the reference name, `{{hg38}}`. A reference of that name wins over a job parameter of the same name. To let the job override a reference, write `{{GenomeFasta||{{hg38}}}}`. `reference` in the document is `{ "name": "description" }` and does not create the reference row or the file. This API cannot upload `{{Script:…}}` or `{{Asset:…}}` files.

### Template protocol

Use a template when the same commands run once per sample and a later command sees every sample. A document with a `pipeline` list is a template. Import keeps `samples`, `blocks`, and `pipeline` only.

```json
{
  "name": "paired-trim",
  "description": "Trim each pair, then merge the cleaned files.",
  "samples": {
    "group": 2,
    "name": "rep{{index}}",
    "fields": { "umi_len": "{{UMI_LEN||6}}" }
  },
  "blocks": {
    "trim": {
      "steps": [
        {
          "software": "fastp",
          "parameter": "-i {{sample.r1}} -I {{sample.r2}} --umi_len={{sample.umi_len}} -o {{sample.prefix}}.fq.gz",
          "outputs": { "clean": "{{sample.prefix}}.fq.gz" },
          "version_check": "fastp --version",
          "env": "analysis",
          "force_local": false,
          "gpu_step": false
        }
      ]
    }
  },
  "pipeline": [
    { "map": "samples", "steps": [ { "call": "trim" } ] },
    {
      "software": "__SHELL__",
      "parameter": "cat {{samples.clean}} > {{JobName}}_merged.fq.gz",
      "outputs": { "merged": "{{JobName}}_merged.fq.gz" }
    }
  ]
}
```

- `samples.group` is how many input files belong to one sample. Omitted means 1. The job's semicolon-separated file count must divide by `group`.
- Each sample has `index` (from 1), `name` (from `samples.name`, default `rep{{index}}`), `prefix` (`{{JobName}}_` plus the name), `r1`, `r2`, …, and `files`. `samples.fields` adds further values.
- A pipeline entry is a command, a call, or `{ "map": "samples", "steps": [ ... ] }`. The map runs once per sample and finishes one sample before the next. Maps stay at the top of `pipeline`.
- `{ "call": "trim", "args": { "bam": "{{sample.clean}}" } }` passes arguments. Inside the block they are `{{bam}}`, filled in before the block starts. A block may call another block. A block may not call itself.
- `outputs` records a path under a chosen name. It does not discover files the command wrote. Inside the map, a later command for that sample reads `{{sample.clean}}`. After the map, `{{samples.clean}}` lists every sample separated by spaces, `{{samples.first.clean}}` and `{{samples.last.clean}}` pick one end, and `{{samples.2.clean}}` is sample 2. An output outside the map is read as `{{shared.merged}}`.
- `{{sample.field}}` is valid only inside a map. A field one edit away from a declared name is rejected.
- A template step keeps `version_check`, `env`, `force_local`, and `gpu_step` (`true` or `false`). `env` must resolve after the document's `environment` object is imported. A missing software name is a 400.
- Expansion runs when the worker claims the job. At most 500 samples and 5000 steps.

`sample_sheet` on the job is a JSON list, one object per sample. Fewer rows than samples keeps the defaults. More rows than input groups is an error.

```json
[{ "name": "rep1" }, { "name": "rep2", "umi_len": "8" }]
```

To take paths from the sheet instead of `input_file`, put `r1` and `r2` (or a `files` array) on every row. Mixing rows that have files with rows that do not is an error.

Longer template rules are in `docs/protocol-templates.md`.

## Idempotency

`Idempotency-Key` is at most 200 characters. The stored response is replayed with header `Idempotency-Replayed: true`. The same key is scoped to the signed-in account and includes the path and body. A key still in progress is 409. After two minutes an unfinished claim can be retried with the same body.

## Shell

```bash
curl -sS -X POST "$BIOQUEUE_URL/api/v1/jobs/" \
  -H "Authorization: Bearer $BIOQUEUE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: liver-rep1" \
  -d '{"job_name":"liver_rep1","protocol":"RNA-seq","input_file":"sample.fq","parameter":"threads=8;"}'
```
