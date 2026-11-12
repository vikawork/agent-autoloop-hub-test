// Deterministic HTTP worker. No agent CLI, model, SDK or project imports.
import http from 'node:http';
import net from 'node:net';
import fs from 'node:fs';

const [mode, origin, hubPid, delayString] = process.argv.slice(2);
const stamp = () => Number(process.hrtime.bigint() - BigInt(origin)) / 1e6;
const emit = (event, values = {}) => console.log(JSON.stringify({ms: stamp(), event, ...values}));
const keys = JSON.parse(fs.readFileSync('/work/state/keys.json', 'utf8'));
async function api(path, key, body) {
  const r = await fetch(`http://127.0.0.1:3350${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: {authorization: `Bearer ${key}`, 'content-type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000),
  });
  const data = await r.json();
  if (!r.ok) throw new Error(`HTTP ${r.status}: ${JSON.stringify(data)}`);
  return data;
}
function crash() {
  try { process.kill(Number(hubPid), 'SIGKILL'); emit('hub_kill_sent'); }
  catch (e) { emit('hub_kill_error', {code: e.code}); }
}
function receipt(job) {
  if (job.context.answers.length) return {
    outcome: 'done', summary: 'Task complete: Blue',
    notice: [{title: 'Task complete', text: 'Blue selected.', key: 'complete', fyi: true}],
    later: [{key: 'audit-check', cancel: true}],
  };
  return {outcome: 'done', summary: 'Waiting for colour',
    ask: [{title: 'Pick a colour', text: 'Choose Blue or Green.', options: ['Blue', 'Green'],
           key: 'colour', about: 'Finish after the colour answer; do not ask again.'}],
    later: [{key: 'audit-check', at: new Date(Date.now() + 3600000).toISOString(), about: 'Atomic receipt witness'}],
  };
}
async function submit(job, result, killDelay) {
  const body = JSON.stringify(result);
  const delay = Number(killDelay);
  if (killDelay !== undefined && delay < 0) { crash(); await new Promise(r => setTimeout(r, -delay)); }
  return await new Promise(resolve => {
    const req = http.request({hostname: '127.0.0.1', port: 3350,
      path: `/v1/runs/${job.run}/result`, method: 'POST',
      headers: {authorization: `Bearer ${job.token}`, 'content-type': 'application/json',
                'content-length': Buffer.byteLength(body)}}, res => {
      let text = ''; res.on('data', c => text += c);
      res.on('end', () => { emit('receipt_ack', {status: res.statusCode, body: text}); resolve(); });
    });
    req.on('error', e => { emit('receipt_error', {code: e.code}); resolve(); });
    req.setTimeout(15000, () => req.destroy(new Error('request timeout')));
    emit('receipt_send_start'); req.end(body); emit('receipt_send_end');
    if (killDelay !== undefined && delay >= 0) setTimeout(crash, delay);
  });
}
async function lost(job, result) {
  const body = JSON.stringify(result);
  const request = `POST /v1/runs/${job.run}/result HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer ${job.token}\r\nContent-Type: application/json\r\nContent-Length: ${Buffer.byteLength(body)}\r\nConnection: close\r\n\r\n${body}`;
  await new Promise((resolve, reject) => {
    const socket = net.createConnection({host: '127.0.0.1', port: 3350}, () => {
      socket.write(request, () => { emit('receipt_socket_closed_without_read'); socket.destroy(); resolve(); });
    });
    socket.on('error', reject);
    // Deliberately no response/data listener.
  });
}
try {
  if (mode === 'retry') {
    const {job, result} = JSON.parse(fs.readFileSync('/work/state/first.json', 'utf8'));
    await submit(job, result);
  } else {
    const {job} = await api(`/v1/work?claim=${mode === 'complete' ? 'answer' : 'first'}&wait=0&running=&capacity=1`, keys.worker);
    if (!job) throw new Error('No job available');
    emit('claimed', {run: job.run, attempt: job.attempt, context: job.context, session: job.session});
    if (mode === 'hold') { setInterval(() => {}, 1000); }
    else {
      const result = receipt(job);
      if (mode !== 'complete') fs.writeFileSync('/work/state/first.json', JSON.stringify({job, result}));
      emit('receipt_prepared', {run: job.run, result});
      if (mode === 'lost') await lost(job, result);
      else await submit(job, result, mode === 'crash' ? delayString : undefined);
    }
  }
} catch (e) { emit('worker_error', {message: String(e)}); process.exitCode = 1; }
