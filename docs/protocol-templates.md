# Protocol templates

A normal BioQueue protocol is a list of commands. That list gets long when the same commands run on each replicate and only the filenames change. A **protocol template** is the short form of that protocol: describe the samples, write the repeated commands once, then write the steps that combine the samples.

The worker still runs an ordered list of commands. When a job starts, BioQueue expands the template for that job's samples and runs the result. Resume, logs, and the step counter use that expanded list.

An ordinary protocol JSON file, one with a `step` list and no `pipeline`, is unchanged. Import a template from the Protocols page with **Import JSON**.

## The shape of a template

A template JSON file has the usual `name` and `description`, plus three sections:

| Section | What it is |
| --- | --- |
| `samples` | How input files become sample records, and which fields differ between samples |
| `blocks` | Named groups of commands you can call more than once |
| `pipeline` | The order of work: steps that run once, a pass over every sample, then steps that see every sample |

```json
{
  "name": "paired_preprocess",
  "description": "Trim and align each sample, then merge the BAMs.",
  "samples": {
    "group": 2,
    "name": "rep{{index}}",
    "fields": {
      "umi_len": "{{UMI_LEN||6}}"
    }
  },
  "blocks": {
    "align": {
      "steps": [
        {
          "software": "fastp",
          "parameter": "-i {{sample.r1}} -I {{sample.r2}} --umi_len={{sample.umi_len}} -o {{sample.prefix}}.fq.gz",
          "outputs": { "clean": "{{sample.prefix}}.fq.gz" }
        }
      ]
    }
  },
  "pipeline": [
    { "software": "fastqc", "parameter": "{{InputFile}}" },
    { "map": "samples", "steps": [ { "call": "align" } ] },
    {
      "software": "samtools",
      "parameter": "merge -fh {{samples.first.clean}} {{JobName}}_merged.bam {{samples.clean}}",
      "outputs": { "merged_bam": "{{JobName}}_merged.bam" }
    }
  ]
}
```

`{{JobName}}`, `{{InputFile}}`, and `{{UMI_LEN||6}}` are still filled in when the step runs, the same way as in a normal protocol. The template fills in sample names and which file belongs to which sample before that.

## Samples

`samples.group` is how many input files belong to one sample. Paired-end reads use `2`: file 1 and file 2 are sample 1, file 3 and file 4 are sample 2. Single-end reads can omit `group`; it defaults to `1`.

Input files on the job are separated with semicolons, in sample order:

```text
rep1_R1.fq.gz;rep1_R2.fq.gz;rep2_R1.fq.gz;rep2_R2.fq.gz
```

The file count must divide evenly by `group`. Four files and `group: 2` make two samples. Three files in that protocol is an error.

`samples.name` is the default sample name. `rep{{index}}` produces `rep1`, `rep2`, and so on. `index` starts at 1.

Each sample record starts with these fields:

| Field | Meaning |
| --- | --- |
| `index` | `1`, `2`, … |
| `name` | From `samples.name`, or from the sample sheet |
| `prefix` | `{{JobName}}_` plus the sample name, so `{{JobName}}_rep1` |
| `r1`, `r2`, … | That sample's files, in order. Inside a template these stay as `{{InputFile:1}}`, `{{InputFile:2}}`, and so on, until the job runs |
| `files` | The same paths in one space-separated string |

`samples.fields` adds anything else that can differ per sample. A value can be a job parameter, including a default:

```json
"fields": {
  "umi_len": "{{UMI_LEN||6}}",
  "umi_loc": "{{UMI_LOC||per_read}}"
}
```

The PROcap example goes one step further and keeps the old numbered parameters. `{{UMI_LEN{{index}}||6}}` becomes `{{UMI_LEN1||6}}` for the first sample and `{{UMI_LEN2||6}}` for the second. The Parameters box on the new-job page lists those keys.

You can also give every sample the same parameter and override one sample in the sample sheet, described below.

## Blocks

A block is a named list of commands. Call it from the pipeline instead of pasting the commands again.

```json
"blocks": {
  "align": {
    "steps": [
      {
        "software": "STAR",
        "parameter": "--readFilesIn {{sample.clean_r1}} {{sample.clean_r2}} --outFileNamePrefix {{sample.prefix}}_",
        "version_check": "STAR --version",
        "outputs": {
          "aligned_bam": "{{sample.prefix}}_Aligned.sortedByCoord.out.bam"
        }
      }
    ]
  }
}
```

