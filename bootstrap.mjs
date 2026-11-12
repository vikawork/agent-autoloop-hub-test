// Runs only in Docker. Provision isolated fixture keys through the project's administrative API.
import fs from 'node:fs';
fs.mkdirSync('/work/state', {recursive: true});
const rules = {timezone: 'UTC', askFirst: [], sources: {input: {name: 'Fixture input'}},
  agents: {script: {name: 'Deterministic script', worker: 'script-worker', use: 'command', command: ['node', '/work/worker.mjs']}},
  channels: {sink: {name: 'Local sink', answerers: [], links: false}},
  rules: [{name: 'Colour task', when: {source: 'input', types: ['colour.pick']}, to: 'script',
    cwd: '/work/state', prompt: 'Ask Blue or Green, then finish after the answer.'}]};
fs.writeFileSync('/work/state/rules.json', JSON.stringify(rules));
const runtime = await import('/src/host/runtime.ts');
const keys = {};
for (const [kind, name] of [['source', 'input'], ['worker', 'script-worker'], ['owner', 'fixture'], ['channel', 'sink']])
  keys[kind] = runtime.addKey(kind, name);
fs.writeFileSync('/work/state/keys.json', JSON.stringify(keys), {mode: 0o600});
const config = {url: 'http://127.0.0.1:3350', hub: {listen: '127.0.0.1:3350'}};
if (process.argv[2] === 'E') config.channels = {sink: {use: 'webhook', key: keys.channel,
  url: 'http://127.0.0.1:3351/notify', platform: 'slack'}};
fs.writeFileSync('/work/state/config.json', JSON.stringify(config), {mode: 0o600});
runtime.db.close();
console.log('Isolated fixture provisioned');
