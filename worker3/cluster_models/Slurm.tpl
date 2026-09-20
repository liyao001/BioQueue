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

set -e
{PROLOGUE}
{PROTOCOL}
{EPILOGUE}
