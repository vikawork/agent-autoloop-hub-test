#!/usr/bin/env python3
"""Host orchestrator: runs untrusted source only in disposable Docker containers."""
import argparse
import concurrent.futures
import json
import pathlib
import subprocess
import threading
import time

BASE = pathlib.Path(__file__).resolve().parent
ROOT = BASE.parents[2]
LOCK = threading.Lock()

def command(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, **kwargs)

def checked(args, **kwargs):
    result = command(args, **kwargs)
    if result.returncode:
        raise RuntimeError(f'{args[0]} {args[1]} failed, exit {result.returncode}: {result.stderr}')
    return result.stdout

def run_one(experiment, number, batch):
    setup = json.loads((BASE / 'results/setup.json').read_text())
    delays = json.loads((BASE / 'results/delays.json').read_text())
    delay = delays.get(experiment, [0] * 200)[number - 1]
    label = f'{batch}-{experiment.lower()}-{number:03d}'
    container, volume = f'autoloop-demo-{label}', f'autoloop-demo-{label}-state'
    folder = BASE / 'logs' / label
    folder.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    try:
        checked(['docker', 'volume', 'create', volume])
        args = ['docker', 'create', '--name', container, '--network', 'none', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--read-only', '--pids-limit', '64',
                '--memory', '512m', '--cpus', '1', '--tmpfs', '/tmp:rw,noexec,nosuid,size=16m',
                '--mount', f'type=bind,src={ROOT / setup["source"]},dst=/src,readonly',
                '--mount', f'type=volume,src={volume},dst=/work',
                '--env', 'AGENT_AUTOLOOP_HOME=/work/state', '--env', 'NO_COLOR=1',
                '--workdir', '/work', setup['image'], 'nice', '-n', '10', 'node',
                '--disable-warning=ExperimentalWarning', '/work/harness.mjs', experiment,
                str(number), str(delay), batch]
        checked(args)
        for filename in ['worker.mjs', 'bootstrap.mjs', 'harness.mjs']:
            checked(['docker', 'cp', str(BASE / filename), f'{container}:/work/{filename}'])
        inspected = json.loads(checked(['docker', 'inspect', container]))[0]
        config = {'network': inspected['HostConfig']['NetworkMode'],
                  'cap_drop': inspected['HostConfig']['CapDrop'],
                  'security_opt': inspected['HostConfig']['SecurityOpt'],
                  'privileged': inspected['HostConfig']['Privileged'],
                  'readonly_root': inspected['HostConfig']['ReadonlyRootfs'],
                  'memory_bytes': inspected['HostConfig']['Memory'],
                  'nano_cpus': inspected['HostConfig']['NanoCpus'],
                  'mounts': [{k: m[k] for k in ['Type', 'Destination', 'RW']} for m in inspected['Mounts']]}
        (folder / 'docker-config.json').write_text(json.dumps(config, indent=2) + '\n')
        result = command(['docker', 'start', '-a', container], timeout=900)
        (folder / 'container.log').write_text(result.stdout + result.stderr)
        checked(['docker', 'cp', f'{container}:/work/out/.', str(folder)])
        record = json.loads((folder / 'result.json').read_text())
        record['docker_exit'] = result.returncode
        record['logs'] = str(folder.relative_to(BASE))
        record['container_config'] = config
    except Exception as error:
        # Preserve any available evidence before cleanup, including bootstrap failures.
        command(['docker', 'cp', f'{container}:/work/out/.', str(folder)])
        record = {'experiment': experiment, 'run': number, 'variant': batch,
                  'outcome': 'host-error', 'error': str(error).replace(str(ROOT), '.'),
                  'logs': str(folder.relative_to(BASE)), 'wall_ms': (time.monotonic()-started)*1000}
        (folder / 'host-error.json').write_text(json.dumps(record, indent=2) + '\n')
    finally:
        command(['docker', 'rm', '-f', container])
        command(['docker', 'volume', 'rm', volume])
    with LOCK:
        with (BASE / 'results' / f'{batch}-{experiment}.jsonl').open('a') as file:
            file.write(json.dumps(record) + '\n')
        print(json.dumps({k: record.get(k) for k in ['experiment', 'run', 'variant', 'outcome', 'success', 'error']}), flush=True)
    return record

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiments', default='A,B,C,D,E,F,F-online')
    parser.add_argument('--batch', default='main')
    parser.add_argument('--count', type=int)
    parser.add_argument('--jobs', type=int, default=1)
    parser.add_argument('--start', type=int, default=1)
    args = parser.parse_args()
    sizes = {'A': 30, 'B': 30, 'C': 200, 'D': 100, 'E': 100, 'F': 5, 'F-online': 5}
    tasks = [(e, n) for e in args.experiments.split(',')
             for n in range(args.start, args.start + (args.count or sizes[e]))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(lambda task: run_one(*task, args.batch), tasks))

if __name__ == '__main__':
    main()