`outputs` records a filename under a name you choose. The value is the path the command is expected to write. BioQueue does not discover new filenames from the tool. The same explanation is on the protocol page, in **How later steps use an output**.

Where the name is stored depends on where the command runs:

| Where the command runs | Where the name is stored | How a later command reads it |
| --- | --- | --- |
| Inside a sample map, or in a block called from that map | On that sample | `{{sample.aligned_bam}}` in a later command for the same sample. After the map, `{{samples.aligned_bam}}` lists every sample, `{{samples.first.aligned_bam}}` and `{{samples.last.aligned_bam}}` pick one end, and `{{samples.2.aligned_bam}}` is sample 2 |
| After the map, or in a block called from there | Once, for the whole job | `{{shared.merged_bam}}` |

A block stores its outputs the same way as the place it is called. A block argument is separate: `bam = {{sample.dedup_bam}}` on the call is read inside the block as `{{bam}}`, and that value is filled in before the block starts.

A command can also set:

| Field | Meaning |
| --- | --- |
| `version_check` | Command run before the step, same as on a normal step |
| `env` | Name of an existing virtual environment. An environment you own is used before a public one with the same name. The name is literal |
| `force_local` | `true` or `false`. Run on the worker machine |
| `gpu_step` | `true` or `false` |

A block can take arguments. Inside the block, `{{bam}}` is the value passed at the call:

```json
"pints": {
  "steps": [
    {
      "software": "pints_visualizer",
      "parameter": "-b {{bam}} -o {{JobName}}_{{tag}} {{flags}}"
    }
  ]
}
```

```json
{ "call": "pints", "args": { "bam": "{{sample.dedup_bam}}", "tag": "{{sample.name}}_rpm", "flags": "--rpm" } }
```

The same block can be called again after the samples are merged, with the merged file as `bam`. Arguments are substituted at the call, so `{{sample.dedup_bam}}` is resolved before entering the block.

A block may call another block. A block may not call itself, directly or through a loop of calls.

## Pipeline

`pipeline` is the order of the whole protocol. Each entry is one of three things.

**A command.** It runs once. Use this for setup and for anything that is not per-sample. `{{InputFile}}` here is still every input file.

```json
{ "software": "mkdir", "parameter": "raw_qc" }
```

**A sample map.** Its steps run once per sample, in sample order. Finish sample 1 before sample 2 starts. Maps do not nest, and a map is only allowed at the top of the pipeline, not inside a block.

```json
{ "map": "samples", "steps": [ { "call": "process_sample" } ] }
```

Inside the map, and inside blocks called from the map, `{{sample.field}}` is the sample currently running.

**A command or block call after the map.** This is the join. It sees every sample:

| Placeholder | Expands to |
| --- | --- |
| `{{samples.dedup_bam}}` | Every sample's `dedup_bam`, in order, separated by spaces |
| `{{samples.first.dedup_bam}}` | The first sample only |
| `{{samples.last.dedup_bam}}` | The last sample only |
| `{{samples.2.dedup_bam}}` | Sample 2 (the number starts at 1) |
| `{{samples.prefix}}` | `{{JobName}}_rep1 {{JobName}}_rep2` for the default names |

`samtools merge` needs both the header source and the full list. This is the same command the hand-written two-replicate protocol used, and a third sample adds a third file without copying the step:

```json
{
  "software": "samtools",
  "parameter": "merge -fh {{samples.first.dedup_bam}} {{JobName}}_merged.bam {{samples.dedup_bam}}",
  "outputs": { "merged_bam": "{{JobName}}_merged.bam" }
}
```

`outputs` on a step outside the map is shared, not stored on a sample. Later steps read it with `{{shared.merged_bam}}`. The PROcap template does this for the merged BAM and for the `multiBamSummary` matrix, then passes those paths into the reporting commands.

`{{sample.field}}` is only valid inside a map. A join step uses `{{samples.field}}` or `{{shared.field}}`.

## Create a job

