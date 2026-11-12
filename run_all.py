#!/usr/bin/env python3
"""Run unchanged-default worker-loss observations alongside the main experiment sets."""
import pathlib
import subprocess
import sys

BASE = pathlib.Path(__file__).resolve().parent
def launch(*args):
    return subprocess.Popen([sys.executable, str(BASE / 'harness.py'), *args], cwd=BASE)

if __name__ == '__main__':
    long = launch('--experiments', 'F,F-online', '--jobs', '10')
    groups = [launch('--experiments', experiments, '--jobs', jobs)
              for experiments, jobs in [('A', '1'), ('B,C,D', '4'), ('E', '20')]]
    for group in groups:
        result = group.wait()
        if result:
            raise SystemExit(result)
    raise SystemExit(long.wait())
