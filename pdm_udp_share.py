#!/usr/bin/env python3
"""Convenience name for the unchanged shared-line stereo PDM gateware."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().with_name('pdm_udp_stereo_shared.py')), run_name='__main__')
