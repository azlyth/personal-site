const test = require('node:test');
const assert = require('node:assert');
const DrawingStore = require('../drawing-store');

// Stand-in for the Redis layer whose latency is what opened the lost-update
// window in the first place.
function slowPersistence({ saveDelay = 30, initial = null } = {}) {
  const calls = { saves: 0, loads: 0 };
  let stored = initial;
  return {
    calls,
    get stored() { return stored; },
    async loadDrawingSession() {
      calls.loads++;
      await new Promise((r) => setTimeout(r, saveDelay));
      return stored;
    },
    async saveDrawingSession(sessionId, state) {
      calls.saves++;
      await new Promise((r) => setTimeout(r, saveDelay));
      stored = JSON.parse(JSON.stringify(state));
      return true;
    },
    serializeDrawingState(state) {
      return { ...state, players: Array.from(state.players.entries()) };
    }
  };
}

const segment = (x) => ({ fromX: x, fromY: 0, toX: x + 1, toY: 0, color: '#000000', lineWidth: 3 });

test('segments appended while a save is in flight are still persisted', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  store.appendSegments('s', [segment(0)]);
  store.appendSegments('s', [segment(1)]);
  store.appendSegments('s', [segment(2)]);

  await store.flushAll();

  assert.deepStrictEqual(persistence.stored.strokes.map((s) => s.fromX), [0, 1, 2]);
});

test('a burst of appends collapses into a bounded number of writes', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  for (let i = 0; i < 200; i++) store.appendSegments('s', [segment(i)]);
  await store.flushAll();

  assert.strictEqual(persistence.stored.strokes.length, 200);
  assert.ok(persistence.calls.saves <= 5, `expected writes to coalesce, got ${persistence.calls.saves}`);
});

test('state is read from persistence once, not on every append', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');
  await store.load('s');

  store.appendSegments('s', [segment(0)]);
  await store.flushAll();

  assert.strictEqual(persistence.calls.loads, 1);
});

test('clear empties the canvas and persists the empty state', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  store.appendSegments('s', [segment(0), segment(1)]);
  store.clear('s');
  await store.flushAll();

  assert.deepStrictEqual(store.getStrokes('s'), []);
  assert.deepStrictEqual(persistence.stored.strokes, []);
});

test('a clear issued mid-save is not undone by the in-flight write', async () => {
  const persistence = slowPersistence({ saveDelay: 40 });
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  store.appendSegments('s', [segment(0)]);
  await new Promise((r) => setTimeout(r, 10)); // let the save start
  store.clear('s');
  await store.flushAll();

  assert.deepStrictEqual(persistence.stored.strokes, []);
});

test('the canvas is capped so one session cannot grow without bound', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5, maxStrokes: 10 });
  await store.load('s');

  for (let i = 0; i < 25; i++) store.appendSegments('s', [segment(i)]);
  await store.flushAll();

  const kept = store.getStrokes('s');
  assert.strictEqual(kept.length, 10);
  assert.deepStrictEqual(kept.map((s) => s.fromX), [15, 16, 17, 18, 19, 20, 21, 22, 23, 24]);
});

test('players are tracked per session and restored as a Map from persisted state', async () => {
  const persistence = slowPersistence();
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  store.addPlayer('s', 'socket-1');
  store.addPlayer('s', 'socket-2');
  assert.strictEqual(store.playerCount('s'), 2);

  store.removePlayer('s', 'socket-1');
  assert.strictEqual(store.playerCount('s'), 1);

  await store.flushAll();
  assert.deepStrictEqual(persistence.stored.players.map(([id]) => id), ['socket-2']);
});

test('persisted strokes from a previous run are loaded back', async () => {
  const persistence = slowPersistence({
    initial: { strokes: [segment(7)], players: [['old-socket', {}]], createdAt: new Date().toISOString(), lastActivity: new Date().toISOString() }
  });
  const store = new DrawingStore(persistence, { flushIntervalMs: 5 });
  await store.load('s');

  assert.deepStrictEqual(store.getStrokes('s').map((s) => s.fromX), [7]);
});
