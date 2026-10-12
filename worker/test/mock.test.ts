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
