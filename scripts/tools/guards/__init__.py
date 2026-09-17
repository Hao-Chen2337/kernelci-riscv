"""The offline guard suite, one module per area of the worker's behaviour.

The entry point stays scripts/tools/verify-worker-guards.py, which calls
guards.runner.main().  Rationale: docs/code-notes/W2d-tools.md.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # scripts/ holds kcilib
