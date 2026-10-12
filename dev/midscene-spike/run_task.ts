import { AndroidDevice, AndroidAgent } from '@midscene/android';
import fs from 'fs';
const [name, prompt] = process.argv.slice(2);
(async () => {
  const d = new AndroidDevice('127.0.0.1:15555'); await d.connect();
  const a = new AndroidAgent(d, { reportFileName: `ms-${name}` } as any);
  const t = Date.now(); let err = '';
  try { await a.aiAct(prompt); } catch (e: any) { err = String(e?.message || e).slice(0, 400); }
  const wall = (Date.now() - t) / 1000;
  const usages: any[] = [];
  const walk = (o: any) => { if (!o || typeof o !== 'object') return; if (o.usage && typeof o.usage === 'object' && 'total_tokens' in o.usage) usages.push(o.usage); for (const k in o) if (k !== 'usage') walk(o[k]); };
  try { walk(JSON.parse((a as any).dumpDataString())); } catch (e) { walk((a as any).dump); }
  const sum = (k: string) => usages.reduce((s, u) => s + (u[k] || 0), 0);
  const out = { name, prompt, wall, err, calls: usages.length, prompt_tokens: sum('prompt_tokens'), completion_tokens: sum('completion_tokens'), total_tokens: sum('total_tokens'), report: (a as any).reportFile };
  console.log('RESULT ' + JSON.stringify(out));
  process.exit(0);
})();