1. Import the JSON, or build the template on the Protocols page. **Save protocol** stores it. While you edit, **Expanded preview** follows the unsaved draft. Its sample count defaults to 2 and can be set from 1 to 8; that count is only for the preview. The job uses however many samples its input files make. A command with no software name makes the preview ask for a correction until the name is filled in.
2. Create a job with that protocol. Template protocols are marked **Template** in the protocol list and in the job's protocol picker.
3. Put the fastq files in **Input files**, semicolon-separated, in sample order. If the file count does not divide evenly by files per sample, the page says so and leaves the Samples box as it is.
4. The **Samples** box is filled in for a template. Clear it to let BioQueue name the samples from the input files. Edit a row to rename one sample or replace one field. The page shows how many samples and steps will run, and which input files belong to which sample.

With `group: 2` and four files, BioQueue builds `rep1` and `rep2` itself. **Parameters** holds job-wide values, including one key per sample when a field uses `{{UMI_LEN{{index}}||6}}`. A placeholder left in a Samples row reads that parameter; it is not a second copy of the value. Empty parameter keys are listed under the Parameters box.

The **Samples** box is a JSON list, one object per sample. Use it to override fields without listing files again:

```json
[
  { "name": "rep1" },
  { "name": "rep2", "umi_len": "8" }
]
```

Sample 2 then uses `8` instead of `{{UMI_LEN||6}}`. Fewer rows than samples is fine: the extra samples keep the defaults. More rows than input groups is an error.

To point at files from the sample list instead of **Input files**, put `r1` and `r2` on **every** row (or a `files` array on every row). Mixing rows that have files with rows that do not is an error.

```json
[
  { "name": "rep1", "r1": "/data/a_R1.fq.gz", "r2": "/data/a_R2.fq.gz" },
  { "name": "rep2", "r1": "/data/b_R1.fq.gz", "r2": "/data/b_R2.fq.gz" }
]
```

Those paths are used as written. Sample names should be unique and safe in a filename: letters, digits, underscores, or hyphens.

On a job card, **Samples** edits the same list later. The expanded step count follows the current inputs and sample list.

## Create a template in the browser

Open **New Template** from the Protocols page or the Protocol menu.

The page starts from a small sample-aware draft: one reusable block and a pipeline map that calls it once per sample. **Pipeline** is above **Reusable blocks**. Edit samples, commands, calls, and the sample map in the form. Sample fields, outputs, and block arguments are name/value rows. **How later steps use an output** explains how a filename recorded on one command is read later. **Advanced JSON** remains available for hand edits. Nothing is stored until **Create protocol**.

You can still create a template by importing a JSON file with a `pipeline` key, or by editing an existing template after import.

## Edit a template in the browser

On the Protocols page, select a template protocol.

- **Expanded preview** is at the top of the editor and follows the unsaved draft. Change **Preview sample count** to redraw it. That number is not saved.
- **Sample grouping and fields** edits files per sample (`samples.group`), the default name, and extra fields.
- **Pipeline**, then **Reusable blocks**, edit commands, calls, and the sample map. Add, remove, and the arrow buttons change the draft. Adding a command, block call, sample map, or block scrolls to the new entry. Removing an entry or a block asks first. A block can be removed only after its calls are gone.
- Collapsed commands show a short parameter or argument line, so two steps with the same software name can be told apart.
- **Advanced JSON** edits the same draft as text. **Back to forms** applies it. **Format JSON** pretty-prints it.

Nothing is stored until **Save protocol**. Invalid JSON, a missing software name, a missing block, a `{{sample…}}` placeholder outside the map, a placeholder one edit away from a declared name, or an unknown environment name cannot be saved. A name with no near match, such as `{{sample.condition}}`, can still be required metadata on the job. Leaving the page with unsaved draft changes asks before the draft is discarded. The running-job count in the header does not.

## What the worker runs

Expansion happens when the worker claims the job. Placeholders such as `{{JobName}}`, `{{ThreadN}}`, `{{Workspace}}`, `{{History:…}}`, and `{{STAR_INDEX}}` are resolved then, command by command, as they are for a normal step.

Within one job the expanded steps run in order: the whole first sample, then the whole second sample, then the join. Two samples do not run at the same time inside that job.

The resource-learning hash is taken from the command text before sample names are filled in. The two STAR steps in a two-replicate job share one checkpoint.

At most 500 samples and 5000 expanded steps are accepted. A template that cannot be expanded marks the job failed instead of leaving it waiting.

Editing the template and saving it changes the protocol version. A job already created keeps the version it was given; the worker warns if that no longer matches the saved template. The expansion itself is computed from the current template and that job's samples when the job runs.
