# {JOBNAME}
executable               = {PROTOCOL}
log                      = {STDOUT}
output                   = {STDOUT}
error                    = {STDERR}
initialdir               = {WORKSPACE}
request_cpus             = {GLOBAL_MAX_CPU_FOR_CLUSTER}
should_transfer_files    = Yes
when_to_transfer_output = ON_EXIT
{MEM}
queue