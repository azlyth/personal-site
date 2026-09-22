const test = require('node:test');
const assert = require('node:assert');
const DrawingStore = require('../drawing-store');

function fakePersistence() {
  let stored = null;
  return {
    get stored() { return stored; },
    async loadDrawingSession() { return stored; },
    async saveDrawingSession(sessionId, state) {
      stored = JSON.parse(JSON.stringify(state));
      return true;
    },
    serializeDrawingState(state) {
      return { ...state, players: Array.from(state.players.entries()) };
    }
  };
}

const segment = (x) => ({ fromX: x, fromY: 0, toX: x + 1, toY: 0, color: '#000000', lineWidth: 9 });

async function canvas() {
  const store = new DrawingStore(fakePersistence(), { flushIntervalMs: 5 });
  await store.load('c');
  return store;
}

test('undo removes a whole stroke, not one segment of it', async () => {
  const store = await canvas();
  // One press-to-lift arrives as several packets, all carrying the same id.
  store.appendSegments('c', [segment(0), segment(1)], 'g1');
  store.appendSegments('c', [segment(2), segment(3)], 'g1');
  assert.equal(store.getStrokes('c').length, 4);

  assert.equal(store.undoLastGesture('c'), 4);
  assert.equal(store.getStrokes('c').length, 0);
});

test('undo takes the most recent stroke and leaves earlier ones', async () => {
  const store = await canvas();
  store.appendSegments('c', [segment(0), segment(1)], 'g1');
  store.appendSegments('c', [segment(2)], 'g2');

  assert.equal(store.undoLastGesture('c'), 1);
  const left = store.getStrokes('c');
  assert.equal(left.length, 2);
  assert.ok(left.every((stroke) => stroke.gesture === 'g1'));
});

test('undo walks back stroke by stroke and then stops', async () => {
  const store = await canvas();
  store.appendSegments('c', [segment(0)], 'g1');
  store.appendSegments('c', [segment(1)], 'g2');
  store.appendSegments('c', [segment(2)], 'g3');

  assert.equal(store.undoLastGesture('c'), 1);
  assert.equal(store.undoLastGesture('c'), 1);
  assert.equal(store.undoLastGesture('c'), 1);
  assert.equal(store.undoLastGesture('c'), 0);
  assert.equal(store.getStrokes('c').length, 0);
});

test('undo on an empty canvas is a no-op rather than an error', async () => {
  const store = await canvas();
  assert.equal(store.undoLastGesture('c'), 0);
});

test('only the trailing run comes off when two people draw at once', async () => {
  const store = await canvas();
  // Two drawers interleave: A, B, then A again. Undo is last-in-first-out, so
  // it takes A's most recent stroke and must not reach back through B's to
  // collect A's earlier one.
  store.appendSegments('c', [segment(0), segment(1)], 'a1');
  store.appendSegments('c', [segment(2)], 'b1');
  store.appendSegments('c', [segment(3), segment(4)], 'a2');

  assert.equal(store.undoLastGesture('c'), 2);
  const left = store.getStrokes('c');
  assert.deepEqual(left.map((stroke) => stroke.gesture), ['a1', 'a1', 'b1']);
});

test('strokes stored before gestures existed come off one at a time', async () => {
  const store = await canvas();
  // Not synthetic: a tab left open from before this shipped sends packets with
  // no gesture, and the whole canvas must not vanish on one undo.
  store.appendSegments('c', [segment(0), segment(1), segment(2)], undefined);

  assert.equal(store.undoLastGesture('c'), 1);
  assert.equal(store.getStrokes('c').length, 2);
});

test('an undone stroke does not come back from Redis', async () => {
  const store = await canvas();
  store.appendSegments('c', [segment(0)], 'g1');
  store.appendSegments('c', [segment(1)], 'g2');
  store.undoLastGesture('c');
  await store.flush('c');

  assert.equal(store.persistence.stored.strokes.length, 1);
  assert.equal(store.persistence.stored.strokes[0].gesture, 'g1');
});

test('appended strokes carry the gesture they were drawn in', async () => {
  const store = await canvas();
  const stored = store.appendSegments('c', [segment(0)], 'g1');
  assert.equal(stored[0].gesture, 'g1');
});
