#!/usr/bin/env python3
"""The sole writer of summary.json; all measurements are derived from retained JSONL."""
import collections
import datetime as dt
import hashlib
import json
import pathlib
import statistics

BASE = pathlib.Path(__file__).resolve().parent
EXPECTED = {'A': 30, 'B': 30, 'C': 200, 'D': 100, 'E': 100, 'F': 5, 'F-online': 5}

def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def distribution(values, digits=3):
    values = list(values)
    if not values:
        return None
    return {k: round(v, digits) for k, v in
            [('min', min(values)), ('median', statistics.median(values)), ('max', max(values))]}

def histogram(values):
    return dict(sorted(collections.Counter(map(str, values)).items()))

def aggregate(experiment, rows):
    good = [r for r in rows if r['outcome'] == 'observed']
    out = {'n': len(rows), 'expected_n': EXPECTED[experiment], 'observed': len(good),
           'errors': [{'run': r['run'], 'outcome': r['outcome'], 'error': r.get('error'), 'logs': r['logs']}
                      for r in rows if r['outcome'] != 'observed'],
           'success': sum(r.get('success', False) for r in good),
           'wall_seconds': distribution(r['wall_ms'] / 1000 for r in rows),
           'final_counts': {key: histogram(r['final']['counts'][key] for r in good)
                            for key in ['question_cards', 'completion_cards', 'completions', 'rounds']}}
    if experiment in ['A', 'B', 'C', 'D', 'E']:
        out['answer_in_context'] = sum(r.get('answer_in_context', False) for r in good)
        out['new_round'] = sum(r.get('new_round', False) for r in good)
        out['hub_present_worker_absent'] = sum(any(p['phase'] == 'question_open' and p['hub_exists']
                                                  and not p['worker_exists'] for p in r['processes']) for r in good)
    if experiment == 'A':
        out['idle_seconds'] = distribution(r['idle']['elapsed_ms']/1000 for r in good)
        out['idle_cpu_ms'] = distribution(r['idle']['cpu_ticks'] * 1000 / r['idle']['clock_ticks_per_second'] for r in good)
        out['idle_rss_kib'] = distribution(r['idle']['after']['rss_kib'] for r in good)
    if experiment == 'B':
        out['question_survived'] = sum(r.get('question_survived', False) for r in good)
    if experiment == 'C':
        ack = [r for r in good if r.get('acknowledged')]
        unack = [r for r in good if not r.get('acknowledged')]
        out.update(acknowledged=len(ack), acknowledged_retained=sum(r['ack_retained'] for r in ack),
                   unacknowledged=len(unack),
                   unack_applied=sum(r['after_restart']['counts']['question_cards'] == 1 and r['atomic'] for r in unack),
                   unack_absent=sum(r['after_restart']['counts']['question_cards'] == 0 and r['atomic'] for r in unack),
                   partial=sum(not r['atomic'] for r in good),
                   negative_delays=sum(r['delay_ms'] < 0 for r in good),
                   delay_histogram=histogram(r['delay_ms'] for r in good))
        actual = []
        for r in good:
            sent = next(e['ms'] for e in r['timeline'] if e['event'] == 'receipt_send_end')
            killed = next(e['ms'] for e in r['timeline'] if e['event'] == 'hub_kill_sent')
            actual.append(killed-sent)
        out['kill_relative_to_send_end_ms'] = distribution(actual)
        out['contradiction_runs'] = [r['run'] for r in good if not r['atomic'] or not r['ack_retained'] or not r['success']]
    if experiment == 'D':
        out['first_applied_before_retry'] = sum(r['before_retry']['counts']['question_cards'] == 1 for r in good)
        out['socket_closed_without_response_reader'] = sum(any(e['event'] == 'receipt_socket_closed_without_read'
                                                                for e in r['timeline']) for r in good)
        out['retry_acknowledged'] = sum(any(e['event'] == 'receipt_ack' and e['status'] == 200 for e in r['timeline']) for r in good)
    if experiment == 'E':
        out['notification_deliveries'] = histogram(r['notification_deliveries'] for r in good)
        out['duplicated_notifications'] = sum(r['notification_deliveries'] > 1 for r in good)
        out['single_delivery'] = sum(r['notification_deliveries'] == 1 for r in good)
        out['total_completion_deliveries'] = sum(r['notification_deliveries'] for r in good)
        out['delay_histogram'] = histogram(r['delay_ms'] for r in good)
        actual = []
        repeat_intervals = []
        for r in good:
            d = [e['ms'] for e in r['sink_deliveries'] if e['body']['text'].startswith('Task complete')]
            kill = next(e['ms'] for e in r['timeline'] if e['event'] == 'hub_kill_after_sink')
            actual.append(kill-d[0])
            repeat_intervals.extend((t-d[0])/1000 for t in d[1:])
        out['actual_kill_after_sink_ms'] = distribution(actual)
        out['repeat_after_first_seconds'] = distribution(repeat_intervals)
    if experiment.startswith('F'):
        out['final_run_states'] = histogram(r['final']['runs'][0]['state'] for r in good)
        out['final_attempts'] = histogram(r['final']['runs'][0]['attempts'] for r in good)
        out['observed_seconds'] = distribution(r['observed_ms']/1000 for r in good)
        out['notice_runs'] = sum(bool(r['final']['cards']) for r in good)
        changes = [t['elapsed_ms']/1000 for r in good for t in r['transitions'] if t['state']['cards']]
        out['first_notice_seconds'] = distribution(changes)
        out['transitions'] = [{'run': r['run'], 'states': r['transitions']} for r in good]
    return out

