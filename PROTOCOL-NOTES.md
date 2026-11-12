# Protocol actually used

Source root: `.studio/ai-channel/autoloop/src/`, detached at the tag and SHA in
`results/summary.json`. References below are relative to that clone.

The fixture is provisioned inside Docker by importing `host/runtime.ts` and calling its
administrative key creation API. It writes rules and config into the empty scratch state
directory, then closes that connection. The measured hub is the ordinary
`node /src/bin/agent-autoloop.ts up` process. The deterministic worker never imports project
code and no built-in worker or agent CLI is enabled. Only the webhook experiment enables a
channel plugin, running inside the hub process (`host/up.ts:1`, `host/up.ts:102`).

- Source key: `POST /v1/events`, with stable event ID `colour-task`, type `colour.pick`,
  subject `colour`, and summary `Pick a colour`. Event semantics: `docs/protocol.md:117`.
- Worker key: `GET /v1/work?claim=first&wait=0&running=&capacity=1`. The response contains
  `job.run`, a receipt token, attempt, session and context. This script persists the job and
  exact result privately in scratch state before submission. The next round uses claim
  `answer`. The supplementary online-worker observation sends `capacity=0` and empty
  `running` once a second; it keeps worker presence alive without reporting the killed
  round. See `docs/protocol.md:180` and `docs/protocol.md:189`.
- Receipt token: `POST /v1/runs/{run}/result`. The first receipt is
  `{outcome:"done", summary:"Waiting for colour", ask:[{title:"Pick a colour",
  text:"Choose Blue or Green.", options:["Blue","Green"], key:"colour",
  about:"Finish after the colour answer; do not ask again."}],
  later:[{key:"audit-check", at:"<one hour ahead>", about:"Atomic receipt witness"}]}`.
  The timer is an independent receipt effect used to detect partial application. It never
  fires during these observations. Completion submits `outcome:"done"`, summary
  `Task complete: Blue`, one closed FYI notice, and cancellation of `audit-check`.
  Shape and same-token replay contract: `docs/protocol.md:210` and
  `docs/protocol.md:229`. Replay verification: `kernel/decide.ts:455`. Receipt application: `kernel/decide.ts:417`.
- Owner key: `GET /v1/state`, then `POST /v1/cards/{id}/answer` with `{choice:0}`.
  The next job must contain `context.answers[].chosen === "Blue"`.
  See `docs/protocol.md:305` and `kernel/http.ts:324`.
- The lost-ack case writes the entire HTTP request to a socket and destroys the socket in
  its write callback, with no response reader. The same stored token and byte-identical
  JSON result are replayed. This simulates client loss of the response; the before-retry
  snapshot records whether the first request actually committed.
- The built-in webhook channel POSTs to the local sink with its Slack template. The sink
  returns HTTP success with body `ok`, then the coordinator kills the hub at its seeded
  delay. No platform idempotency key is added. See `plugins/webhook/channel.ts:39`,
  `plugins/webhook/channel.ts:56`, `plugins/webhook/templates.ts:26`.

`AGENT_AUTOLOOP_HOME=/work/state` confines `rules.json`, `config.json`, `master.key` and
`hub.db` to the disposable Docker volume (`host/home.ts:5`, `host/runtime.ts:18`). Keys,
tokens and the database are not exported. The database uses WAL and full synchronous
writes (`host/runtime.ts:37`). The authoritative append-only `facts` table and derived
`projections` table are initialized in `kernel/evolve.ts:54`. Both commit in the same
transaction (`kernel/store.ts:10`, `kernel/store.ts:33`). The coordinator reads only
selected nonsensitive projection fields in its own SQLite read transaction.

Default timing constants are unchanged: `kernel/due.ts:6` defines the minute,
`kernel/due.ts:10` the round lease, and `kernel/due.ts:12` worker-offline notification.
An online worker omitting a round triggers `unknown` in `kernel/decide.ts:275`; an absent
worker retains its claim. An explicit failed result follows the separate retry policy in
`kernel/decide.ts:352`, which a process kill alone does not exercise. Delivery claim leases
are assigned by `kernel/decide.ts:539`; delivery acknowledgement is persisted by
`kernel/decide.ts:776`. The observation window allows the unchanged delivery lease to
expire after restart.
