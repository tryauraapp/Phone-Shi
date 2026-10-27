const token = new URLSearchParams(location.search).get('token');
const start = document.querySelector('#start');
const video = document.querySelector('#camera');
const canvas = document.querySelector('#crop');
const ctx = canvas.getContext('2d', { alpha: false });
const status = document.querySelector('#status');
const detail = document.querySelector('#detail');
const cameraPanel = document.querySelector('.camera-panel');
const phonePanel = document.querySelector('.phone-panel');
const phone = document.querySelector('#phone');
const mirrorButton = document.querySelector('#mirror');
const endpoint = name => `/bridge/${name}?token=${encodeURIComponent(token)}`;
let socket, stream;
let mirrored = false;
let encoding = false;
let lastSent = 0;
let inFlight = 0;
let previewing = false;
let renderedGeneration = -1;
let acknowledgements = [];
let pollActive = false;
let lastAck = 0;
start.textContent = 'ALLOW CAMERA';
start.style.display = 'block';
mirrorButton.textContent = 'MIRROR: OFF';

// Mirroring affects the local self-view only. The camera data stays unmirrored.
mirrorButton.addEventListener('click', () => {
  mirrored = !mirrored;
  canvas.style.transform = mirrored ? 'scaleX(-1)' : '';
  mirrorButton.textContent = `MIRROR: ${mirrored ? 'ON' : 'OFF'}`;
});
function drawCrop() {
  if (video.readyState < 2) return;
  const ratio = 3 / 4;
  let sx = 0, sy = 0, sw = video.videoWidth, sh = video.videoHeight;
  if (sw / sh > ratio) { sw = sh * ratio; sx = (video.videoWidth - sw) / 2; }
  else { sh = sw / ratio; sy = (video.videoHeight - sh) / 2; }
  ctx.drawImage(video, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
}
function preview(now) {
  if (!previewing) return;
  drawCrop();
  // Acknowledgements follow the native-file update, bounding the in-flight queue.
  if (!encoding && inFlight < 2 && socket?.readyState === WebSocket.OPEN && socket.bufferedAmount < 128 * 1024 && now - lastSent >= 1000 / 24) {
    encoding = true;
    lastSent = now;
    canvas.toBlob(async blob => {
      try {
        if (blob && socket?.readyState === WebSocket.OPEN) {
          const bytes = await blob.arrayBuffer();
          if (socket?.readyState === WebSocket.OPEN) { socket.send(bytes); inFlight++; }
        }
      } finally { encoding = false; }
    }, 'image/jpeg', 0.72);
  }
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(preview);
  else requestAnimationFrame(preview);
}
async function poll() {
  if (pollActive) return;
  pollActive = true;
  try {
    if (inFlight > 0 && socket?.readyState === WebSocket.OPEN && performance.now() - lastAck > 5000) socket.close();
    const response = await fetch(endpoint('status'), { cache: 'no-store' });
    if (!response.ok) throw new Error(`Bridge returned ${response.status}`);
    const current = await response.json();
    acknowledgements = acknowledgements.filter(time => performance.now() - time < 1000);
    const fresh = current.camera && Date.now() - current.cameraLastFrameAt < 2000;
    status.textContent = fresh ? `LIVE · ${acknowledgements.length} FPS` : current.phase.replaceAll('-', ' ').toUpperCase();
    detail.textContent = current.detail;
    if (current.phase === 'ready') {
      const config = await fetch(endpoint('config'), { cache: 'no-store' }).then(r => r.json());
      if (renderedGeneration !== config.controllerGeneration) {
        phone.src = config.phoneUrl;
        renderedGeneration = config.controllerGeneration;
      }
      phonePanel.hidden = false;
      document.body.classList.add('running');
      if (!config.liveCamera) {
        cameraPanel.style.display = 'none';
        document.querySelector('main').style.gridTemplateColumns = '1fr';
        phonePanel.style.gridColumn = '1';
      }
    }
  } catch { status.textContent = 'RECONNECTING'; }
  finally { pollActive = false; }
}
setInterval(poll, 1000);
void poll();
start.addEventListener('click', async () => {
  start.disabled = true;
  try {
    if (!stream || stream.getVideoTracks().every(track => track.readyState === 'ended')) {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 }, frameRate: { ideal: 30, max: 30 } }, audio: false,
      });
      video.srcObject = stream;
      await video.play();
    }
    socket = new WebSocket(`${location.origin.replace('https:', 'wss:')}${endpoint('camera')}`);
    socket.binaryType = 'arraybuffer';
    socket.onmessage = event => {
      try {
        if (JSON.parse(event.data).ack) { lastAck = performance.now(); inFlight = Math.max(0, inFlight - 1); acknowledgements.push(lastAck); }
      } catch { /* Ignore unknown control messages. */ }
    };
    await new Promise((resolve, reject) => {
      socket.onopen = resolve;
      socket.onerror = () => reject(new Error('Camera connection failed. Tap to reconnect.'));
    });
    inFlight = 0;
    lastAck = performance.now();
    socket.onclose = () => {
      start.hidden = false; start.disabled = false; start.style.display = 'block';
      start.textContent = 'RECONNECT CAMERA';
    };
    if (!previewing) {
      previewing = true;
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(preview);
      else requestAnimationFrame(preview);
    }
    start.hidden = true;
    start.style.display = 'none';
  } catch (error) {
    start.disabled = false;
    detail.textContent = error.message;
  }
});
