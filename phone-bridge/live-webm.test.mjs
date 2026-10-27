import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn, spawnSync } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { IvfFrames, LiveWebM } from './live-webm.mjs';

test('a looping decoder sees current frames in the seekable file without corruption', async () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'emu-live-webm-'));
  const filename = path.join(directory, 'live.webm');
  const encoded = spawnSync('ffmpeg', ['-v', 'error', '-f', 'lavfi', '-i',
    'testsrc2=size=640x480:rate=30:duration=1', '-c:v', 'libvpx-vp9', '-deadline', 'realtime',
    '-cpu-used', '8', '-g', '1', '-threads', '2', '-f', 'ivf', 'pipe:1']);
  assert.equal(encoded.status, 0, encoded.stderr.toString());
  const frames = [];
  const parser = new IvfFrames(frame => frames.push(frame));
  // Exercise framing across arbitrary network/pipe boundaries.
  for (let offset = 0; offset < encoded.stdout.length; offset += 37) parser.push(encoded.stdout.subarray(offset, offset + 37));
  assert.equal(frames.length, 30);
  const live = new LiveWebM(filename, frames[0]);
  const initialBytes = fs.statSync(filename).size;
  let index = 0;
  const timer = setInterval(() => live.update(frames[(++index * 7) % frames.length]), 100);
  const child = spawn('ffmpeg', ['-v', 'error', '-re', '-stream_loop', '-1', '-i', filename,
    '-t', '4', '-f', 'framemd5', 'pipe:1']);
  let output = '', errors = '';
  child.stdout.on('data', chunk => output += chunk);
  child.stderr.on('data', chunk => errors += chunk);
  try {
    const code = await new Promise((resolve, reject) => { child.on('error', reject); child.on('close', resolve); });
    assert.equal(code, 0, errors);
    assert.equal(errors, '');
    const rows = output.split('\n').filter(row => row && !row.startsWith('#'));
    assert.ok(rows.length >= 100, `Only ${rows.length} decoded frames`);
    for (const half of [rows.slice(0, rows.length / 2), rows.slice(rows.length / 2)]) {
      assert.ok(new Set(half.map(row => row.split(',').at(-1).trim())).size > 3, 'Decoder retained stale frames');
    }
    assert.equal(fs.statSync(filename).size, initialBytes, 'The live file must remain bounded');
  } finally {
    clearInterval(timer); live.close();
    fs.rmSync(directory, { recursive: true });
  }
});
