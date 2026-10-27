// A bounded, seekable VP9 camera surface. No named pipe is exposed to QEMU.
import fs from 'node:fs';

const hex = value => Buffer.from(value, 'hex');
function size(value, bytes = 4) {
  const result = Buffer.alloc(bytes);
  let n = BigInt(value) | (1n << BigInt(7 * bytes));
  for (let i = bytes - 1; i >= 0; i--) { result[i] = Number(n & 255n); n >>= 8n; }
  return result;
}
function element(id, data) { return Buffer.concat([hex(id), size(data.length), data]); }
function uint(id, value) {
  const data = Buffer.alloc(4); data.writeUInt32BE(value); return element(id, data);
}
function float(id, value) {
  const data = Buffer.alloc(8); data.writeDoubleBE(value); return element(id, data);
}
const string = (id, value) => element(id, Buffer.from(value));

export class LiveWebM {
  constructor(filename, frame, { width = 640, height = 480, fps = 30, slots = 15, slotBytes = 65536, reuse = false } = {}) {
    this.slots = slots;
    this.slotBytes = slotBytes;
    this.fps = fps;
    this.frames = 0;
    const ebml = element('1a45dfa3', Buffer.concat([
      uint('4286', 1), uint('42f7', 1), uint('42f2', 4), uint('42f3', 8),
      string('4282', 'webm'), uint('4287', 4), uint('4285', 2),
    ]));
    const info = element('1549a966', Buffer.concat([
      uint('2ad7b1', 1000000), float('4489', slots * 1000 / fps),
      string('4d80', 'EMU Live'), string('5741', 'EMU Live'),
    ]));
    const tracks = element('1654ae6b', element('ae', Buffer.concat([
      uint('d7', 1), uint('73c5', 1), uint('83', 1), uint('9c', 0),
      string('86', 'V_VP9'), uint('23e383', Math.round(1e9 / fps)),
      element('e0', Buffer.concat([uint('b0', width), uint('ba', height)])),
    ])));
    const prefix = Buffer.concat([info, tracks]);
    const cues = element('1c53bb6b', Buffer.concat(Array.from({ length: slots }, (_, index) =>
      element('bb', Buffer.concat([
        uint('b3', Math.round(index * 1000 / fps)),
        element('b7', Buffer.concat([uint('f7', 1), uint('f1', prefix.length + index * slotBytes)])),
      ])))));
    const payloadBytes = prefix.length + slots * slotBytes + cues.length;
    const header = Buffer.concat([ebml, hex('18538067'), size(payloadBytes, 8), prefix]);
    this.offset = header.length;
    if (reuse && fs.existsSync(filename)) {
      const existing = fs.openSync(filename, 'r');
      try {
        const bytes = Buffer.alloc(header.length);
        fs.readSync(existing, bytes, 0, bytes.length, 0);
        if (!bytes.equals(header) || fs.fstatSync(existing).size !== header.length + slots * slotBytes + cues.length) {
          throw new Error('Refusing to overwrite an unrecognized live camera file.');
        }
      } finally { fs.closeSync(existing); }
      this.fd = fs.openSync(filename, 'r+');
    } else this.fd = fs.openSync(filename, 'wx', 0o600);
    try {
      fs.writeSync(this.fd, header);
      this.update(frame);
      fs.writeSync(this.fd, cues, 0, cues.length, this.offset + slots * slotBytes);
    } catch (error) { this.close(); throw error; }
  }
  update(frame) {
    // One complete cluster is replaced per pwrite; the file never grows or
    // disappears, and slow readers never accumulate a queue of old frames.
    const clusters = [];
    for (let index = 0; index < this.slots; index++) {
      const timestamp = uint('e7', Math.round(index * 1000 / this.fps));
      const block = element('a3', Buffer.concat([hex('81000080'), frame]));
      const spare = this.slotBytes - 8 - timestamp.length - block.length;
      if (spare < 5) throw new Error('Encoded frame exceeds the live WebM slot capacity.');
      clusters.push(Buffer.concat([
        hex('1f43b675'), size(this.slotBytes - 8), timestamp, block,
        hex('ec'), size(spare - 5), Buffer.alloc(spare - 5),
      ]));
    }
    for (let index = 0; index < clusters.length; index++) {
      const cluster = clusters[index];
      const count = fs.writeSync(this.fd, cluster, 0, cluster.length, this.offset + index * this.slotBytes);
      if (count !== cluster.length) throw new Error('Short write while updating live WebM.');
    }
    this.frames++;
  }
  close() { if (this.fd !== undefined) fs.closeSync(this.fd); this.fd = undefined; }
}

export class IvfFrames {
  constructor(onFrame) { this.pending = Buffer.alloc(0); this.header = false; this.onFrame = onFrame; }
  push(chunk) {
    this.pending = Buffer.concat([this.pending, chunk]);
    if (!this.header) {
      if (this.pending.length < 32) return;
      if (this.pending.toString('ascii', 0, 4) !== 'DKIF' || this.pending.toString('ascii', 8, 12) !== 'VP90') throw new Error('Expected VP9 IVF stream.');
      this.pending = this.pending.subarray(32); this.header = true;
    }
    while (this.pending.length >= 12) {
      const bytes = this.pending.readUInt32LE(0);
      if (bytes > 4 * 1024 * 1024) throw new Error('Invalid IVF frame length.');
      if (this.pending.length < 12 + bytes) return;
      const frame = this.pending.subarray(12, 12 + bytes);
      this.pending = this.pending.subarray(12 + bytes);
      this.onFrame(frame);
    }
  }
}
