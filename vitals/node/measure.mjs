// Stream a video file through the SmartSpectra SDK's custom-input path, the same
// path a backend would use for frames arriving from the drone relay.
//
//   node measure.mjs <feed.mp4> <out.json> [--realtime]
//
// Decodes with ffmpeg to raw RGB, pushes every frame with sendFrame(), and writes
// every metrics packet, validation status, and error to <out.json>.
// --realtime paces frames at the clip frame rate (default: as fast as accepted).
import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  SmartSpectraSDK, FrameTransform, PixelFormat, breathingMetrics, cardioMetrics, decodeMetrics,
} from '@smartspectra/node-sdk';

const FPS = 30;
const [, , feed, out, ...flags] = process.argv;
const realtime = flags.includes('--realtime');

function apiKey() {
  if (process.env.PRESAGE_API_KEY) return process.env.PRESAGE_API_KEY;
  const env = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '.env'), 'utf8');
  return env.match(/^PRESAGE_API_KEY=(.*)$/m)[1].trim();
}

function probeSize(path) {
  return new Promise((resolve, reject) => {
    const p = spawn('ffprobe', ['-v', 'error', '-select_streams', 'v:0', '-show_entries',
      'stream=width,height', '-of', 'csv=p=0', path]);
    let s = '';
    p.stdout.on('data', (d) => { s += d; });
    p.on('close', (code) => (code ? reject(new Error(`ffprobe ${code}`)) : resolve(s.trim().split(',').map(Number))));
  });
}

const [width, height] = await probeSize(feed);
const frameBytes = width * height * 3;
const log = { feed, width, height, metrics: [], validation: {}, errors: [], status: [] };
const t0 = Date.now();

const sdk = new SmartSpectraSDK({
  apiKey: apiKey(),
  requestedMetrics: [...breathingMetrics, ...cardioMetrics],
  enableAccumulatedOutput: true,
});
sdk.on('processingStatus', (s) => log.status.push([Date.now() - t0, s]));
sdk.on('validationStatus', (code, ts, hint) => {
  const v = (log.validation[code] ??= { count: 0, hint, first_us: ts });
  v.count += 1;
});
sdk.on('metrics', (buf, ts) => {
  log.metrics.push({ ts, wall_ms: Date.now() - t0, data: decodeMetrics(buf) });
});
sdk.on('error', (code, message, retryable) => log.errors.push({ code, message, retryable, wall_ms: Date.now() - t0 }));

sdk.useCustomInput(FrameTransform.kNone);
await sdk.start();

const ff = spawn('ffmpeg', ['-loglevel', 'error', '-i', feed, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']);
let pending = Buffer.alloc(0);
let frame = 0;
for await (const chunk of ff.stdout) {
  pending = Buffer.concat([pending, chunk]);
  while (pending.length >= frameBytes) {
    const buf = pending.subarray(0, frameBytes);
    pending = pending.subarray(frameBytes);
    const tsUs = Math.round((frame * 1e6) / FPS);
    sdk.sendFrame(buf, width, height, width * 3, PixelFormat.kRGB, tsUs);
    frame += 1;
    if (realtime) {
      const lag = t0 + (frame * 1000) / FPS - Date.now();
      if (lag > 0) await new Promise((r) => setTimeout(r, lag));
    }
  }
}
log.frames = frame;
log.send_ms = Date.now() - t0;
await sdk.stopAsync();
log.total_ms = Date.now() - t0;
await sdk.destroy();
writeFileSync(out, JSON.stringify(log, null, 1));
console.log(`${feed}: frames=${frame} metrics=${log.metrics.length} errors=${log.errors.length} ` +
  `validation=${JSON.stringify(Object.fromEntries(Object.entries(log.validation).map(([k, v]) => [k, v.count])))} ` +
  `${log.total_ms}ms`);
