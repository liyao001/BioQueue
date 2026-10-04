#!/usr/bin/env python
"""Set up a personal BioQueue install. Same as ``bioqueue init``."""
import sys

from BioQueue.cli import main

if __name__ == "__main__":
    raise SystemExit(main(["init", *sys.argv[1:]]))
