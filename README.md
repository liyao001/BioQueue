# BioQueue

**Run every analysis in your project, and never lose track of one again.**

BioQueue is a job queue and a project record in one browser app. You write an analysis once as a *protocol*, launch it as *jobs* on your own machine or a cluster, and BioQueue keeps every run's parameters, inputs, logs, and results — plus how the runs feed into each other — organized by project and workspace.

You install it in your own account, the way you would install JupyterLab. No root access, no cluster administrator, no separate database server required.

## Why BioQueue

Most analysis projects end up tracked in a spreadsheet of job IDs, a pile of `nohup.out` and `slurm-1234.out` files, and folder names like `align_v3_final_fixed`. Six months later, nobody can say which parameters produced the figure.

BioQueue replaces that with one place where:

- **Jobs run themselves.** Queue fifty jobs and walk away. BioQueue runs as many at once as your CPU, memory, and disk allow, or submits them to Slurm, LSF, PBS, or HTCondor.
- **Every run is on the record.** Each job keeps its protocol version, parameters, inputs, notes, stdout/stderr, and results folder. Clone it, rerun it, or resume it from the step that failed.
- **The project is a graph, not a folder.** Jobs can take another job's outputs as inputs. BioQueue tracks those links, so you can see what a result was built from and what depends on it.
- **You hear about it when it's done.** Get a message on Slack, Discord, Telegram, email, and others when a job finishes or fails.

## How it fits together

A BioQueue **account is a project**. Everything the project needs lives inside it, and its own folder on disk holds the uploads, results, and archives:

```text
Project (account)            e.g. liver-regeneration
├── Protocols                the methods: trim → align → count
├── References               named paths such as {{hg38}}
├── Environments             conda / venv activations for steps
└── Workspaces               parts of the project: RNA-seq, ATAC-seq, Figure 3
    └── Jobs                 runs: liver_rep1, 8 threads, protocol v3
        └── Results, logs, notes, links to upstream and downstream jobs
```

Protocols, references, and environments are defined once per project and reused by every workspace. Workspaces split the project's jobs into the pieces you think in: an assay, a sub-study, or a figure. Each job is one run of a protocol with its own inputs and parameters.

Separate projects stay separate: each account has its own protocols, jobs, and folder, so starting a new project means starting from a clean slate rather than a longer list.

## Highlights

**Write the pipeline once, run it on every sample.** A protocol template describes the per-sample steps once, then the steps that combine all samples. Give a job eight paired-end FASTQ files and BioQueue expands the template into the right commands for four samples, then merges. See [Protocol templates](docs/protocol-templates.md).

**Launch many jobs at a time.** Create a single job, paste a table of jobs, upload a job file, or create an array job with one child per input.

**Chain analyses.** Pick a previous job's output when you create a job, or reference it with a `{{History:…}}` token. BioQueue waits for the upstream job, and the DAG explorer shows the whole chain: what a job depends on and everything built from it.

**Catch problems before they cost hours.** Before the first step runs, the worker checks that the input files exist and that upstream jobs did not fail.

**Recover without starting over.** Resume from the failed step or any step you choose, rerun in place or from a clean folder, and compare a job's parameters with another job or its protocol with the current version.

**Browse results in the browser.** Open a job's results folder to preview, download, rename, or delete files, read its stdout and stderr, or archive the folder when the project is done.

**Size jobs from history.** BioQueue learns how much CPU, memory, and disk each step used before and estimates what the next run needs, so it can pack concurrent jobs without overcommitting the machine.

**Scale when you need to.** The same protocols run locally or on Slurm, LSF, Torque/PBS, or HTCondor. Slurm jobs can also be submitted over SSH from another machine. Named runners let you send specific jobs to specific machines.

**Many projects, one install.** One BioQueue instance can hold several projects, one account each, sharing the same worker and cluster settings. Within a project, each job can be hidden, visible, or shown only in its workspace.

## Get started

You need Python 3.9 or newer.

```bash
pip install bioqueue
bioqueue init
bioqueue
```

Or with conda:

```bash
conda install -c conda-forge bioqueue
bioqueue init
bioqueue
```

A pip install also needs the `libmagic` library (`brew install libmagic` on macOS, or the `libmagic` package on Linux). The conda package includes it.

`bioqueue init` asks for an account name and password, and nothing else. That account is your first project. It creates a data folder at `~/BioQueue` (pass `--data` for another path), uses SQLite, and sizes the worker to this machine's CPU, memory, and disk. The site and the worker share that database file. BioQueue uses WAL mode and waits up to 30 seconds when the other process is writing, so a personal install does not hit the old "database is locked" errors. `bioqueue` with no arguments does the same setup on first run, then starts the web app and the worker together.

For PostgreSQL or MySQL, see [PostgreSQL and MySQL](docs/databases.md). Install `bioqueue[postgres]` or `bioqueue[mysql]`, create an empty database, and export `BIOQUEUE_DB_ENGINE` and the other `BIOQUEUE_DB_*` variables before `bioqueue init`.

To run from a checkout, install [Pixi](https://pixi.sh), then:

```bash
git clone https://github.com/liyao001/BioQueue.git
cd BioQueue
pixi run bioqueue init
pixi run bioqueue
```

Pixi creates the environment and installs `libmagic` with it.

Open <http://127.0.0.1:8000/> and sign in. Create a workspace and a protocol, then a job, and watch it run on the dashboard.

To start another project, add an account under **Users** in the user menu and sign in as it.

`Ctrl-C` stops both processes. `bioqueue worker` and `bioqueue serve` start them separately. `python install.py` is the same as `bioqueue init`.

## Going further

- **Cluster submission**: set the cluster type and resources in `config/custom.conf`; the worker then submits steps to the scheduler instead of running them locally.
- **Worker options**: `python -m worker --help` covers scheduling policy (`--schedule greedy|fifo`), resource estimation, and binding a worker to a named runner (`--runner`).
- **Notifications**: [set up job alerts](docs/notifications.md).
- **Lab use**: `bioqueue --host 0.0.0.0` or Apache/nginx, and [PostgreSQL or MySQL](docs/databases.md) instead of SQLite. SQLite still allows only one writer at a time, so a shared install should not use it. Colleagues sign up for their own projects at `/ui/register/` (an admin activates new accounts).

All documentation is in [`docs/`](docs/README.md).

## Citation

If BioQueue helps your research, please cite:

Yao, L., Wang, H., Song, Y. & Sui, G. BioQueue: a novel pipeline framework to accelerate bioinformatics analysis. *Bioinformatics* 33, 3286–3288 (2017). [doi:10.1093/bioinformatics/btx403](https://doi.org/10.1093/bioinformatics/btx403)

## License

Apache License 2.0. See [LICENSE](LICENSE).
