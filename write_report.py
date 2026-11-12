#!/usr/bin/env python3
"""Render REPORT.md exclusively from summary.json; never computes measurement counts."""
import json
import pathlib

BASE = pathlib.Path(__file__).resolve().parent

def main():
    s = json.loads((BASE/'results/summary.json').read_text())
    if not s['complete']:
        raise SystemExit('Measurement incomplete; report not written')
    setup, ex = s['setup'], s['experiments']
    lines = ['# Does a task survive its worker and hub?', '',
             'A deterministic script asks Blue or Green, exits, and later receives the answer in a new round. '
             'We measure the hub’s orchestration and persistence. No model or real agent CLI is involved.', '',
             'The question and answer survived the tested process exits and hub kills. Receipt replay produced '
             'no duplicate question or completion in these samples. External notification delivery had a '
             'different boundary, shown below.', '']
    def add(text=''):
        lines.append(text)
    def table(title, rows, n):
        add(f'## {title}'); add(); add('| Observation | Count |'); add('| --- | ---: |')
        for label, count in rows:
            add(f'| {label} | {count} of {n} |')
        add()
    a=ex['A']
    table('A — waiting without a worker', [('Hub present and worker absent',a['hub_present_worker_absent']),
          ('Answer in a new round’s context',a['answer_in_context']),('Task completed once',a['success'])],a['n'])
    add(f"Idle window seconds, min/median/max: {a['idle_seconds']['min']} / {a['idle_seconds']['median']} / {a['idle_seconds']['max']}. "
        f"Hub CPU milliseconds over that window: {a['idle_cpu_ms']['min']} / {a['idle_cpu_ms']['median']} / {a['idle_cpu_ms']['max']}. "
        f"Final hub RSS KiB: {a['idle_rss_kib']['min']} / {a['idle_rss_kib']['median']} / {a['idle_rss_kib']['max']}. "
        'CPU time comes from the hub process’s kernel accounting; RSS excludes the coordinator.');add()
    b=ex['B']
    table('B — hub killed with an open question', [('Question survived restart',b['question_survived']),
          ('Answer in the next round’s context',b['answer_in_context']),('Task completed once',b['success'])],b['n'])
    add(f"Each restart waited {setup['restart_wait_seconds']} seconds after the killed process exited, using the same scratch state.");add()
    c=ex['C']
    table('C — hub killed around a receipt', [('Receipt acknowledged',c['acknowledged']),
          ('Unacknowledged, wholly applied',c['unack_applied']),('Unacknowledged, wholly absent',c['unack_absent']),
          ('Partial application',c['partial']),('Task completed once after identical replay',c['success'])],c['n'])
    add(f"Acknowledged receipts retained after restart: {c['acknowledged_retained']} of {c['acknowledged']}. "
        f"Unacknowledged receipts total: {c['unacknowledged']}. The independent effects checked were the question, "
        'the audit timer and the first round’s completed state. Both allowed unacknowledged outcomes remain in the logs.');add()
    add(f"Fixed seed: {setup['seed']}. Delay draws and their order are retained in `results/delays.json`; "
        f"{c['negative_delays']} kills preceded submission. Actual kill time relative to request write completion, milliseconds "
        f"min/median/max: {c['kill_relative_to_send_end_ms']['min']} / {c['kill_relative_to_send_end_ms']['median']} / "
        f"{c['kill_relative_to_send_end_ms']['max']}. These are scheduled delays, not a controlled cut inside a database instruction.");add()
    d=ex['D']
    table('D — socket closed without reading acknowledgement', [('Socket closed with no response reader',d['socket_closed_without_response_reader']),
          ('First receipt already applied before replay',d['first_applied_before_retry']),
          ('Identical receipt replay acknowledged',d['retry_acknowledged']),('Task completed once',d['success'])],d['n'])
    add(f"Final question-card counts: `{json.dumps(d['final_counts']['question_cards'])}`; "
        f"round counts: `{json.dumps(d['final_counts']['rounds'])}`; completion counts: `{json.dumps(d['final_counts']['completions'])}`. "
        'Histogram keys are counts per run; values are the number of runs.');add()
    e=ex['E']
    table('E — notification received, then hub killed', [('Completion notification delivered once',e['single_delivery']),
          ('Completion notification delivered more than once',e['duplicated_notifications']),
          ('Underlying task completed once',e['success'])],e['n'])
    add(f"Completion deliveries per notification: `{json.dumps(e['notification_deliveries'])}`; "
        f"total received: {e['total_completion_deliveries']}. The built-in webhook channel targeted the loopback HTTP sink "
        'inside the container, with the Slack response contract and no external platform idempotency. The sink returned '
        'success immediately. The hub, including its in-process channel, was then killed.');add()
    add(f"Actual sink-to-kill milliseconds, min/median/max: {e['actual_kill_after_sink_ms']['min']} / "
        f"{e['actual_kill_after_sink_ms']['median']} / {e['actual_kill_after_sink_ms']['max']}. "
        f"The unchanged delivery lease was observed for {setup['E_post_restart_seconds']} seconds after restart.")
    if e['repeat_after_first_seconds']:
        r=e['repeat_after_first_seconds']
        add(f"Repeated delivery followed the first by {r['min']}–{r['max']} seconds (median {r['median']}).")
    add('This is a conditional crash experiment. Its duplicate frequency is not an estimate of production message loss.');add()
    f=ex['F'];fo=ex['F-online']
    table('F — worker killed after claiming, then absent', [('Offline notice appeared',f['notice_runs']),
          ('Claim retained',f['final_run_states'].get('claimed',0))],f['n'])
    add(f"Observation seconds, min/median/max: {f['observed_seconds']['min']} / {f['observed_seconds']['median']} / {f['observed_seconds']['max']}. "
        f"Final states: `{json.dumps(f['final_run_states'])}`; reported-failure counts: `{json.dumps(f['final_attempts'])}`. "
        f"First offline notice seconds after kill: {f['first_notice_seconds']['min']}–{f['first_notice_seconds']['max']}.");add()
    table('F supplement — worker presence stays online, killed round omitted', [('Uncertain round state',fo['final_run_states'].get('unknown',0)),
          ('Notice appeared',fo['notice_runs'])],fo['n'])
    add(f"First notice seconds after kill: {fo['first_notice_seconds']['min']}–{fo['first_notice_seconds']['max']}; "
        f"final states: `{json.dumps(fo['final_run_states'])}`; reported-failure counts: `{json.dumps(fo['final_attempts'])}`. "
        'This supplement changes presence, not timing constants. The coordinator sends worker heartbeats without the killed '
        'round. A killed process does not itself submit a failed receipt, so the documented failed-result backoff is not '
        'measured by this experiment. The retained and uncertain outcomes are different documented recovery cases.');add()
    add('## Setup and reproduction');add()
    add(f"Tested newest stable release `{setup['tag']}`, commit `{setup['sha']}`. "
        f"Scouted baseline `{setup['baseline_tag']}`: `{setup['v1.7.1_sha']}`. "
        f"Official image: `{setup['image']}`. Node versions observed: {', '.join(s['node_versions'])}. "
        f"Host CPU: {setup['cpu']}. CPU only. UTC range: {s['start_utc']} to {s['end_utc']}; "
        f"measurement wall time {s['wall_seconds']} seconds, including retained pilots.");add()
    add('Every run uses an independent Docker network namespace with networking disabled, a read-only source mount, '
        'an empty state directory in a fresh scratch volume, no other host mounts, dropped capabilities and a read-only '
        'container root. The coordinator and hub are started through `nice`; the process listings show effective niceness. '
        'Per-run security settings are retained as `docker-config.json`. Containers and volumes are removed after copying '
        'the selected logs. No credentials, tokens or database files are exported.');add()
    add(f"Health endpoint commit values: `{json.dumps(s['health_commit_histogram'])}`. "
        'The release identity comes from the detached checkout and read-only mount; the health field did not identify the commit.');add()
    add('Dependencies: Docker, Git and Python standard library on the host; Node and Linux process tools from the pinned '
        'official image. No package install, real agent, paid model, GPU, project installer or host execution of project code.');add()
    add('From the repository root, on a fresh output directory:');add();add('```sh')
    add('sh episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/setup.sh')
    add('sh episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/run-all.sh')
    add('python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/summarize.py')
    add('python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/write_report.py')
    add('```');add()
    add('The full sets overlapped on this machine. Idle CPU measurements are per process; timings are not a throughput '
        'benchmark. Replays require a fresh batch name so retained logs cannot be overwritten.');add()
    add('Release notes read between the baseline and tested tag, retained verbatim without contributor metadata in the summary:');add()
    for note in setup['release_changes']:
        add(f"- [{note['tag']}]({note['url']}): {note['change']}")
    add();add('The delivery-plugin changes concern PR delivery and reviews, distinct from the webhook notification tested here.');add()
    add('## Concrete screen runs');add()
    for screen in s['screens']:
        add(f"### {screen['experiment']}, run {screen['run']}");add()
        add(f"Retained evidence: `{screen['logs']}`. Replay with the same seeded run index:");add();add('```sh')
        add(screen['replay_command']);add('```');add()
        add('Actual container coordinator command:');add();add('```sh');add(screen['container_command']);add('```');add()
        add('Process listing while the question was open (PID, PPID, niceness, state, RSS KiB, CPU time, command):');add();add('```text')
        for listing in screen['processes']:
            if listing['phase']=='question_open':
                lines.extend(listing['listing']);break
        add('```');add();add('Raw hub log:');add();add('```text');lines.extend(screen['hub_log']);add('```');add()
        add('Exact worker log lines:');add();add('```jsonl');lines.extend(screen['worker_log_excerpt']);add('```');add()
        if screen['experiment']=='E':
            add('Sink and kill timeline, monotonic milliseconds from coordinator start:');add();add('```jsonl')
            for event in screen['events']:
                if event['event'] in ['sink_received','hub_kill_after_sink']:add(json.dumps(event,ensure_ascii=False))
            add('```');add()
        add(f"Final counts: `{json.dumps(screen['final_counts'])}`.");add()
    add('## Failed pilots, skipped work and limits');add()
    for name, p in s['supplementary'].items():
        add(f"- `{name}`: {p['n']} run(s), outcomes `{json.dumps(p['outcomes'])}`.")
        if p['notification_deliveries']:
            add(f"  Completion-delivery histogram: `{json.dumps(p['notification_deliveries'])}`.")
        for error in p['errors']:
            add(f"  Run {error['run']}: `{error['error']}`. Evidence: `{error['logs']}`.")
    add();add('The failed pilots were harness mistakes: a broad scratch-path substitution altered the owner-state endpoint. '
              'The endpoint was corrected before the main samples; no project code or timing default was changed. '
              'The successful webhook pilot and all main outcomes remain retained even where their delivery counts differ.');add()
    add(f"Worker-loss samples use the job’s permitted reduced set of {f['n']} runs because the default observation "
        'windows are long. There is no shortened-timing set. The real Codex reconnect fix '
        f"(`{setup['reconnect_claim']}`) was not tested; it requires a real transport and agent, excluded here.");add()
    add('One machine, one rule, one task, deterministic worker. Process kills are not power loss or disk failure. '
        'These samples do not establish model session continuity, agent subprocess recovery, general exactly-once external '
        'side effects, source-event deduplication, repeated work-claim semantics, late-result handling after uncertainty, '
        'or the explicit failed-receipt retry policy. The audit timer checks joint receipt effects; it does not prove '
        'every possible receipt shape is atomic. No product contradiction was inferred merely from an allowed '
        'unacknowledged outcome or a documented webhook duplicate.');add()
    add('All reported numbers and quoted numeric log lines are rendered from `results/summary.json`, written only by '
        '`summarize.py`. Per-run JSONL retains monotonic timelines, process listings, snapshots and outcomes; '
        '`logs/` retains raw hub and worker logs. `PROTOCOL-NOTES.md` identifies the source boundaries used.');add()
    (BASE/'REPORT.md').write_text('\n'.join(lines))

if __name__ == '__main__':
    main()
