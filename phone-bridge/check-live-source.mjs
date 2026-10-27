// Local diagnostic only: exercise the native camera with moving test patterns.
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { IvfFrames, LiveWebM } from './live-webm.mjs';
const filename = process.argv[2];
if (!filename) throw new Error('Usage: node check-live-source.mjs NEW_OUTPUT.webm');
const encoded = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i',
  'testsrc2=size=640x480:rate=30:duration=2', '-c:v', 'libvpx-vp9', '-deadline', 'realtime',
  '-cpu-used', '8', '-g', '1', '-threads', '2', '-f', 'ivf', 'pipe:1'], { maxBuffer: 16 * 1024 * 1024 });
if (encoded.status !== 0) throw new Error(encoded.stderr.toString());
const frames = [];
new IvfFrames(frame => frames.push(frame)).push(encoded.stdout);
const live = new LiveWebM(filename, frames[0]);
let index = 0;
setInterval(() => live.update(frames[++index % frames.length]), 1000 / 24);
process.stdout.write(`Native camera diagnostic: ${filename}\n`);
process.on('SIGINT', () => { live.close(); process.exit(0); });
process.on('SIGTERM', () => { live.close(); process.exit(0); });
