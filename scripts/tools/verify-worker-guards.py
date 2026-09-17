#!/usr/bin/env python3
"""Offline guard checks for the RISC-V pull-lab worker's behaviour.

The checks live in guards/, one module per area; this stays the entry point
`./run.sh verify` calls.  Rationale: docs/code-notes/W2d-tools.md.

    python3 scripts/tools/verify-worker-guards.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # holds guards

from guards.runner import main

if __name__ == "__main__":
    sys.exit(main())