def screen_run(row):
    exp, run = row['experiment'], row['run']
    folder = BASE / row['logs']
    prefix = 'episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/'
    events = [e for e in row['timeline'] if e['event'] in
              ['receipt_ack', 'receipt_error', 'hub_kill_sent', 'hub_kill_after_sink',
               'sink_received', 'answer_sent', 'worker_loss_state']]
    return {'experiment': exp, 'run': run, 'delay_ms': row['delay_ms'], 'logs': row['logs'],
            'replay_command': f'python3 {prefix}harness.py --experiments {exp} --start {run} --count 1 --batch screen-{exp.lower()}-{run}',
            'container_command': f'nice -n 10 node --disable-warning=ExperimentalWarning /work/harness.mjs {exp} {run} {row["delay_ms"]} main',
            'processes': row['processes'], 'events': events,
            'hub_log': (folder / 'hub.log').read_text().splitlines(),
            'worker_log_excerpt': [line for line in (folder/'worker.log').read_text().splitlines()
                                   if json.loads(line)['event'] in ['receipt_ack', 'receipt_error', 'hub_kill_sent']],
            'final_counts': row['final']['counts'],
            'idle': row.get('idle'), 'notification_deliveries': row.get('notification_deliveries')}

def main():
    setup = json.loads((BASE / 'results/setup.json').read_text())
    setup.update(baseline_tag='v1.7.1', reconnect_claim='CLAIM-0001', E_post_restart_seconds=65,
                 release_changes=[
                     {'tag':'v1.7.2', 'url':'https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.7.2',
                      'change':'Windows registration failure retains the existing service and hub until replacement succeeds; the worker recovery fixture waits until an agent starts before fault injection. Feishu text answers and default channel routing were added.'},
                     {'tag':'v1.8.0', 'url':'https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.0',
                      'change':'Per-rule and per-agent active-task limits were added. Delivery records review rounds and supports emergency handling of a handed-off PR when the hub is unavailable.'},
                     {'tag':'v1.8.1', 'url':'https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.1',
                      'change':'Emergency delivery can retry transient failures in its existing temporary directory; deeper review requirements can trigger another review.'},
                     {'tag':'v1.8.2', 'url':'https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.2',
                      'change':'Events skipped during pauses can be replayed. Delivery retries a stalled queued GitHub check once, then hands it back; follow-up review ownership and delivery end states were fixed. Reading incomplete ZCode output no longer hangs.'}])
    rows = {e: read(BASE / f'results/main-{e}.jsonl') if (BASE / f'results/main-{e}.jsonl').exists() else [] for e in EXPECTED}
    other = {p.stem: read(p) for p in sorted((BASE / 'results').glob('*.jsonl')) if not p.name.startswith('main-')}
    all_rows = [r for group in rows.values() for r in group] + [r for group in other.values() for r in group]
    stamps = [r['started_utc'] for r in all_rows if 'started_utc' in r]
    ends = [r['finished_utc'] for r in all_rows if 'finished_utc' in r]
    start = min(stamps) if stamps else None
    end = max(ends) if ends else None
    summary = {'setup': setup, 'expected': EXPECTED, 'generated_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
               'start_utc': start, 'end_utc': end,
               'wall_seconds': round((dt.datetime.fromisoformat(end)-dt.datetime.fromisoformat(start)).total_seconds(), 3) if end else None,
               'node_versions': sorted({r['node'] for r in all_rows if 'node' in r}),
               'health_commit_histogram': histogram(r['health']['commit'] for r in all_rows if 'health' in r),
               'experiments': {e: aggregate(e, rs) for e, rs in rows.items()},
               'supplementary': {name: {'n': len(rs), 'outcomes': histogram(r['outcome'] for r in rs),
                                        'notification_deliveries': histogram(r['notification_deliveries'] for r in rs if 'notification_deliveries' in r),
                                        'errors': [{'run':r['run'], 'error':r.get('error'), 'logs':r['logs']}
                                                   for r in rs if r['outcome'] != 'observed']} for name, rs in other.items()},
               'total_main_runs': sum(map(len, rows.values())),
               'complete': all(len(rows[e]) == n and all(r['outcome']=='observed' for r in rows[e]) for e,n in EXPECTED.items()),
               'inputs': {str(p.relative_to(BASE)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in sorted((BASE/'results').glob('*.jsonl'))},
               'harness_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in sorted(BASE.iterdir()) if p.suffix in ['.py','.mjs','.sh']},
               'screens': []}
    # Select concrete examples using observations, not a preferred outcome.
    selectors = [('A', lambda r: True), ('B', lambda r: True),
                 ('C', lambda r: not r.get('acknowledged')), ('E', lambda r: r.get('notification_deliveries', 0) > 1)]
    for exp, predicate in selectors:
        candidates = [r for r in rows[exp] if r['outcome']=='observed']
        if candidates:
            selected = next((r for r in candidates if predicate(r)), candidates[0])
            summary['screens'].append(screen_run(selected))
    (BASE/'results/summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({'complete':summary['complete'], 'total_main_runs':summary['total_main_runs'],
                      'experiments': {e: {'n':v['n'], 'success':v['success'], 'errors':v['errors']} for e,v in summary['experiments'].items()}}))

if __name__ == '__main__':
    main()
