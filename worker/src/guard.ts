// Deterministic sensitive-action guard + usage/cost accounting helpers.
export const SENSITIVE_KEYWORDS = [
  // ported from slash/agent/policy.py (legacy loop)
  '确认支付', '立即支付', '确认付款', '密码支付', '确认转账', '转账', '注销账号', '删除账号', '永久删除',
  // extended
  '支付', '付款', '确认购买', '立即购买', '提交订单', '删除', '注销', '充值', '提现',
  'pay now', 'confirm payment', 'place order', 'buy now', 'transfer', 'delete account', 'permanently delete',
];
export const GUARDED_ACTIONS = new Set(['Tap', 'DoubleClick', 'LongPress', 'Input', 'KeyboardPress']);

export class SensitiveActionBlocked extends Error {
  constructor(public reason: string) { super('need_human: ' + reason); }
}

function keywords(): string[] {
  const extra = (process.env.MIDSCENE_SENSITIVE_KEYWORDS || '').split(',').map((s) => s.trim()).filter(Boolean);
  return [...SENSITIVE_KEYWORDS, ...extra];
}

/** Collect every string in the action params (locate prompt, value, ...). */
export function paramText(param: unknown, depth = 0): string {
  if (param == null || depth > 4) return '';
  if (typeof param === 'string') return param;
  if (typeof param !== 'object') return '';
  if (Array.isArray(param)) return param.map((p) => paramText(p, depth + 1)).join(' ');
  return Object.entries(param as Record<string, unknown>)
    .filter(([k]) => !['images', 'rect', 'center', 'bbox', 'point'].includes(k))
    .map(([, v]) => paramText(v, depth + 1)).join(' ');
}

export function sensitiveReason(actionName: string, param: unknown, allow: string[] = []): string | null {
  if (!GUARDED_ACTIONS.has(actionName)) return null;
  const blob = paramText(param).toLowerCase();
  for (const k of keywords()) {
    if (allow.includes(k)) continue;
    if (blob.includes(k.toLowerCase())) return `需要确认后才能继续：${k}（${actionName}: ${paramText(param).slice(0, 80)}）`;
  }
  return null;
}

export interface ActionLike { name: string; call: (param: any, ctx?: any) => any; [k: string]: any }
export function guardActions<T extends ActionLike>(actions: T[], allow: string[] = [], onBlock?: (r: string) => void): T[] {
  return actions.map((a) => {
    if (!GUARDED_ACTIONS.has(a.name)) return a;
    return { ...a, call: async (param: any, ctx?: any) => {
      const reason = sensitiveReason(a.name, param, allow);
      if (reason) { onBlock?.(reason); throw new SensitiveActionBlocked(reason); }
      return a.call(param, ctx);
    } };
  });
}

// ---- usage / cost ----
export interface Usage { calls: number; prompt_tokens: number; completion_tokens: number; total_tokens: number; cost_cny: number }
export function price(): { inPerM: number; outPerM: number } {
  // Doubao seed 2.1 turbo list price (docs/midscene-spike-results.md): ¥3/M in, ¥15/M out
  return { inPerM: Number(process.env.MIDSCENE_PRICE_IN_PER_M ?? 3), outPerM: Number(process.env.MIDSCENE_PRICE_OUT_PER_M ?? 15) };
}
export function costOf(prompt: number, completion: number): number {
  const p = price();
  return Math.round(((prompt * p.inPerM + completion * p.outPerM) / 1e6) * 1e5) / 1e5;
}
/** Sum every distinct `usage` object ({prompt_tokens, completion_tokens, total_tokens}) found in a dump. */
export function collectUsage(root: unknown): Usage {
  const seen = new Set<unknown>(); const usages: any[] = [];
  const walk = (o: any, d: number) => {
    if (!o || typeof o !== 'object' || seen.has(o) || d > 30) return; seen.add(o);
    if (o.usage && typeof o.usage === 'object' && 'total_tokens' in o.usage && !seen.has(o.usage)) { seen.add(o.usage); usages.push(o.usage); }
    for (const k in o) if (k !== 'usage' && k !== 'screenshot' && k !== 'screenshotBase64') walk(o[k], d + 1);
  };
  walk(root, 0);
  const sum = (k: string) => usages.reduce((s, u) => s + (Number(u[k]) || 0), 0);
  const pt = sum('prompt_tokens'), ct = sum('completion_tokens');
  return { calls: usages.length, prompt_tokens: pt, completion_tokens: ct, total_tokens: sum('total_tokens'), cost_cny: costOf(pt, ct) };
}
