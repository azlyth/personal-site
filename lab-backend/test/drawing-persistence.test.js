const test = require('node:test');
const assert = require('node:assert');
const { createClient } = require('redis');
const { io } = require('socket.io-client');
const { dockerAvailable, startRedis } = require('./helpers/redis-container');
const { startServer } = require('./helpers/server-process');

const SESSION = 'global-drawing-canvas';
const PORT = 3998;
const skip = dockerAvailable() ? false : 'docker not available';

let redis;
let server;
let inspector;

test.before(async () => {
  if (skip) return;
  redis = await startRedis({ port: 6399, name: 'lab-test-redis-drawing' });
  server = await startServer({ port: PORT, redisUrl: redis.url });
  inspector = createClient({ url: redis.url });
  await inspector.connect();
});

test.after(async () => {
  if (inspector) await inspector.quit();
  if (server) await server.stop();
  if (redis) redis.stop();
});

async function storedStrokes() {
  const raw = await inspector.get(`drawing:${SESSION}`);
  return raw ? JSON.parse(raw).strokes : [];
}

async function waitForStrokes(count, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  let strokes = await storedStrokes();
  while (Date.now() < deadline && strokes.length < count) {
    await new Promise((r) => setTimeout(r, 100));
    strokes = await storedStrokes();
  }
  return strokes;
}

async function waitForEmptyCanvas(timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if ((await storedStrokes()).length === 0) return;
    await new Promise((r) => setTimeout(r, 50));
  }
  throw new Error('canvas was not cleared in persistence');
}

function once(socket, event, timeoutMs = 5000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`timed out waiting for "${event}"`)), timeoutMs);
    socket.once(event, (payload) => {
      clearTimeout(timer);
      resolve(payload);
    });
  });
}

async function connectPainter(t) {
  const socket = io(server.url, { transports: ['websocket'] });
  t.after(() => socket.close());
  socket.on('connect', () => socket.emit('create-drawing-session'));
  await once(socket, 'drawing-session-created');
  socket.emit('clear-drawing-canvas', { sessionId: SESSION });
  await once(socket, 'drawing-cleared');
  await waitForEmptyCanvas();
  return socket;
}

test('drawing strokes survive packets that arrive in the same batch', { skip, timeout: 60000 }, async (t) => {
  const painter = await connectPainter(t);

  // A fast straight swipe: the browser fires pointer events faster than a Redis
  // round trip, so the packets reach the server back to back in one read.
  const TOTAL = 100;
  for (let i = 0; i < TOTAL; i++) {
    painter.emit('drawing-data', {
      sessionId: SESSION,
      fromX: i, fromY: 10, toX: i + 1, toY: 10,
      color: '#000000', lineWidth: 3
    });
  }

  const strokes = await waitForStrokes(TOTAL);
  assert.strictEqual(strokes.length, TOTAL, `expected every stroke persisted, got ${strokes.length}/${TOTAL}`);
  assert.deepStrictEqual(strokes.map((s) => s.fromX), Array.from({ length: TOTAL }, (_, i) => i),
    'strokes should persist in the order they were drawn');
});

test('a batched stroke path is stored in order and broadcast to other clients', { skip, timeout: 60000 }, async (t) => {
  const painter = await connectPainter(t);

  const watcher = io(server.url, { transports: ['websocket'] });
  t.after(() => watcher.close());
  watcher.on('connect', () => watcher.emit('join-drawing-session', { sessionId: SESSION }));
  await once(watcher, 'drawing-session-joined');

  const appended = once(watcher, 'drawing-append');

  // One packet carrying the points collected since the last flush.
  const segments = [0, 1, 2, 3, 4].map((i) => ({ fromX: i, fromY: 20, toX: i + 1, toY: 20 }));
  painter.emit('drawing-data', { sessionId: SESSION, segments, color: '#ff0000', lineWidth: 3 });

  const update = await appended;
  assert.strictEqual(update.strokes.length, 5, 'watchers receive only the new strokes');
  assert.strictEqual(update.strokes[0].color, '#ff0000', 'colour comes from the packet envelope');

  const stored = await waitForStrokes(5);
  assert.deepStrictEqual(stored.map((s) => s.fromX), [0, 1, 2, 3, 4]);
  assert.ok(stored.every((s) => s.lineWidth === 3), 'line width comes from the packet envelope');
});
