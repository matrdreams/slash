#!/usr/bin/env python3
"""CLI entry for the compatibility harness. `slash compat run` calls the same code."""

import sys

from slash.compat.harness import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
