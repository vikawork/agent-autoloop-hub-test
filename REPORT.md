# Does a task survive its worker and hub?

A deterministic script asks Blue or Green, exits, and later receives the answer in a new round. We measure the hub’s orchestration and persistence. No model or real agent CLI is involved.

The question and answer survived the tested process exits and hub kills. Receipt replay produced no duplicate question or completion in these samples. External notification delivery had a different boundary, shown below.

## A — waiting without a worker

| Observation | Count |
| --- | ---: |
| Hub present and worker absent | 30 of 30 |
| Answer in a new round’s context | 30 of 30 |
| Task completed once | 30 of 30 |

Idle window seconds, min/median/max: 10.0 / 10.001 / 10.002. Hub CPU milliseconds over that window: 0.0 / 0.0 / 20.0. Final hub RSS KiB: 111584 / 114678.0 / 116604. CPU time comes from the hub process’s kernel accounting; RSS excludes the coordinator.

## B — hub killed with an open question

| Observation | Count |
| --- | ---: |
| Question survived restart | 30 of 30 |
| Answer in the next round’s context | 30 of 30 |
| Task completed once | 30 of 30 |

Each restart waited 2 seconds after the killed process exited, using the same scratch state.

## C — hub killed around a receipt

| Observation | Count |
| --- | ---: |
| Receipt acknowledged | 128 of 200 |
| Unacknowledged, wholly applied | 20 of 200 |
| Unacknowledged, wholly absent | 52 of 200 |
| Partial application | 0 of 200 |
| Task completed once after identical replay | 200 of 200 |

Acknowledged receipts retained after restart: 128 of 128. Unacknowledged receipts total: 72. The independent effects checked were the question, the audit timer and the first round’s completed state. Both allowed unacknowledged outcomes remain in the logs.

Fixed seed: 12648430. Delay draws and their order are retained in `results/delays.json`; 12 kills preceded submission. Actual kill time relative to request write completion, milliseconds min/median/max: -26.021 / 14.441 / 39.783. These are scheduled delays, not a controlled cut inside a database instruction.

## D — socket closed without reading acknowledgement

| Observation | Count |
| --- | ---: |
| Socket closed with no response reader | 100 of 100 |
| First receipt already applied before replay | 100 of 100 |
| Identical receipt replay acknowledged | 100 of 100 |
| Task completed once | 100 of 100 |

Final question-card counts: `{"1": 100}`; round counts: `{"2": 100}`; completion counts: `{"1": 100}`. Histogram keys are counts per run; values are the number of runs.

## E — notification received, then hub killed

| Observation | Count |
| --- | ---: |
| Completion notification delivered once | 90 of 100 |
| Completion notification delivered more than once | 10 of 100 |
| Underlying task completed once | 100 of 100 |

Completion deliveries per notification: `{"1": 90, "2": 10}`; total received: 110. The built-in webhook channel targeted the loopback HTTP sink inside the container, with the Slack response contract and no external platform idempotency. The sink returned success immediately. The hub, including its in-process channel, was then killed.

Actual sink-to-kill milliseconds, min/median/max: 0.382 / 15.638 / 31.871. The unchanged delivery lease was observed for 65 seconds after restart.
Repeated delivery followed the first by 60.004–60.02 seconds (median 60.009).
This is a conditional crash experiment. Its duplicate frequency is not an estimate of production message loss.

## F — worker killed after claiming, then absent

| Observation | Count |
| --- | ---: |
| Offline notice appeared | 5 of 5 |
| Claim retained | 5 of 5 |

Observation seconds, min/median/max: 615.717 / 615.767 / 615.791. Final states: `{"claimed": 5}`; reported-failure counts: `{"0": 5}`. First offline notice seconds after kill: 600.676–600.752.

## F supplement — worker presence stays online, killed round omitted

| Observation | Count |
| --- | ---: |
| Uncertain round state | 5 of 5 |
| Notice appeared | 5 of 5 |

First notice seconds after kill: 300.311–300.372; final states: `{"unknown": 5}`; reported-failure counts: `{"0": 5}`. This supplement changes presence, not timing constants. The coordinator sends worker heartbeats without the killed round. A killed process does not itself submit a failed receipt, so the documented failed-result backoff is not measured by this experiment. The retained and uncertain outcomes are different documented recovery cases.

## Setup and reproduction

Tested newest stable release `v1.8.2`, commit `306e0873edc84a658ff1351e0f43f637edaf0e48`. Scouted baseline `v1.7.1`: `24e21c6ba7c30808467ee93c99b3a1200ac9246e`. Official image: `node:24@sha256:9d266751ca3d7fdbe651c878ffd5ad0a42fed49a18c283509267c97f025b7496`. Node versions observed: v24.22.3. Host CPU: AMD Ryzen 9 9950X 16-Core Processor. CPU only. UTC range: 2026-11-12T05:25:08.321Z to 2026-11-12T05:36:37.599Z; measurement wall time 689.278 seconds, including retained pilots.

