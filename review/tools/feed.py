#!/usr/bin/env python3
"""Run a harness stage with scripted user turns, echoing each turn after the `you>` prompt.

  feed.py <stage.py> <turns.txt>     # one user message per line; the run ends after the last line
Runs the stage unmodified via runpy; only builtins.input is replaced.
"""
import builtins
import runpy
import sys
from pathlib import Path

stage, turns = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).read_text(encoding="utf-8").splitlines()
queue = [t for t in turns if t.strip()] + ["/quit"]


def scripted_input(prompt=""):
    if not queue:
        raise EOFError
    line = queue.pop(0)
    print(f"{prompt}{line}", flush=True)
    return line


builtins.input = scripted_input
sys.path.insert(0, str(stage.parent))
sys.argv = [str(stage)] + sys.argv[3:]
runpy.run_path(str(stage), run_name="__main__")
