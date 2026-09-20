"""Resource / dependency checkpoint codes written to waiting jobs."""
from enum import IntEnum


class CheckPoints(IntEnum):
    FINISHING = 0
    DISK = 1
    MEMORY = 2
    CPU = 3
    FORMER = 4
    PEER = 5
    DEPENDENCE = 6
