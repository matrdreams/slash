// slash midscene worker: long-running HTTP JSON API that runs Midscene aiAct on Android devices.
// Endpoints: GET /health, POST /tasks, GET /tasks/:id, GET /tasks/:id/events[?after=N][&stream=1], POST /tasks/:id/cancel
import http from 'node:http';
import path from 'node:path';
import fs from 'node:fs';

export type TaskState = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'need_human';
export interface WorkerEvent { seq: number; type: string; ts: number; data: Record<string, unknown> }
export interface WorkerTask {
  id: string; device_serial: string; goal: string; max_steps?: number; context?: string;
  state: TaskState; result?: string; error?: string; report_path?: string; need_human_reason?: string;
  events: WorkerEvent[]; abort: AbortController; listeners: Set<(e: WorkerEvent) => void>;
}

const MOCK = process.env.MIDSCENE_WORKER_MOCK === '1';
const REPORT_DIR = process.env.MIDSCENE_WORKER_REPORT_DIR || path.resolve('midscene_run/report');
const tasks = new Map<string, WorkerTask>();
const deviceQueues = new Map<string, Promise<void>>();

class NeedHuman extends Error { constructor(public reason: string) { super('need_human: ' + reason); } }

function emit(t: WorkerTask, type: string, data: Record<string, unknown> = {}) {
  const e: WorkerEvent = { seq: t.events.length, type, ts: Date.now(), data };
  t.events.push(e);
  for (const l of t.listeners) l(e);
}
function finish(t: WorkerTask, state: TaskState, extra: Partial<WorkerTask> = {}) {
  Object.assign(t, extra); t.state = state;
  emit(t, 'done', { state, result: t.result, error: t.error, report_path: t.report_path, reason: t.need_human_reason });
}

const SENSITIVE_HINT = 'If the next step would pay money, transfer funds, delete data, send a message to others, or enter a password/verification code, or a login/captcha/QR scan is required, do NOT do it: call the RequestHuman action with a reason instead.';

async function runMock(t: WorkerTask) {
  const steps = Math.min(t.max_steps ?? 3, 3);
  for (let i = 0; i < steps; i++) {
    if (t.abort.signal.aborted) throw new Error('aborted');
    emit(t, 'step', { idx: i, phase: 'action_done', action: { name: i === 0 ? 'Launch' : 'Tap', target: `mock-${i}` } });
    await new Promise((r) => setTimeout(r, Number(process.env.MIDSCENE_WORKER_MOCK_DELAY_MS || 20)));
  }
  if (t.goal.includes('[need_human]')) throw new NeedHuman('mock: login required');
  if (t.goal.includes('[fail]')) throw new Error('mock failure');
  const report = path.join(REPORT_DIR, `slash-${t.id}.html`);
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(report, `<html><body>mock report ${t.id}</body></html>`);
  t.report_path = report;
  return 'mock ok';
}

async function runReal(t: WorkerTask) {
  const { AndroidDevice, AndroidAgent } = await import('@midscene/android');
  const { defineAction, z } = (await import('@midscene/core')) as any;
  const requestHuman = defineAction({
    name: 'RequestHuman',
    description: 'Hand control to a human: use for login, captcha, QR scan, payment, or any sensitive/irreversible action needing confirmation.',
    paramSchema: z.object({ reason: z.string().describe('why a human is needed') }),
    call: async (p: { reason: string }) => { throw new NeedHuman(p?.reason || 'need human'); },
  });
  const device = new AndroidDevice(t.device_serial, {
    imeStrategy: (process.env.MIDSCENE_IME_STRATEGY as any) || 'yadb-for-non-ascii',
    customActions: [requestHuman],
  } as any);
  await device.connect();
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  process.env.MIDSCENE_RUN_DIR = process.env.MIDSCENE_RUN_DIR || path.dirname(REPORT_DIR);
  const agent = new AndroidAgent(device, {
    reportFileName: `slash-${t.id}`,
    replanningCycleLimit: t.max_steps,
    aiActContext: [SENSITIVE_HINT, t.context || ''].filter(Boolean).join('\n'),
  } as any);
  let idx = 0;
  agent.addProgressListener((ev: any) => {
    if (ev.scope !== 'aiAct') return;
    if (['plan_planned', 'action_done', 'action_failed', 'plan_failed'].includes(ev.phase)) {
      const d = ev.data || {};
      emit(t, 'step', { idx: idx++, phase: ev.phase, action: d.action ?? d.actions ?? null, thought: d.thought ?? d.log ?? undefined });
    }
  });
  try {
    const out = await agent.aiAct(t.goal, { abortSignal: t.abort.signal } as any);
    return typeof out === 'string' ? out : 'done';
  } finally {
    t.report_path = (agent as any).reportFile;
    try { await agent.destroy(); } catch { /* ignore */ }
  }
}

