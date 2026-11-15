#!/usr/bin/env python3
"""Convenience name; the unchanged capture implementation is shipped beside it."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().with_name('capture_pdm_udp_lossy.py')), run_name='__main__')
