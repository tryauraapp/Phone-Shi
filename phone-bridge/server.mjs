import crypto from 'node:crypto';
import fs from 'node:fs';
import http from 'node:http';
import https from 'node:https';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import httpProxy from 'http-proxy';
import QRCode from 'qrcode';
import { WebSocketServer } from 'ws';
import { IvfFrames, LiveWebM } from './live-webm.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.dirname(here);
const web = path.join(here, 'web');
const avd = process.env.EMU_AVD || 'Galaxy_S25_20261027_tinder_f001699c';
const serial = process.env.EMU_SERIAL || 'emulator-5554';
const liveDirectory = path.join(root, '.local', 'live-camera');
fs.mkdirSync(liveDirectory, { recursive: true });
// Native camera names are space-delimited internally, so keep this pathname
// outside workspace directories which may contain spaces.
const liveFile = path.join(os.tmpdir(), `emu-camera-${crypto.createHash('sha256').update(avd).digest('hex').slice(0, 16)}.webm`);
const bind = process.env.BRIDGE_BIND || '0.0.0.0';
const httpsPort = Number(process.env.BRIDGE_HTTPS_PORT || 3443);
const httpPort = Number(process.env.BRIDGE_HTTP_PORT || 3080);
const controllerPort = Number(process.env.EMU_CONTROLLER_PORT || 3300);
// Browser screen encoding shares guest CPU with the camera consumer. Keep
// its workload bounded without changing the physical camera stream.
const displayFps = process.env.EMU_DISPLAY_FPS || '30';
const displaySize = process.env.EMU_DISPLAY_SIZE || '960';
const displayBitRate = process.env.EMU_DISPLAY_BIT_RATE || '4000000';
const liveCameraEnabled = process.env.EMU_LIVE_CAMERA !== '0';
const lanIp = process.env.BRIDGE_LAN_IP || Object.values(os.networkInterfaces()).flat()
  .find((item) => item?.family === 'IPv4' && !item.internal)?.address;
const pairToken = process.env.BRIDGE_TOKEN || crypto.randomBytes(18).toString('base64url');
const phoneToken = process.env.EMU_CONTROLLER_TOKEN || crypto.randomBytes(24).toString('base64url');
const cert = process.env.BRIDGE_CERT || path.join(here, '.certs', `${lanIp}.pem`);
const key = process.env.BRIDGE_KEY || path.join(here, '.certs', `${lanIp}-key.pem`);
const ca = process.env.BRIDGE_CA || '';
if (!lanIp) throw new Error('No LAN IPv4 address found. Set BRIDGE_LAN_IP.');
if (!fs.existsSync(cert) || !fs.existsSync(key)) throw new Error(`TLS certificate missing. Run ./prepare_tls.sh ${lanIp}`);

