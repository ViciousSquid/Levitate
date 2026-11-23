#!/usr/bin/env python3
"""Command-line random maze generator: see tools/procedural_map_gen.py,
which this runs."""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from tools.procedural_map_gen import generate_map_to_file, run_cli  # noqa: E402,F401

if __name__ == "__main__":
    run_cli()
