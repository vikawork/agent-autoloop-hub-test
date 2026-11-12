// Container coordinator. No project imports; uses HTTP and read-only SQLite snapshots.
import fs from 'node:fs';
import http from 'node:http';
import {spawn, spawnSync} from 'node:child_process';
import {DatabaseSync} from 'node:sqlite';

const [experiment, numberString, delayString = '0', variant = 'main'] = process.argv.slice(2);
const run = Number(numberString), delay = Number(delayString);
const origin = process.hrtime.bigint();
const now = () => Number(process.hrtime.bigint() - origin) / 1e6;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const out = {experiment, run, variant, delay_ms: delay, started_utc: new Date().toISOString(), node: process.version, timeline: [], processes: []};
const note = (event, values = {}) => {
  const item = {ms: now(), ...values, event}; out.timeline.push(item);
  fs.appendFileSync('/work/out/timeline.jsonl', JSON.stringify(item) + '\n'); return item;
};
fs.mkdirSync('/work/out', {recursive: true});
let hub, sink, worker, killed = false;
const deliveries = [];
let keys;
async function api(path, body, kind = 'owner') {
  const r = await fetch(`http://127.0.0.1:3350${path}`, {method: body === undefined ? 'GET' : 'POST',
    headers: {authorization: `Bearer ${keys[kind]}`, 'content-type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(10000)});
  const data = await r.json();
  if (!r.ok) throw new Error(`HTTP ${r.status} ${path}: ${JSON.stringify(data)}`);
  return data;
}
async function startHub() {
  const fd = fs.openSync('/work/out/hub.log', 'a');
  hub = spawn('nice', ['-n', '10', 'node', '--disable-warning=ExperimentalWarning', '/src/bin/agent-autoloop.ts', 'up'], {stdio: ['ignore', fd, fd]});
  fs.closeSync(fd);
  await new Promise(resolve => hub.once('spawn', resolve));
  note('hub_spawned', {pid: hub.pid});
  const end = now() + 15000;
  while (now() < end) {
    try { const r = await fetch('http://127.0.0.1:3350/healthz', {signal: AbortSignal.timeout(500)});
      if (r.ok) { out.health = await r.json(); note('hub_ready'); return; }
    } catch {}
    await sleep(20);
  }
  throw new Error('Hub did not become ready');
}
async function stopHub(signal = 'SIGKILL') {
  if (hub.exitCode !== null || hub.signalCode !== null) return;
  const done = new Promise(resolve => hub.once('exit', resolve)); hub.kill(signal); note('hub_signal', {signal}); await done;
}
async function restart() { await sleep(2000); await startHub(); }
async function doWorker(mode, extra = []) {
  worker = spawn('nice', ['-n', '10', 'node', '/work/worker.mjs', mode, String(origin), String(hub.pid), String(delay)], {stdio: ['ignore', 'pipe', 'pipe']});
  let text = '', err = '';
  worker.stdout.on('data', c => { text += c; fs.appendFileSync('/work/out/worker.log', c); });
  worker.stderr.on('data', c => { err += c; fs.appendFileSync('/work/out/worker-stderr.log', c); });
  const exit = new Promise(resolve => worker.once('exit', (code, signal) => resolve({code, signal})));
  if (mode === 'hold') {
    const end = now() + 10000;
    while (!text.includes('"claimed"') && now() < end) await sleep(10);
    if (!text.includes('"claimed"')) throw new Error('Worker failed to claim');
    const ps = processList('worker_claimed');
    note('worker_kill_sent', {pid: worker.pid}); worker.kill('SIGKILL');
  }
  const status = await exit;
  const events = text.trim().split('\n').filter(Boolean).map(x => JSON.parse(x));
  out.timeline.push(...events);
  note('worker_exited', {mode, ...status, stderr: err});
  if (status.code && mode !== 'crash') throw new Error(`Worker ${mode} exited ${status.code}`);
  return events;
}
function processList(phase) {
  const result = spawnSync('ps', ['-eo', 'pid,ppid,ni,stat,rss,time,args', '--no-headers'], {encoding: 'utf8'});
  const listing = result.stdout.trim().split('\n').map(s => s.trim().replaceAll('/src/', 'src/').replaceAll('/work/', 'work/'));
  const item = {ms: now(), phase, listing, hub_pid: hub.pid,
    hub_exists: fs.existsSync(`/proc/${hub.pid}/stat`),
    worker_exists: worker ? fs.existsSync(`/proc/${worker.pid}/stat`) : false};
  out.processes.push(item); note('process_listing', item); return item;
}
function usage() {
  const raw = fs.readFileSync(`/proc/${hub.pid}/stat`, 'utf8');
  const fields = raw.slice(raw.lastIndexOf(')') + 2).trim().split(/\s+/);
  const status = fs.readFileSync(`/proc/${hub.pid}/status`, 'utf8');
  return {ms: now(), cpu_ticks: Number(fields[11]) + Number(fields[12]),
    rss_kib: Number(status.match(/^VmRSS:\s+(\d+)/m)[1])};
}
function snapshot(label) {
  const db = new DatabaseSync('/work/state/hub.db', {readOnly: true});
  db.exec('BEGIN');
  const read = name => db.prepare('SELECT data FROM projections WHERE collection=?').all(name).map(r => JSON.parse(r.data));
  const cards = read('cards').map(({id, kind, key, state, title, choice, answer, result, run_id, fyi}) => ({id, kind, key, state, title, choice, answer, result, run_id, fyi}));
  const runs = read('runs').map(({id, state, summary, attempts, error, claimed_at, finished_at, seen_at}) => ({id, state, summary, attempts, error, claimed_at, finished_at, seen_at}));
  const timers = read('timers');
  const sent = read('deliveries').map(({id, card_id, ref, version, delivered_version, tries, not_before}) => ({id, card_id, ref, version, delivered_version, tries, not_before}));
  const counts = {question_cards: cards.filter(c => c.kind === 'ask').length,
    completion_cards: cards.filter(c => c.title === 'Task complete').length,
    completions: runs.filter(r => r.state === 'done' && r.summary === 'Task complete: Blue').length,
    rounds: runs.length, audit_timers: timers.filter(t => t.key === 'audit-check' && t.event_id === null).length};
  db.exec('COMMIT'); db.close();
  const value = {label, ms: now(), cards, runs, timers, deliveries: sent, counts};
  fs.writeFileSync(`/work/out/${label}.json`, JSON.stringify(value, null, 2)); note('snapshot', value); return value;
}
async function finishTask() {
  const state = await api('/v1/state');
  const card = state.cards.find(c => c.kind === 'ask' && c.title === 'Pick a colour');
  if (!card) throw new Error('No open colour question');
  note('answer_sent', {card: card.id, choice: 0, response: await api(`/v1/cards/${card.id}/answer`, {choice: 0})});
  const events = await doWorker('complete');
  out.answer_in_context = events.some(e => e.event === 'claimed' && e.context.answers.some(a => a.chosen === 'Blue'));
  out.new_round = events.some(e => e.event === 'claimed' && e.run !== 1);
}
async function waitFor(fn, timeout, step = 25) {
  const end = now() + timeout;
  while (now() < end) { if (await fn()) return true; await sleep(step); } return false;
}
try {
  const provision = spawnSync('nice', ['-n', '10', 'node', '--disable-warning=ExperimentalWarning', '/work/bootstrap.mjs', experiment], {encoding: 'utf8'});
  fs.writeFileSync('/work/out/bootstrap.log', provision.stdout + provision.stderr);
  if (provision.status) throw new Error('Fixture provisioning failed; see bootstrap.log');
  keys = JSON.parse(fs.readFileSync('/work/state/keys.json', 'utf8'));
  if (experiment === 'E') {
    sink = http.createServer((req, res) => {
      let body = ''; req.on('data', c => body += c);
      req.on('end', () => {
        const item = {ms: now(), body: JSON.parse(body)}; deliveries.push(item); note('sink_received', item);
        if (item.body.text.startsWith('Task complete') && !killed) {
          killed = true;
          setTimeout(() => { hub.kill('SIGKILL'); note('hub_kill_after_sink', {delay_ms: delay}); }, delay);
        }
        res.writeHead(200, {'content-type': 'text/plain'}).end('ok');
      });
    });
    await new Promise(resolve => sink.listen(3351, '127.0.0.1', resolve));
  }
  await startHub();
  out.event_response = await api('/v1/events', {id: 'colour-task', type: 'colour.pick', subject: 'colour', summary: 'Pick a colour'}, 'source');
  note('event_accepted', out.event_response);
  if (experiment === 'F' || experiment === 'F-online') {
    await doWorker('hold'); processList('after_worker_kill');
    const killedAt = now(); out.transitions = [];
    let previous = '';
    const window = experiment === 'F' ? 615000 : 315000;
    while (now() - killedAt < window) {
      if (experiment === 'F-online') await api('/v1/work?claim=heartbeat&wait=0&running=&capacity=0', undefined, 'worker');
      const state = await api('/v1/state');
      const current = JSON.stringify({runs: state.runs.map(r => ({id: r.id, state: r.state, attempts: r.attempts})), cards: state.cards.map(c => ({id: c.id, title: c.title, text: c.text}))});
      if (current !== previous) { const item = {elapsed_ms: now() - killedAt, state: JSON.parse(current)}; out.transitions.push(item); note('worker_loss_state', item); previous = current; }
      await sleep(1000);
    }
    out.observed_ms = now() - killedAt;
    out.final = snapshot('final');
  } else {
    const events = await doWorker(experiment === 'C' ? 'crash' : experiment === 'D' ? 'lost' : 'ask');
    out.acknowledged = events.some(e => e.event === 'receipt_ack' && e.status === 200);
    if (experiment === 'C') {
      if (hub.exitCode === null && hub.signalCode === null) await new Promise(resolve => hub.once('exit', resolve));
      await restart();
      out.after_restart = snapshot('after-restart');
      const c = out.after_restart.counts;
      const first = out.after_restart.runs.find(r => r.id === 1);
      out.atomic = (c.question_cards === 1 && c.audit_timers === 1 && first?.state === 'done') ||
        (c.question_cards === 0 && c.audit_timers === 0 && first?.state === 'claimed');
      out.ack_retained = !out.acknowledged || (c.question_cards === 1 && c.audit_timers === 1 && first?.state === 'done');
      await doWorker('retry');
    } else if (experiment === 'D') {
      await sleep(100); out.before_retry = snapshot('before-retry'); await doWorker('retry');
    }
    out.waiting = snapshot('waiting'); processList('question_open');
    if (experiment === 'A') {
      const before = usage(); await sleep(10000); const after = usage();
      out.idle = {before, after, elapsed_ms: after.ms - before.ms,
        cpu_ticks: after.cpu_ticks - before.cpu_ticks, clock_ticks_per_second: Number(spawnSync('getconf', ['CLK_TCK'], {encoding: 'utf8'}).stdout)};
      processList('after_idle'); note('idle_window', out.idle);
    }
    if (experiment === 'B') {
      await stopHub(); await restart(); const s = await api('/v1/state');
      out.question_survived = s.cards.filter(c => c.kind === 'ask' && c.title === 'Pick a colour').length === 1;
      out.after_restart = snapshot('after-restart');
    }
    await finishTask();
    if (experiment === 'E') {
      if (!await waitFor(() => killed && (hub.signalCode !== null || hub.exitCode !== null), 15000)) throw new Error('No notification-triggered hub kill');
      await restart();
      // Keep the documented one-minute delivery lease. No timing knobs or source edits.
      await sleep(65000);
      out.notification_deliveries = deliveries.filter(d => d.body.text.startsWith('Task complete')).length;
      out.sink_deliveries = deliveries;
    }
    out.final = snapshot('final');
    const c = out.final.counts;
    out.success = c.question_cards === 1 && c.completions === 1 && c.completion_cards === 1 && c.rounds === 2 && out.answer_in_context;
  }
  out.outcome = 'observed';
} catch (e) { out.outcome = 'harness-error'; out.error = String(e); note('harness_error', {message: out.error}); }
finally {
  if (worker && worker.exitCode === null && worker.signalCode === null) worker.kill('SIGKILL');
  if (hub && hub.exitCode === null && hub.signalCode === null) await stopHub('SIGTERM');
  if (sink) { sink.closeAllConnections(); await new Promise(resolve => sink.close(resolve)); }
  out.timeline.sort((a,b) => a.ms - b.ms);
  out.finished_utc = new Date().toISOString(); out.wall_ms = now();
  fs.writeFileSync('/work/out/result.json', JSON.stringify(out));
  console.log(JSON.stringify({experiment, run, variant, outcome: out.outcome, success: out.success, counts: out.final?.counts, error: out.error}));
}
