// Exercise the complete network -> encoder -> seekable native-file path.
// Run only with Camera Feed Preview / CameraProbe, never a verification screen.
import { spawnSync } from 'node:child_process';
import WebSocket from 'ws';
const url = process.argv[2];
if (!url) throw new Error('Pass the authenticated local wss://.../bridge/camera URL.');
const encoded = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i',
  'testsrc2=size=360x480:rate=24:duration=1', '-threads', '1', '-c:v', 'mjpeg', '-q:v', '5',
  '-f', 'image2pipe', 'pipe:1'], { maxBuffer: 8 * 1024 * 1024 });
if (encoded.status !== 0) throw new Error(encoded.stderr.toString());
const frames = [];
let offset = 0;
while (offset < encoded.stdout.length) {
  const end = encoded.stdout.indexOf(Buffer.from([255, 217]), offset);
  if (end < 0) break;
  frames.push(encoded.stdout.subarray(offset, end + 2)); offset = end + 2;
}
const socket = new WebSocket(url, { rejectUnauthorized: false });
let sent = 0, received = 0, pending = [];
const latencies = [];
let timer, summary;
socket.on('open', () => {
  timer = setInterval(() => {
    if (pending.length >= 2) return;
    socket.send(frames[sent++ % frames.length]); pending.push(performance.now());
  }, 1000 / 24);
  summary = setInterval(() => console.log(JSON.stringify({ sent, received, pending: pending.length })), 10000);
});
socket.on('message', data => {
  if (!JSON.parse(data).ack) return;
  received++;
  if (pending.length) latencies.push(performance.now() - pending.shift());
});
socket.on('error', error => { console.error(error.message); process.exitCode = 1; });
function stop() {
  clearInterval(timer); clearInterval(summary);
  latencies.sort((a, b) => a - b);
  console.log(JSON.stringify({ sent, received, encoder_round_trip_p50_ms: latencies[Math.floor(latencies.length * .5)], encoder_round_trip_p95_ms: latencies[Math.floor(latencies.length * .95)] }));
  socket.close();
}
setTimeout(stop, 120000);
process.on('SIGINT', () => { stop(); process.exit(0); });
socket.on('close', () => { clearInterval(timer); clearInterval(summary); process.exit(); });
