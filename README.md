# What survives when an agent hub is killed mid-handoff

A measurement by [Vikawork](https://vikawork.com/) of [Agent Autoloop](https://github.com/KKKKhazix/agent-autoloop)
v1.8.2 (commit `306e0873`). In that project an agent that needs a decision puts its question in a receipt and exits;
a local hub keeps the task. We killed the hub around that handoff and counted what survived.

A deterministic script plays the worker. No model and no real agent CLI is involved, so this tests the hub's
orchestration and persistence, not whether a model picks up its reasoning.

| Experiment | Runs | Result |
| --- | ---: | --- |
| A. Question open, worker exited | 30 | Hub present and worker absent in 30; the answer reached the next round in 30 |
| B. Hub killed while the question was open | 30 | Question survived the restart in 30; task finished once in 30 |
| C. Hub killed around the receipt | 200 | 128 acknowledged, all retained; 72 unacknowledged: 20 wholly applied, 52 wholly absent, 0 partial; 200 finished once after the same receipt was sent again |
| D. Reply never read, receipt sent again | 100 | One question and one completion in 100 |
| E. Hub killed just after a webhook delivery | 100 | "Task complete" delivered once in 90 and twice in 10; the task completed once in 100 |
| F. Worker killed mid-round | 5 + 5 | Claim kept and an offline notice after about 600.7 s (5 of 5); with heartbeats that omit the round, marked uncertain after about 300.3 s (5 of 5) |

Process kills on one machine on 12 November 2026, one rule, one task. Process kills are not power loss. Experiment E
is a deliberately timed crash against a receiver with no duplicate protection: 10 in 100 is the result of that
experiment, not a rate in normal use, and the project's documentation says a notification can repeat in that case.
[REPORT.md](REPORT.md) has the tables, the setup, example runs and the limits.

## Files

| File | Contents |
| --- | --- |
| [REPORT.md](REPORT.md) | Results per experiment, setup, concrete runs, failed pilots and limits |
| [PROTOCOL-NOTES.md](PROTOCOL-NOTES.md) | The worker protocol as the test used it, with file and line references into the project at the tested tag |
| `worker.mjs`, `harness.mjs`, `bootstrap.mjs` | The script worker and the in-container coordinator |
| `harness.py`, `run_all.py`, `setup.py`, `summarize.py`, `write_report.py` | Host-side runner, setup (clone at the tag, pull the pinned image), summary and report |
| `results/` | One JSON line per run and `summary.json`, which every number in the report comes from |
| `logs/` | Raw hub and worker logs, timelines and container settings per run |

## Run it

Needs Docker, Git and Python 3. Every run uses its own container from the pinned `node:24` image with networking
disabled, the project mounted read-only and an empty state volume.

The scripts were written inside a larger repository and keep its paths: they expect to sit at
`episodes/when-the-ai-agent-exits-what-keeps-its-task-alive/demo/` under a root that also holds
`.studio/ai-channel/autoloop/` for the clone. Recreate that layout, or change `ROOT` and `SCRATCH` at the top of
`setup.py` and `harness.py`. The commands are in the "Setup and reproduction" section of the report.
