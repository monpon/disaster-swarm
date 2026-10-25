// Run measure.mjs over a set of feeds, then summarise against feeds/truth.json.
//
//   node bench.mjs <image stem> [<image stem> ...]     measure all 4 variants of each image
//   node bench.mjs --summary                          only rebuild results/bench.json
//
// Each clip costs SmartSpectra credits (1 credit = 30 s), so measured clips are
// skipped if results/raw/<feed>.json already exists.
import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const raw = join(root, 'results', 'raw');
const truth = JSON.parse(readFileSync(join(root, 'feeds', 'truth.json'), 'utf8'));
const VARIANTS = ['static', 'calm', 'distress', 'drone'];

const args = process.argv.slice(2);
if (!args.includes('--summary')) {
  for (const stem of args) {
    for (const v of VARIANTS) {
      const name = `${stem}__${v}`;
      const out = join(raw, `${name}.json`);
      if (existsSync(out)) continue;
      const r = spawnSync('node', [join(root, 'node', 'measure.mjs'), join(root, 'feeds', `${name}.mp4`), out, '--realtime'],
        { stdio: ['ignore', 'inherit', 'pipe'], maxBuffer: 64 << 20 });
      if (r.status !== 0) {
        const tail = r.stderr.toString().split('\n').filter((l) => !/^[WI]0000/.test(l)).slice(-8).join('\n');
        console.log(`${name}: FAILED status=${r.status} signal=${r.signal}\n${tail}`);
      }
    }
  }
}

const median = (xs) => {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
};
const round = (x) => (x == null ? null : Math.round(x * 10) / 10);

const rows = [];
for (const file of readdirSync(raw).filter((f) => f.endsWith('.json')).sort()) {
  const name = file.slice(0, -5);
  const log = JSON.parse(readFileSync(join(raw, file), 'utf8'));
  const pulse = log.metrics.flatMap((m) => m.data.cardio?.pulseRate ?? []);
  // Still photos still produce pulse readings; they are never stable with high confidence.
  const trusted = pulse.filter((p) => p.stable && (p.confidence ?? 0) >= 80);
  const breath = log.metrics.flatMap((m) => m.data.breathing?.rate ?? []);
  const firstWall = (key) => log.metrics.find((m) => key(m.data))?.wall_ms ?? null;
  const t = truth[name] ?? {};
  const okFrames = log.validation['0']?.count ?? 0;
  rows.push({
    name, image: t.image, variant: t.variant, skin: round((t.skin ?? 0) * 100),
    truth_hr: t.hr, hr: round(median(pulse.map((p) => p.value))),
    hr_conf: round(median(pulse.map((p) => p.confidence ?? 0))), hr_n: pulse.length,
    hr_trusted: round(median(trusted.map((p) => p.value))), hr_trusted_n: trusted.length,
    truth_rr: t.rr, rr: round(median(breath.map((p) => p.value))), rr_n: breath.length,
    first_hr_s: round(firstWall((d) => d.cardio?.pulseRate) / 1000),
    first_rr_s: round(firstWall((d) => d.breathing?.rate) / 1000),
    ok_frame_pct: round((100 * okFrames) / log.frames),
    validation: Object.fromEntries(Object.entries(log.validation).map(([k, v]) => [k, v.count])),
    errors: log.errors.map((e) => `${e.code}:${e.message}`),
  });
}
writeFileSync(join(root, 'results', 'bench.json'), JSON.stringify(rows, null, 1));
console.table(rows.map(({ validation, errors, image, ...r }) => ({ ...r, errors: errors.length })));
