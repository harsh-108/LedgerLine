#!/usr/bin/env python3
"""Kept for old habits — this is now scripts/reset_password.py."""
import runpy, pathlib
runpy.run_path(str(pathlib.Path(__file__).with_name("reset_password.py")),
               run_name="__main__")
