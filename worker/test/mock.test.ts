import { test } from 'node:test';
import assert from 'node:assert';
import type { AddressInfo } from 'node:net';
import { createServer } from '../src/server.ts';

async function withServer(fn: (base: string) => Promise<void>) {
  const s = createServer(); await new Promise<void>((r) => s.listen(0, '127.0.0.1', r));
  try { await fn(`http://127.0.0.1:${(s.address() as AddressInfo).port}`); } finally { s.close(); }
}
const post = (u: string, b: unknown) => fetch(u, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(b) }).then((r) => r.json());
async function waitDone(base: string, id: string) {
  for (let i = 0; i < 200; i++) { const r: any = await (await fetch(`${base}/tasks/${id}/events`)).json(); if (r.events.some((e: any) => e.type === 'done')) return r; await new Promise((r) => setTimeout(r, 10)); }
  throw new Error('timeout');
}

test('health + success + need_human + cancel + serialize', async () => {
  await withServer(async (base) => {
    assert.equal(((await (await fetch(`${base}/health`)).json()) as any).mock, true);
    await post(`${base}/tasks`, { task_id: 'a', device_serial: 'd1', goal: 'open settings' });
    await post(`${base}/tasks`, { task_id: 'b', device_serial: 'd1', goal: 'login [need_human]' });
    const c: any = await post(`${base}/tasks`, { task_id: 'c', device_serial: 'd1', goal: 'x' });
    assert.equal(c.state, 'queued');
    await post(`${base}/tasks/c/cancel`, {});
    const a = await waitDone(base, 'a');
    assert.equal(a.state, 'succeeded');
    assert.ok(a.events.filter((e: any) => e.type === 'step').length >= 1);
    assert.ok(a.events.at(-1).data.report_path);
    const b = await waitDone(base, 'b');
    assert.equal(b.state, 'need_human');
    assert.equal(b.events.at(-1).data.reason, 'mock: login required');
    assert.equal((await waitDone(base, 'c')).state, 'cancelled');
    const sse = await (await fetch(`${base}/tasks/a/events?stream=1`)).text();
    assert.match(sse, /event: done/);
  });
});

test('sensitive guard blocks tap on payment button -> need_human', async () => {
  await withServer(async (base) => {
    await post(`${base}/tasks`, { task_id: 'g1', device_serial: 'd2', goal: 'buy [tap:确认支付 button]' });
    const r = await waitDone(base, 'g1');
    assert.equal(r.state, 'need_human');
    assert.match(r.events.at(-1).data.reason, /确认支付/);
    await post(`${base}/tasks`, { task_id: 'g2', device_serial: 'd2', goal: 'buy [tap:确认支付 button]', allow_sensitive: ['确认支付', '支付'] });
    assert.equal((await waitDone(base, 'g2')).state, 'succeeded');
    await post(`${base}/tasks`, { task_id: 'g3', device_serial: 'd2', goal: 'x [tap:Delete account]' });
    assert.equal((await waitDone(base, 'g3')).state, 'need_human');
  });
});

test('usage events, cost, and max_cost_cny budget', async () => {
  await withServer(async (base) => {
    await post(`${base}/tasks`, { task_id: 'u1', device_serial: 'd3', goal: 'ok [usage:1000]' });
    const r = await waitDone(base, 'u1');
    assert.equal(r.state, 'succeeded');
    const u = r.events.at(-1).data.usage;
    assert.equal(u.prompt_tokens, 3000); assert.equal(u.completion_tokens, 30);
    assert.equal(u.cost_cny, (3000 * 3 + 30 * 15) / 1e6);
    assert.ok(r.events.some((e: any) => e.type === 'usage'));
    await post(`${base}/tasks`, { task_id: 'u2', device_serial: 'd3', goal: 'big [usage:100000]', max_cost_cny: 0.5 });
    const b = await waitDone(base, 'u2');
    assert.equal(b.state, 'failed');
    assert.match(b.events.at(-1).data.error, /budget exceeded/);
  });
});

import { sensitiveReason, collectUsage } from '../src/guard.ts';
test('guard unit + usage walker', () => {
  assert.ok(sensitiveReason('Tap', { locate: { prompt: '立即支付' } }));
  assert.ok(sensitiveReason('Input', { value: 'x', locate: { prompt: '转账金额' } }));
  assert.equal(sensitiveReason('Scroll', { locate: { prompt: '支付' } }), null);
  assert.equal(sensitiveReason('Tap', { locate: { prompt: 'Display' } }), null);
  const u = collectUsage({ a: [{ usage: { prompt_tokens: 10, completion_tokens: 2, total_tokens: 12 } }, { b: { usage: { prompt_tokens: 5, completion_tokens: 1, total_tokens: 6 } } }] });
  assert.equal(u.calls, 2); assert.equal(u.total_tokens, 18);
});