const state = { phase: 'starting-controller', detail: 'Connecting to Android.', camera: false, phone: false, cameraFrames: 0, cameraLastFrameAt: null };
let ffmpeg = null;
let emulator = null;
let controller = null;
let controllerGeneration = Date.now();
let live = null;
let cameraSocket = null;
let cameraApplied = false;
let blankFrame;
function clearLiveFrame() {
  if (!live) return;
  if (!blankFrame) {
    const result = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i', 'color=black:size=640x480',
      '-frames:v', '1', '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8',
      '-threads', '1', '-g', '1', '-f', 'ivf', 'pipe:1'], { timeout: 5000 });
    if (result.status !== 0) return;
    new IvfFrames(frame => { blankFrame = frame; }).push(result.stdout);
  }
  if (blankFrame) live.update(blankFrame);
}
const setState = (phase, detail, extra = {}) => {
  Object.assign(state, { phase, detail, ...extra });
  process.stdout.write(`[bridge] ${phase}: ${detail}\n`);
};
const run = (command, args) => new Promise((resolve) => {
  const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
  let output = '';
  child.stdout.on('data', (chunk) => { output += chunk; });
  child.stderr.on('data', (chunk) => { output += chunk; });
  child.on('error', (error) => resolve({ code: -1, output: error.message }));
  child.on('close', (code) => resolve({ code, output }));
});
async function waitForBoot() {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const result = await run('adb', ['-s', serial, 'shell', 'getprop', 'sys.boot_completed']);
    if (result.code === 0 && result.output.trim() === '1') return;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error('Android did not finish booting within 90 seconds.');
}
async function waitForController() {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const ready = await new Promise((resolve) => {
      const request = http.get({
        hostname: '127.0.0.1', port: controllerPort, path: '/health',
        headers: { authorization: `Bearer ${phoneToken}` }, timeout: 1000,
      }, (response) => { response.resume(); resolve(response.statusCode === 200); });
      request.on('error', () => resolve(false));
      request.on('timeout', () => { request.destroy(); resolve(false); });
    });
    if (ready) return;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error('Phone controller did not become ready.');
}
function startDecoder(socket) {
  const parser = new IvfFrames(frame => {
    if (!live) live = new LiveWebM(liveFile, frame, { reuse: true });
    else live.update(frame);
    Object.assign(state, { camera: true, cameraFrames: state.cameraFrames + 1, cameraLastFrameAt: Date.now() });
    if (socket.readyState === 1) socket.send(JSON.stringify({ ack: true, at: Date.now() }));
    if (!cameraApplied) void applyLiveCamera();
  });
  ffmpeg = spawn('ffmpeg', [
    '-hide_banner', '-loglevel', 'warning', '-probesize', '32', '-analyzeduration', '0',
    '-f', 'image2pipe', '-framerate', '24', '-vcodec', 'mjpeg', '-threads', '1', '-i', 'pipe:0',
    '-map', '0:v:0', '-an', '-vf',
    'scale=360:480:force_original_aspect_ratio=increase:force_divisible_by=2,setsar=1,crop=360:480:trunc((iw-ow)/4)*2:trunc((ih-oh)*0.40625/2)*2,pad=640:480:0:0:black,setsar=1',
    '-c:v', 'libvpx-vp9', '-deadline', 'realtime', '-cpu-used', '8', '-row-mt', '1',
    '-threads', '2', '-lag-in-frames', '0', '-g', '1', '-crf', '32', '-b:v', '0', '-pix_fmt', 'yuv420p',
    '-flush_packets', '1', '-f', 'ivf', 'pipe:1',
  ], { stdio: ['pipe', 'pipe', 'pipe'] });
  const decoder = ffmpeg;
  decoder.stdout.on('data', chunk => {
    if (cameraSocket !== socket) return;
    try { parser.push(chunk); }
    catch (error) { state.detail = `Camera update failed: ${error.message}`; socket.close(1011, 'Camera update failed'); }
  });
  ffmpeg.stderr.on('data', (chunk) => process.stderr.write(`[camera] ${chunk}`));
  ffmpeg.stdin.on('error', (error) => {
    if (error.code !== 'EPIPE') process.stderr.write(`[camera] input error: ${error.message}\n`);
  });
  ffmpeg.on('error', error => { state.detail = error.message; socket.close(1011, 'Camera encoder unavailable'); });
  ffmpeg.on('close', () => {
    if (ffmpeg === decoder) ffmpeg = null;
    if (cameraSocket === socket) state.camera = false;
  });
}
async function applyLiveCamera() {
  if (cameraApplied) return;
  cameraApplied = true;
  try {
    const identity = await run('adb', ['-s', serial, 'emu', 'avd', 'name']);
    if (identity.code !== 0 || identity.output.split(/\r?\n/)[0].trim() !== avd) throw new Error('The connected phone does not match the selected AVD.');
    // If the bridge was restarted, reuse the running native camera unchanged.
    const processes = await run('ps', ['-ax', '-o', 'command=']);
    if (processes.output.split('\n').some(line => line.includes('qemu-system-aarch64') && line.includes(avd) && line.includes(`videofile:${liveFile}`))) return;
    setState('restarting-phone', 'Connecting the live camera. Android will be back shortly.', { camera: true, phone: false });
    const previousController = controller;
    controller = null;
    previousController?.kill('SIGTERM');
    await run('adb', ['-s', serial, 'emu', 'kill']);
    for (let attempt = 0; attempt < 30; attempt++) {
      const result = await run('adb', ['-s', serial, 'shell', 'getprop', 'sys.boot_completed']);
      if (result.code !== 0) break;
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    const log = fs.openSync(path.join(liveDirectory, 'emulator-live.log'), 'a', 0o600);
    try {
      emulator = spawn('python3', [path.join(root, 'emulator_proxy.py'), '--avd', avd,
        '-camera-front', `videofile:${liveFile}`], { cwd: root, detached: true, stdio: ['ignore', log, log] });
      emulator.unref();
    } finally { fs.closeSync(log); }
    emulator.on('error', error => setState('error', error.message, { phone: false }));
    await waitForBoot();
    await startController();
  } catch (error) { setState('error', error.message, { phone: false }); }
}
async function startController() {
  if (controller) return;
  try {
    setState('starting-controller', 'Android is ready; connecting the browser display.', { phone: true });
    controller = spawn(path.join(here, 'node_modules', '.bin', 'serve-emu'), [
      '-s', serial, '--host', '127.0.0.1', '--port', String(controllerPort), '--token', phoneToken,
      '--max-fps', displayFps, '--bit-rate', displayBitRate, '--max-size', displaySize,
    ], { cwd: here, env: { ...process.env, PATH: `${path.join(here, 'node_modules', '.bin')}${path.delimiter}${process.env.PATH || ''}` }, stdio: ['ignore', 'pipe', 'pipe'] });
    controller.stdout.on('data', (chunk) => process.stdout.write(`[controller] ${chunk}`));
    controller.stderr.on('data', (chunk) => process.stderr.write(`[controller] ${chunk}`));
    controller.on('error', error => setState('error', error.message, { phone: false }));
    await waitForController();
    controllerGeneration++;
    setState('ready', !liveCameraEnabled ? 'Phone control is ready. Android uses its directly connected camera.' : state.camera ? 'Phone control and live camera feed are connected.' : 'Phone control is ready. Tap Allow camera to connect your iPhone.', { phone: true });
  } catch (error) {
    setState('error', error.message, { phone: false });
  }
}
const authorized = (rawUrl) => new URL(rawUrl, 'https://bridge.invalid').searchParams.get('token') === pairToken;
const proxy = httpProxy.createProxyServer({ target: `http://127.0.0.1:${controllerPort}`, ws: true });
proxy.on('error', (_error, _request, response) => {
  response?.writeHead?.(503, { 'content-type': 'text/plain' }); response?.end?.('Phone controller is starting.');
});
function staticFile(response, name, type) {
  response.writeHead(200, { 'content-type': type, 'cache-control': 'no-store' });
  fs.createReadStream(path.join(web, name)).pipe(response);
}
const tlsServer = https.createServer({ cert: fs.readFileSync(cert), key: fs.readFileSync(key) }, (request, response) => {
  const url = new URL(request.url, `https://${lanIp}:${httpsPort}`);
  if (url.pathname === '/bridge/' || url.pathname === '/bridge') {
    if (!authorized(request.url)) { response.writeHead(401); return response.end('Invalid pairing token.'); }
    return staticFile(response, 'index.html', 'text/html; charset=utf-8');
  }
  if (url.pathname === '/bridge/app.js') return staticFile(response, 'app.js', 'text/javascript; charset=utf-8');
  if (url.pathname === '/bridge/style.css') return staticFile(response, 'style.css', 'text/css; charset=utf-8');
  if (url.pathname === '/bridge/config') {
    if (!authorized(request.url)) { response.writeHead(401); return response.end(); }
    response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    return response.end(JSON.stringify({ phoneUrl: `/?token=${phoneToken}`, avd, liveCamera: liveCameraEnabled, controllerGeneration }));
  }
  if (url.pathname === '/bridge/status') {
    if (!authorized(request.url)) { response.writeHead(401); return response.end(); }
    response.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' });
    return response.end(JSON.stringify(state));
  }
  return proxy.web(request, response);
});
const wss = new WebSocketServer({ noServer: true, maxPayload: 4 * 1024 * 1024 });
tlsServer.on('upgrade', (request, socket, head) => {
  const url = new URL(request.url, `https://${lanIp}:${httpsPort}`);
  if (url.pathname === '/bridge/camera') {
    if (!liveCameraEnabled) return socket.destroy();
    if (!authorized(request.url)) return socket.destroy();
    return wss.handleUpgrade(request, socket, head, (ws) => wss.emit('connection', ws));
  }
  return proxy.ws(request, socket, head);
});
wss.on('connection', (socket) => {
  cameraSocket?.close(1000, 'Replaced by a new camera connection');
  cameraSocket = socket;
  if (ffmpeg) ffmpeg.kill('SIGTERM');
  startDecoder(socket);
  socket.on('message', (data, binary) => {
    if (!binary || !ffmpeg?.stdin.writable) return;
    if (cameraSocket !== socket || data.length > 1024 * 1024 || ffmpeg.stdin.writableLength > 256 * 1024) return;
    ffmpeg.stdin.write(data);
  });
  socket.on('close', () => {
    if (cameraSocket !== socket) return;
    cameraSocket = null;
    ffmpeg?.stdin.end();
    state.camera = false;
    state.detail = 'Camera disconnected. Phone control remains available.';
    try { clearLiveFrame(); } catch (error) { process.stderr.write(`[camera] clear: ${error.message}\n`); }
  });
});
const secureUrl = `https://${lanIp}:${httpsPort}/bridge/?token=${pairToken}`;
const bootstrapUrl = `http://${lanIp}:${httpPort}/pair?token=${pairToken}`;
const bootstrap = http.createServer(async (request, response) => {
  const url = new URL(request.url, bootstrapUrl);
  if (url.pathname === '/ca.cer' && ca && fs.existsSync(ca)) {
    response.writeHead(200, { 'content-type': 'application/x-x509-ca-cert', 'content-disposition': 'attachment; filename="EMU-Bridge-CA.cer"' });
    return fs.createReadStream(ca).pipe(response);
  }
  if (!authorized(request.url)) { response.writeHead(401); return response.end('Invalid pairing token.'); }
  if (url.pathname === '/qr.png') {
    response.writeHead(200, { 'content-type': 'image/png', 'cache-control': 'no-store' });
    return response.end(await QRCode.toBuffer(bootstrapUrl, { width: 640, margin: 2 }));
  }
  response.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' });
  return response.end(`<!doctype html><meta name="viewport" content="width=device-width"><title>EMU Bridge</title><style>body{font:17px system-ui;background:#111;color:#eee;padding:28px;line-height:1.5}a{display:block;margin:18px 0;padding:16px;background:#d7ff3f;color:#111;border-radius:12px;text-decoration:none;font-weight:700}</style><h1>EMU phone bridge</h1><p>One-time setup: install and trust the CA in Settings, then open the controller.</p>${ca ? '<a href="/ca.cer">1. Install secure-camera certificate</a>' : ''}<a href="${secureUrl}">2. Open phone + camera</a>`);
});
tlsServer.listen(httpsPort, bind);
void waitForBoot().then(startController).catch(error => setState('error', error.message));
bootstrap.listen(httpPort, bind, async () => {
  process.stdout.write(`\nScan this QR from the iPhone:\n${await QRCode.toString(bootstrapUrl, { type: 'terminal', small: true })}\n${bootstrapUrl}\nSecure URL: ${secureUrl}\n`);
});
function shutdown() {
  controller?.kill('SIGTERM'); ffmpeg?.kill('SIGTERM');
  try { clearLiveFrame(); } finally { live?.close(); }
  process.exit(0);
}
process.on('SIGINT', shutdown); process.on('SIGTERM', shutdown);
