#!/bin/bash
#SBATCH --job-name={JOBNAME}
#SBATCH --cpus-per-task={CPU}
{MEM}
{WALLTIME}
{PARTITION}
{GRES}
{EXCLUDE}
{ARRAY}
{EXTRA}
{CHDIR}
#SBATCH --output={STDOUT}
#SBATCH --error={STDERR}
#SBATCH --open-mode=truncate

set -e
{PROLOGUE}
{PROTOCOL}
{EPILOGUE}