function findNeedHuman(e: any, depth = 0): NeedHuman | undefined {
  if (!e || depth > 5) return;
  if (e instanceof NeedHuman) return e;
  const m = /need_human: (.*)/.exec(String(e?.message || ''));
  if (m) return new NeedHuman(m[1].split('\n')[0]);
  return findNeedHuman(e.cause, depth + 1);
}

async function execute(t: WorkerTask) {
  if (t.abort.signal.aborted) return;
  t.state = 'running'; emit(t, 'status', { state: 'running' });
  try {
    const result = await (MOCK ? runMock(t) : runReal(t));
    if (t.abort.signal.aborted) return finish(t, 'cancelled');
    finish(t, 'succeeded', { result });
  } catch (e: any) {
    if (t.abort.signal.aborted) return finish(t, 'cancelled');
    const nh = findNeedHuman(e);
    if (nh) return finish(t, 'need_human', { need_human_reason: nh.reason });
    finish(t, 'failed', { error: String(e?.message || e).slice(0, 2000) });
  }
}

export function submit(body: any): WorkerTask {
  const id = String(body.task_id || `t${Date.now()}${Math.random().toString(16).slice(2, 6)}`);
  if (!body.device_serial || !body.goal) throw Object.assign(new Error('device_serial and goal required'), { status: 400 });
  if (tasks.has(id) && !['succeeded', 'failed', 'cancelled', 'need_human'].includes(tasks.get(id)!.state))
    throw Object.assign(new Error('task already active'), { status: 409 });
  const t: WorkerTask = { id, device_serial: String(body.device_serial), goal: String(body.goal), max_steps: body.max_steps,
    context: body.context, state: 'queued', events: [], abort: new AbortController(), listeners: new Set() };
  tasks.set(id, t);
  emit(t, 'status', { state: 'queued' });
  // serialize per device
  const prev = deviceQueues.get(t.device_serial) || Promise.resolve();
  const next = prev.then(() => execute(t)).catch(() => {});
  deviceQueues.set(t.device_serial, next);
  return t;
}

export function view(t: WorkerTask) {
  const { abort, listeners, events, ...rest } = t;
  return { ...rest, event_count: events.length };
}

function send(res: http.ServerResponse, code: number, obj: unknown) {
  res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(obj));
}
async function readBody(req: http.IncomingMessage): Promise<any> {
  const chunks: Buffer[] = []; for await (const c of req) chunks.push(c as Buffer);
  return chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {};
}

export function createServer() {
  return http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url || '/', 'http://x');
      const parts = url.pathname.split('/').filter(Boolean);
      if (req.method === 'GET' && url.pathname === '/health')
        return send(res, 200, { ok: true, mock: MOCK, model: process.env.MIDSCENE_MODEL_NAME || null, tasks: tasks.size });
      if (req.method === 'POST' && url.pathname === '/tasks') return send(res, 200, view(submit(await readBody(req))));
      if (parts[0] === 'tasks' && parts[1]) {
        const t = tasks.get(parts[1]);
        if (!t) return send(res, 404, { error: 'not found' });
        if (req.method === 'GET' && parts.length === 2) return send(res, 200, view(t));
        if (req.method === 'POST' && parts[2] === 'cancel') {
          if (t.state === 'queued' || t.state === 'running') {
            t.abort.abort();
            if (t.state === 'queued') finish(t, 'cancelled');
          }
          return send(res, 200, view(t));
        }
        if (req.method === 'GET' && parts[2] === 'events') {
          const after = Number(url.searchParams.get('after') ?? -1);
          if (url.searchParams.get('stream') !== '1')
            return send(res, 200, { state: t.state, events: t.events.filter((e) => e.seq > after) });
          res.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache' });
          const write = (e: WorkerEvent) => { res.write(`event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`); if (e.type === 'done') res.end(); };
          for (const e of t.events.filter((e) => e.seq > after)) write(e);
          if (t.events.some((e) => e.type === 'done')) return;
          t.listeners.add(write); req.on('close', () => t.listeners.delete(write));
          return;
        }
      }
      send(res, 404, { error: 'not found' });
    } catch (e: any) {
      send(res, e?.status || 500, { error: String(e?.message || e) });
    }
  });
}

if (process.argv[1] && /server\.(ts|js)$/.test(process.argv[1])) {
  const port = Number(process.env.MIDSCENE_WORKER_PORT || 8790);
  const host = process.env.MIDSCENE_WORKER_HOST || '127.0.0.1';
  createServer().listen(port, host, () => console.log(`midscene-worker listening on ${host}:${port} mock=${MOCK}`));
}