Every run uses an independent Docker network namespace with networking disabled, a read-only source mount, an empty state directory in a fresh scratch volume, no other host mounts, dropped capabilities and a read-only container root. The coordinator and hub are started through `nice`; the process listings show effective niceness. Per-run security settings are retained as `docker-config.json`. Containers and volumes are removed after copying the selected logs. No credentials, tokens or database files are exported.

Health endpoint commit values: `{"dev": 478}`. The release identity comes from the detached checkout and read-only mount; the health field did not identify the commit.

Dependencies: Docker, Git and Python standard library on the host; Node and Linux process tools from the pinned official image. No package install, real agent, paid model, GPU, project installer or host execution of project code.

From the repository root, on a fresh output directory:

```sh
sh episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/setup.sh
sh episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/run-all.sh
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/summarize.py
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/write_report.py
```

The full sets overlapped on this machine. Idle CPU measurements are per process; timings are not a throughput benchmark. Replays require a fresh batch name so retained logs cannot be overwritten.

Release notes read between the baseline and tested tag, retained verbatim without contributor metadata in the summary:

- [v1.7.2](https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.7.2): Windows registration failure retains the existing service and hub until replacement succeeds; the worker recovery fixture waits until an agent starts before fault injection. Feishu text answers and default channel routing were added.
- [v1.8.0](https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.0): Per-rule and per-agent active-task limits were added. Delivery records review rounds and supports emergency handling of a handed-off PR when the hub is unavailable.
- [v1.8.1](https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.1): Emergency delivery can retry transient failures in its existing temporary directory; deeper review requirements can trigger another review.
- [v1.8.2](https://github.com/KKKKhazix/agent-autoloop/releases/tag/v1.8.2): Events skipped during pauses can be replayed. Delivery retries a stalled queued GitHub check once, then hands it back; follow-up review ownership and delivery end states were fixed. Reading incomplete ZCode output no longer hangs.

The delivery-plugin changes concern PR delivery and reviews, distinct from the webhook notification tested here.

## Concrete screen runs

### A, run 1

Retained evidence: `logs/main-a-001`. Replay with the same seeded run index:

```sh
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/harness.py --experiments A --start 1 --count 1 --batch screen-a-1
```

Actual container coordinator command:

```sh
nice -n 10 node --disable-warning=ExperimentalWarning /work/harness.mjs A 1 0 main
```

Process listing while the question was open (PID, PPID, niceness, state, RSS KiB, CPU time, command):

```text
1       0  10 SNsl 82404 00:00:00 node --disable-warning=ExperimentalWarning work/harness.mjs A 1 0 main
22       1  19 SNl  112320 00:00:00 node --disable-warning=ExperimentalWarning src/bin/agent-autoloop.ts up
39       1  10 RN    4260 00:00:00 ps -eo pid,ppid,ni,stat,rss,time,args --no-headers
```

Raw hub log:

```text
2026-11-12T05:26:36.079Z [hub] listening on 127.0.0.1:3350
```

Exact worker log lines:

```jsonl
{"ms":554.421549,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
{"ms":10645.250855,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
```

Final counts: `{"question_cards": 1, "completion_cards": 1, "completions": 1, "rounds": 2, "audit_timers": 0}`.

### B, run 2

Retained evidence: `logs/main-b-002`. Replay with the same seeded run index:

```sh
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/harness.py --experiments B --start 2 --count 1 --batch screen-b-2
```

Actual container coordinator command:

```sh
nice -n 10 node --disable-warning=ExperimentalWarning /work/harness.mjs B 2 0 main
```

Process listing while the question was open (PID, PPID, niceness, state, RSS KiB, CPU time, command):

```text
1       0  10 SNsl 82336 00:00:00 node --disable-warning=ExperimentalWarning work/harness.mjs B 2 0 main
22       1  19 SNl  112112 00:00:00 node --disable-warning=ExperimentalWarning src/bin/agent-autoloop.ts up
39       1  10 RN    4348 00:00:00 ps -eo pid,ppid,ni,stat,rss,time,args --no-headers
```

Raw hub log:

```text
2026-11-12T05:27:38.826Z [hub] listening on 127.0.0.1:3350
2026-11-12T05:27:41.219Z [hub] listening on 127.0.0.1:3350
```

Exact worker log lines:

```jsonl
{"ms":650.328729,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
{"ms":3048.461489,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
```

Final counts: `{"question_cards": 1, "completion_cards": 1, "completions": 1, "rounds": 2, "audit_timers": 0}`.

### C, run 2

Retained evidence: `logs/main-c-002`. Replay with the same seeded run index:

```sh
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/harness.py --experiments C --start 2 --count 1 --batch screen-c-2
```

Actual container coordinator command:

```sh
nice -n 10 node --disable-warning=ExperimentalWarning /work/harness.mjs C 2 16 main
```

Process listing while the question was open (PID, PPID, niceness, state, RSS KiB, CPU time, command):

```text
1       0  10 SNsl 82680 00:00:00 node --disable-warning=ExperimentalWarning work/harness.mjs C 2 16 main
39       1  19 SNl  114108 00:00:00 node --disable-warning=ExperimentalWarning src/bin/agent-autoloop.ts up
57       1  10 RN    4276 00:00:00 ps -eo pid,ppid,ni,stat,rss,time,args --no-headers
```

Raw hub log:

```text
2026-11-12T05:28:07.544Z [hub] listening on 127.0.0.1:3350
2026-11-12T05:28:10.088Z [hub] listening on 127.0.0.1:3350
```

Exact worker log lines:

```jsonl
{"ms":921.107308,"event":"hub_kill_sent"}
{"ms":930.099833,"event":"receipt_error","code":"ECONNRESET"}
{"ms":3402.790476,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
{"ms":3570.780396,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
```

Final counts: `{"question_cards": 1, "completion_cards": 1, "completions": 1, "rounds": 2, "audit_timers": 0}`.

### E, run 25

Retained evidence: `logs/main-e-025`. Replay with the same seeded run index:

```sh
python3 episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/harness.py --experiments E --start 25 --count 1 --batch screen-e-25
```

Actual container coordinator command:

```sh
nice -n 10 node --disable-warning=ExperimentalWarning /work/harness.mjs E 25 2 main
```

Process listing while the question was open (PID, PPID, niceness, state, RSS KiB, CPU time, command):

```text
1       0  10 SNsl 82632 00:00:00 node --disable-warning=ExperimentalWarning work/harness.mjs E 25 2 main
22       1  19 RNl  122584 00:00:00 node --disable-warning=ExperimentalWarning src/bin/agent-autoloop.ts up
39       1  10 RN    4352 00:00:00 ps -eo pid,ppid,ni,stat,rss,time,args --no-headers
```

Raw hub log:

```text
2026-11-12T05:28:45.372Z [hub] listening on 127.0.0.1:3350
2026-11-12T05:28:47.974Z [hub] listening on 127.0.0.1:3350
```

Exact worker log lines:

```jsonl
{"ms":781.304439,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
{"ms":950.720774,"event":"receipt_ack","status":200,"body":"{\"rejected\":[]}"}
```

Sink and kill timeline, monotonic milliseconds from coordinator start:

```jsonl
{"ms": 790.532255, "body": {"text": "Pick a colour\n\nChoose Blue or Green.\n\n1. Blue\n2. Green", "mrkdwn": false, "unfurl_links": false, "unfurl_media": false}, "event": "sink_received"}
{"ms": 970.93075, "body": {"text": "Task complete\n\nBlue selected.", "mrkdwn": false, "unfurl_links": false, "unfurl_media": false}, "event": "sink_received"}
{"ms": 974.234369, "delay_ms": 2, "event": "hub_kill_after_sink"}
{"ms": 60980.005222, "body": {"text": "Task complete\n\nBlue selected.", "mrkdwn": false, "unfurl_links": false, "unfurl_media": false}, "event": "sink_received"}
```

Final counts: `{"question_cards": 1, "completion_cards": 1, "completions": 1, "rounds": 2, "audit_timers": 0}`.

## Failed pilots, skipped work and limits

- `pilot-A`: 1 run(s), outcomes `{"harness-error": 1}`.
  Run 1: `Error: HTTP 404: {"error":"没有这个地址"}`. Evidence: `logs/pilot-a-001`.
- `pilot2-B`: 1 run(s), outcomes `{"harness-error": 1}`.
  Run 1: `Error: HTTP 404 /v1/work/state: {"error":"没有这个地址"}`. Evidence: `logs/pilot2-b-001`.
- `pilot3-A`: 1 run(s), outcomes `{"observed": 1}`.
- `pilot3-B`: 1 run(s), outcomes `{"observed": 1}`.
- `pilot3-C`: 1 run(s), outcomes `{"observed": 1}`.
- `pilot3-D`: 1 run(s), outcomes `{"observed": 1}`.
- `pilot3-E`: 1 run(s), outcomes `{"observed": 1}`.
  Completion-delivery histogram: `{"2": 1}`.
- `pilot3-F-online`: 1 run(s), outcomes `{"observed": 1}`.

The failed pilots were harness mistakes: a broad scratch-path substitution altered the owner-state endpoint. The endpoint was corrected before the main samples; no project code or timing default was changed. The successful webhook pilot and all main outcomes remain retained even where their delivery counts differ.

Worker-loss samples use the job’s permitted reduced set of 5 runs because the default observation windows are long. There is no shortened-timing set. The real Codex reconnect fix (`CLAIM-0001`) was not tested; it requires a real transport and agent, excluded here.

One machine, one rule, one task, deterministic worker. Process kills are not power loss or disk failure. These samples do not establish model session continuity, agent subprocess recovery, general exactly-once external side effects, source-event deduplication, repeated work-claim semantics, late-result handling after uncertainty, or the explicit failed-receipt retry policy. The audit timer checks joint receipt effects; it does not prove every possible receipt shape is atomic. No product contradiction was inferred merely from an allowed unacknowledged outcome or a documented webhook duplicate.

All reported numbers and quoted numeric log lines are rendered from `results/summary.json`, written only by `summarize.py`. Per-run JSONL retains monotonic timelines, process listings, snapshots and outcomes; `logs/` retains raw hub and worker logs. `PROTOCOL-NOTES.md` identifies the source boundaries used.
