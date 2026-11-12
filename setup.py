#!/usr/bin/env python3
"""Fetch source and official image only. Never executes project code on the host."""
import datetime as dt
import json
import pathlib
import random
import re
import subprocess
import urllib.request

BASE = pathlib.Path(__file__).resolve().parent
ROOT = BASE.parents[2]
SCRATCH = ROOT / '.studio/ai-channel/autoloop'
SRC = SCRATCH / 'src'
IMAGE = 'node:24@sha256:9d266751ca3d7fdbe651c878ffd5ad0a42fed49a18c283509267c97f025b7496'

def command(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode:
        raise RuntimeError(f'{args[0]} failed (exit {p.returncode}); no project code executed')
    return p.stdout.strip()

def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request('https://api.github.com/repos/KKKKhazix/agent-autoloop/releases',
                                 headers={'User-Agent': 'vikawork-measurement'})
    with urllib.request.urlopen(req, timeout=60) as response:
        releases = json.load(response)
    stable = [r for r in releases if not r['draft'] and not r['prerelease']]
    latest = max(stable, key=lambda r: tuple(map(int, r['tag_name'].lstrip('v').split('.'))))
    tag = latest['tag_name']
    if not SRC.exists():
        command(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-checkout',
                 'https://github.com/KKKKhazix/agent-autoloop.git', str(SRC)])
    command(['git', '-C', str(SRC), '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', tag])
    sha = command(['git', '-C', str(SRC), 'rev-parse', 'HEAD'])
    old = command(['git', '-C', str(SRC), 'rev-parse', 'v1.7.1^{commit}'])
    command(['docker', 'pull', IMAGE])
    cpu = re.search(r'^model name\s*:\s*(.*)$', pathlib.Path('/proc/cpuinfo').read_text(), re.M).group(1)
    notes = []
    for r in stable:
        if (1, 7, 1) <= tuple(map(int, r['tag_name'].lstrip('v').split('.'))) <= tuple(map(int, tag[1:].split('.'))):
            # Keep release text, not contributor/account metadata or acknowledgements.
            body = '\n'.join(line for line in r['body'].splitlines()
                             if not re.search(r'Thanks|感谢|Contributors|Full Changelog', line, re.I))
            notes.append({'tag': r['tag_name'], 'url': r['html_url'], 'body': body})
    metadata = {'tag': tag, 'sha': sha, 'v1.7.1_sha': old, 'image': IMAGE,
                'image_id': command(['docker', 'image', 'inspect', IMAGE, '--format', '{{.Id}}']),
                'cpu': cpu, 'setup_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                'source': '.studio/ai-channel/autoloop/src', 'release_notes': notes,
                'seed': 12648430, 'node_major': 24, 'idle_seconds': 10,
                'restart_wait_seconds': 2, 'F_runs': 5,
                'F_absent_window_seconds': 615, 'F_online_window_seconds': 315}
    (BASE / 'results/setup.json').write_text(json.dumps(metadata, indent=2) + '\n')
    rng = random.Random(metadata['seed'])
    delays = {'C': ([-5, -1] + list(range(31))) * 7, 'E': list(range(31)) * 4}
    for k, n in [('C', 200), ('E', 100)]:
        rng.shuffle(delays[k]); delays[k] = delays[k][:n]
    (BASE / 'results/delays.json').write_text(json.dumps(delays, indent=2) + '\n')
    print(json.dumps({k: metadata[k] for k in ['tag', 'sha', 'v1.7.1_sha', 'image', 'cpu']}))

if __name__ == '__main__':
    main()
